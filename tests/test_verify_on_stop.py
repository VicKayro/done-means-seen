"""End-to-end tests for hooks/verify_on_stop.py and hooks/syntax_check.py.

Each test builds a throwaway git repo, a verify map and a fake Claude Code
transcript, then runs the real hook in a subprocess with the Stop-hook JSON on
stdin, exactly as Claude Code does. Nothing touches ~/.claude: HOME, the map,
the state and the log all live in pytest's temp folder.

    uv run --with pytest python -m pytest -q tests/
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "verify_on_stop.py"
SYNTAX = ROOT / "hooks" / "syntax_check.py"


class Sandbox:
    def __init__(self, tmp: Path):
        self.tmp = tmp.resolve()
        self.repo = self.tmp / "demo"
        self.map = self.tmp / "verify.json"
        self.state = self.tmp / "state.json"
        self.log = self.tmp / "verify-on-stop.log"
        self.transcript = self.tmp / "transcript.jsonl"
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.tmp / "home"),
            "VERIFY_MAP": str(self.map),
            "VERIFY_ON_STOP_STATE": str(self.state),
            "VERIFY_ON_STOP_LOG": str(self.log),
            "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        (self.tmp / "home").mkdir()

    # -- setup helpers
    def git(self, *args, cwd=None):
        subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env, check=True, capture_output=True)

    def make_repo(self, files: dict[str, str]):
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("remote", "add", "origin", "https://github.com/acme/demo.git")
        for name, text in files.items():
            (self.repo / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")

    def write_map(self, static, guard_enabled=True, max_blocks=3, **project):
        project = {"name": "demo", "repo": "acme/demo", "static": static, **project}
        self.map.write_text(json.dumps({"guard_enabled": guard_enabled, "max_blocks": max_blocks, "projects": [project]}))

    def write_transcript(self, *tool_uses):
        lines = [json.dumps({"type": "user", "message": {"content": "fix the status file"}})]
        for name, tool_input in tool_uses:
            lines.append(json.dumps({
                "type": "assistant", "cwd": str(self.tmp),
                "message": {"content": [{"type": "tool_use", "name": name, "input": tool_input}]},
            }))
        self.transcript.write_text("\n".join(lines) + "\n")

    def edit(self, name):
        return ("Edit", {"file_path": str(self.repo / name), "old_string": "a", "new_string": "b"})

    # -- running the hook
    def stop(self, session="sess-0001", extra_env=None, after_block=False):
        # after_block: Claude Code sets stop_hook_active when a Stop hook sent Claude back to work;
        # it is false on the first stop after a new message from the user.
        payload = {"session_id": session, "transcript_path": str(self.transcript), "hook_event_name": "Stop",
                   "stop_hook_active": after_block}
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                              capture_output=True, env={**self.env, **(extra_env or {})}, timeout=120)

    def dry_run(self):
        return subprocess.run([sys.executable, str(HOOK), "--dry-run", str(self.transcript)], text=True,
                              capture_output=True, env=self.env, timeout=120)

    def log_text(self):
        return self.log.read_text() if self.log.exists() else ""


CHECK_OK = "grep -qx ok status.txt"


@pytest.fixture
def sb(tmp_path):
    s = Sandbox(tmp_path)
    s.make_repo({"status.txt": "ok\n"})
    s.write_map([CHECK_OK])
    s.write_transcript(s.edit("status.txt"))
    return s


def test_red_check_blocks_with_error_why_fix(sb):
    (sb.repo / "status.txt").write_text("broken\n")
    r = sb.stop()
    assert r.returncode == 2
    assert "ERROR: the check for demo fails after your changes." in r.stderr
    assert f"command: {CHECK_OK}" in r.stderr
    assert "WHY:" in r.stderr and "FIX:" in r.stderr
    assert "say so in one line" in r.stderr
    assert "(block 1 of 3 for this request)" in r.stderr
    assert "demo FAILED" in sb.log_text()
    assert "BLOCKED (1 of 3 for this request): demo" in sb.log_text()


def test_same_red_state_blocks_only_once(sb):
    (sb.repo / "status.txt").write_text("broken\n")
    assert sb.stop().returncode == 2
    second = sb.stop(after_block=True)
    assert second.returncode == 0, second.stderr
    assert "same failure, unchanged" in sb.log_text()


def test_green_once_fixed_then_skipped(sb):
    (sb.repo / "status.txt").write_text("broken\n")
    assert sb.stop().returncode == 2
    (sb.repo / "status.txt").write_text("ok\n")
    fixed = sb.stop()
    assert fixed.returncode == 0, fixed.stderr
    assert "demo green" in sb.log_text()
    again = sb.stop()
    assert again.returncode == 0
    assert "demo already green" in sb.log_text()


def test_guard_disabled_lets_through_unless_forced(sb):
    sb.write_map([CHECK_OK], guard_enabled=False)
    (sb.repo / "status.txt").write_text("broken\n")
    assert sb.stop().returncode == 0
    assert sb.stop(session="sess-forced", extra_env={"VERIFY_ON_STOP_FORCE": "1"}).returncode == 2


def test_unreadable_map_never_blocks(sb):
    sb.map.write_text("{this is not json")
    (sb.repo / "status.txt").write_text("broken\n")
    r = sb.stop()
    assert r.returncode == 0
    assert "guard failure" in sb.log_text()


def test_missing_map_never_blocks(sb):
    sb.map.unlink()
    assert sb.stop().returncode == 0
    assert "guard failure" in sb.log_text()


def test_bash_sed_counts_as_a_write(sb):
    sb.write_transcript(("Bash", {"command": f"sed -i '' 's/ok/broken/' \"{sb.repo / 'status.txt'}\""}))
    (sb.repo / "status.txt").write_text("broken\n")
    assert sb.stop().returncode == 2


def test_read_only_bash_is_not_a_write(sb):
    sb.write_transcript(("Bash", {"command": f"cat \"{sb.repo / 'status.txt'}\""}))
    (sb.repo / "status.txt").write_text("broken\n")
    assert sb.stop().returncode == 0
    assert "demo" not in sb.log_text()


def test_project_not_in_map_is_ignored(sb):
    sb.write_map([CHECK_OK], repo="acme/other")
    (sb.repo / "status.txt").write_text("broken\n")
    assert sb.stop().returncode == 0


def test_bare_repo_name_matches(sb):
    sb.write_map([CHECK_OK], repo="demo")
    (sb.repo / "status.txt").write_text("broken\n")
    assert sb.stop().returncode == 2


def test_changed_expands_to_matching_changed_files_only(tmp_path):
    sb = Sandbox(tmp_path)
    sb.make_repo({"a.py": "x = 1\n", "b.py": "y = 2\n", "notes.md": "hi\n"})
    sb.write_map(["echo CHANGED: {changed}; exit 1"], changed_glob=["*.py"])
    (sb.repo / "a.py").write_text("x = 3\n")
    (sb.repo / "notes.md").write_text("changed\n")
    (sb.repo / "c.py").write_text("z = 4\n")  # new, untracked
    sb.write_transcript(sb.edit("a.py"))
    r = sb.stop()
    assert r.returncode == 2
    out = [line for line in r.stderr.splitlines() if line.startswith("CHANGED:")]
    assert out == ["CHANGED: a.py c.py"]


def test_changed_step_skipped_when_nothing_matches(tmp_path):
    sb = Sandbox(tmp_path)
    sb.make_repo({"a.py": "x = 1\n", "notes.md": "hi\n"})
    sb.write_map(["echo CHANGED: {changed}; exit 1"], changed_glob=["*.py"])
    (sb.repo / "notes.md").write_text("changed\n")
    sb.write_transcript(sb.edit("notes.md"))
    assert sb.stop().returncode == 0
    assert "demo green" in sb.log_text()


def test_max_blocks_per_request(sb):
    sb.write_map([CHECK_OK], max_blocks=2)
    codes = []
    for n in range(3):
        (sb.repo / "status.txt").write_text(f"broken {n}\n")  # a new failing state each time
        r = sb.stop(after_block=n > 0)
        codes.append(r.returncode)
        if r.returncode == 2:
            assert f"(block {n + 1} of 2 for this request)" in r.stderr
    assert codes == [2, 2, 0]
    log = sb.log_text()
    assert log.count("BLOCKED") == 2
    assert "block limit reached (2 for this request): letting Claude through on red" in log


def test_a_new_request_gets_its_own_blocks(sb):
    # A long session: the limit reached on one request must not disarm the hook for the next ones.
    sb.write_map([CHECK_OK], max_blocks=1)
    (sb.repo / "status.txt").write_text("broken 0\n")
    assert sb.stop().returncode == 2
    (sb.repo / "status.txt").write_text("broken 1\n")
    assert sb.stop(after_block=True).returncode == 0  # same request, limit reached
    (sb.repo / "status.txt").write_text("broken 2\n")
    nxt = sb.stop()  # the user wrote again: stop_hook_active is false
    assert nxt.returncode == 2, nxt.stderr
    assert "(block 1 of 1 for this request)" in nxt.stderr


def test_command_not_found_is_not_judged(sb):
    sb.write_map(["definitely-not-a-real-command-xyz"])
    r = sb.stop()
    assert r.returncode == 0
    assert "not judged" in sb.log_text()


def test_folder_project_without_its_own_repo(tmp_path):
    sb = Sandbox(tmp_path)
    scripts = sb.tmp / "scripts"
    scripts.mkdir()
    (scripts / "status.txt").write_text("broken\n")
    sb.map.write_text(json.dumps({"guard_enabled": True, "projects": [
        {"name": "scripts", "folder": str(sb.tmp / "scrip*"), "static": [CHECK_OK]}]}))
    sb.write_transcript(("Write", {"file_path": str(scripts / "status.txt"), "content": "broken\n"}))
    r = sb.stop()
    assert r.returncode == 2
    assert "the check for scripts fails" in r.stderr


def test_dry_run_prints_and_never_blocks(sb):
    sb.write_map([CHECK_OK], guard_enabled=False)  # a dry run ignores the switch
    (sb.repo / "status.txt").write_text("broken\n")
    r = sb.dry_run()
    assert r.returncode == 0
    assert "[dry run] would have blocked with:" in r.stdout
    assert "ERROR: the check for demo fails" in r.stdout
    assert not sb.state.exists()


def test_dry_run_with_nothing_to_block(sb):
    r = sb.dry_run()
    assert r.returncode == 0
    assert "nothing to block" in r.stdout


# ---------------------------------------------------------------- syntax_check.py

def run_syntax(folder):
    return subprocess.run([sys.executable, str(SYNTAX), str(folder)], text=True, capture_output=True, timeout=60)


def test_syntax_check_flags_a_broken_python_file(tmp_path):
    (tmp_path / "good.py").write_text("print('ok')\n")
    (tmp_path / "bad.py").write_text("def broken(:\n")
    (tmp_path / "conf.json").write_text('{"a": 1}')
    r = run_syntax(tmp_path)
    assert r.returncode == 1
    assert "ERROR bad.py" in r.stdout
    assert "1 with errors" in r.stdout


def test_syntax_check_passes_clean_folder(tmp_path):
    (tmp_path / "good.py").write_text("print('ok')\n")
    (tmp_path / "run.sh").write_text("#!/bin/bash\necho ok\n")
    (tmp_path / "conf.json").write_text('{"a": 1}')
    skipped = tmp_path / "node_modules"
    skipped.mkdir()
    (skipped / "bad.py").write_text("def broken(:\n")
    r = run_syntax(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "3 files read, 0 with errors" in r.stdout
