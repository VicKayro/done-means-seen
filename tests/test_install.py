"""Tests for install.sh: run the real installer with HOME pointed at a temp folder.

    uv run --with pytest python -m pytest -q tests/test_install.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install.sh"
HOOK_FILES = ("verify_on_stop.py", "syntax_check.py", "icloud_nosync.sh")


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def env_for(home: Path) -> dict:
    # python3 must resolve to a real interpreter for the embedded merges and the hook run.
    py_dir = str(Path(sys.executable).parent)
    return {
        "HOME": str(home),
        "PATH": f"{py_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "LANG": "C.UTF-8",
    }


def install(home: Path, *args: str) -> subprocess.CompletedProcess:
    r = subprocess.run(["bash", str(INSTALL), *args], env=env_for(home), text=True,
                       capture_output=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def stop_hooks(home: Path) -> list[dict]:
    settings = json.loads((home / ".claude/settings.json").read_text())
    return [h for group in settings["hooks"]["Stop"] for h in group["hooks"]]


def snapshot(folder: Path) -> dict[str, bytes]:
    out = {}
    for p in sorted(folder.rglob("*")):
        if p.is_symlink():
            out[str(p.relative_to(folder))] = ("-> " + os.readlink(p)).encode()
        elif p.is_file():
            out[str(p.relative_to(folder))] = p.read_bytes()
    return out


def test_fresh_install_creates_everything(home):
    r = install(home)
    claude = home / ".claude"
    for f in HOOK_FILES:
        assert (claude / "hooks" / f).read_bytes() == (ROOT / "hooks" / f).read_bytes()
    vmap = json.loads((claude / "verify.json").read_text())
    assert vmap["guard_enabled"] is False
    assert vmap["projects"], "the example projects are copied"
    hooks = stop_hooks(home)
    assert len(hooks) == 1
    assert "verify_on_stop.py" in hooks[0]["command"] and hooks[0]["timeout"] == 600
    assert (claude / "CLAUDE.md").read_text() == (ROOT / "CLAUDE.md").read_text()
    assert (claude / "skills/andon/SKILL.md").read_text() == (ROOT / "andon/SKILL.md").read_text()
    link = home / ".local/bin/andon"
    assert link.is_symlink() and Path(os.readlink(link)) == ROOT / "andon/andon.py"
    assert "Next steps" in r.stdout and "guard_enabled" in r.stdout


def test_andon_link_runs(home):
    install(home)
    r = subprocess.run([str(home / ".local/bin/andon"), "catalogue"], env=env_for(home),
                       text=True, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "Causes" in r.stdout


def test_existing_settings_are_kept_and_backed_up(home):
    claude = home / ".claude"
    claude.mkdir()
    before = {
        "model": "opus",
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "echo other-stop-hook"}]}],
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo pre"}]}],
        },
    }
    (claude / "settings.json").write_text(json.dumps(before))
    install(home)
    after = json.loads((claude / "settings.json").read_text())
    assert after["model"] == "opus" and after["permissions"] == before["permissions"]
    assert after["hooks"]["PreToolUse"] == before["hooks"]["PreToolUse"]
    commands = [h["command"] for h in stop_hooks(home)]
    assert commands[0] == "echo other-stop-hook"
    assert sum("verify_on_stop.py" in c for c in commands) == 1
    backups = list(claude.glob("settings.json.bak-*"))
    assert len(backups) == 1 and json.loads(backups[0].read_text()) == before


def test_second_run_adds_nothing(home):
    install(home)
    first = snapshot(home)
    r = install(home)
    assert snapshot(home) == first
    assert "already has the Stop hook" in r.stdout
    assert len(stop_hooks(home)) == 1


def test_existing_claude_md_and_verify_map_are_never_overwritten(home):
    claude = home / ".claude"
    claude.mkdir()
    (claude / "CLAUDE.md").write_text("my own rules\n")
    (claude / "verify.json").write_text('{"guard_enabled": true, "projects": []}\n')
    r = install(home)
    assert (claude / "CLAUDE.md").read_text() == "my own rules\n"
    assert (claude / "verify.json").read_text() == '{"guard_enabled": true, "projects": []}\n'
    assert "Merge by hand" in r.stdout


def test_changed_hook_is_backed_up_before_being_replaced(home):
    hooks = home / ".claude/hooks"
    hooks.mkdir(parents=True)
    (hooks / "verify_on_stop.py").write_text("# an older local version\n")
    install(home)
    assert (hooks / "verify_on_stop.py").read_bytes() == (ROOT / "hooks/verify_on_stop.py").read_bytes()
    backups = list(hooks.glob("verify_on_stop.py.bak-*"))
    assert len(backups) == 1 and backups[0].read_text() == "# an older local version\n"


def test_dry_run_writes_nothing(home):
    r = install(home, "--dry-run")
    assert list(home.iterdir()) == []
    assert "[dry run]" in r.stdout and "nothing was written" in r.stdout


def test_dry_run_on_an_existing_setup_writes_nothing(home):
    install(home)
    before = snapshot(home)
    install(home, "--dry-run")
    assert snapshot(home) == before


def test_next_steps_point_at_the_latest_session(home):
    sessions = home / ".claude/projects/my-project"
    sessions.mkdir(parents=True)
    old, new = sessions / "old.jsonl", sessions / "new.jsonl"
    old.write_text("{}\n")
    new.write_text("{}\n")
    os.utime(old, (1_000_000_000, 1_000_000_000))
    r = install(home)
    assert f'--dry-run "{new}"' in r.stdout


def test_unknown_option_is_refused(home):
    r = subprocess.run(["bash", str(INSTALL), "--force"], env=env_for(home), text=True,
                       capture_output=True, timeout=60)
    assert r.returncode == 2
    assert list(home.iterdir()) == []


def test_installed_hook_runs(home, tmp_path):
    install(home)
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant", "cwd": str(tmp_path),
        "message": {"content": [{"type": "tool_use", "name": "Edit",
                                 "input": {"file_path": str(tmp_path / "x.py")}}]},
    }) + "\n")
    payload = json.dumps({"session_id": "s1", "transcript_path": str(transcript), "hook_event_name": "Stop"})
    command = stop_hooks(home)[0]["command"]  # exactly what Claude Code will run, through a shell
    r = subprocess.run(["bash", "-c", command], input=payload, env=env_for(home), text=True,
                       capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stderr == ""
