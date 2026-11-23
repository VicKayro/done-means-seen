#!/usr/bin/env python3
"""End-of-turn guard (a Claude Code Stop hook).

Before Claude hands control back, rerun the static checks (typecheck, lint, build,
tests: whatever the map says) of every project it changed code in during the
session. If a check is red, Claude gets the turn back with the error (exit 2) and
keeps looping until it is green.

- A state already verified green (same commit, same changes) is not rerun.
- The same failing state blocks only once: if Claude stops again without changing
  anything, it has judged the failure not to be its own, and it is allowed to say so.
- At most `max_blocks` blocks per session.
- Any failure of the guard itself lets Claude through: it never blocks because of
  its own fault (command not found, timeout, unreadable map).

Config map: $VERIFY_MAP, or ~/.claude/verify.json.

Dry run on a past session, without blocking anything:
    python3 ~/.claude/hooks/verify_on_stop.py --dry-run <transcript.jsonl>
"""

from __future__ import annotations

import fnmatch
import glob
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
MAP = Path(os.environ.get("VERIFY_MAP", HOME / ".claude/verify.json"))
STATE = Path(os.environ.get("VERIFY_ON_STOP_STATE", HOME / ".claude/hooks/verify-on-stop.state.json"))
LOG = Path(os.environ.get("VERIFY_ON_STOP_LOG", HOME / ".claude/hooks/verify-on-stop.log"))

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Shell commands that write to files (in auto mode Claude often edits with sed or a heredoc).
BASH_WRITES = re.compile(
    r"sed -i|perl -p?i|>>?\s*[\"']?[~/\w.$]|\btee\b|<<|\bgit (commit|apply|am|merge|rebase|cherry-pick|checkout --)|\bpatch\b|\bmv\b|\bcp\b"
)
QUOTED_PATH = re.compile(r"[\"'](/(?:Users|home|private|tmp)/[^\"'\n]+)[\"']")
BARE_PATH = re.compile(r"(?<![\w\"'/])(/(?:Users|home|private|tmp)/[^\s\"';|&<>()]+)")
# Beyond this, let Claude through without judging: a dependency folder emptied by a
# file-sync service can take ten minutes to read back, and the end of a turn must not wait that long.
COMMAND_TIMEOUT = 180
OUTPUT_TAIL = 60


def log(line):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass


def tool_env():
    """The hook may run with a reduced PATH (desktop app): put the usual tool folders first."""
    env = dict(os.environ)
    node_bins = sorted(glob.glob(str(HOME / ".nvm/versions/node/*/bin")))
    first = [str(HOME / ".local/bin")] + node_bins[-1:] + ["/opt/homebrew/bin", "/usr/local/bin"]
    env["PATH"] = ":".join(first + [env.get("PATH", "/usr/bin:/bin")])
    return env


def git_bytes(root, *args) -> bytes | None:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=60)
    if r.returncode != 0:
        return None
    return r.stdout


def git(root, *args) -> str | None:
    out = git_bytes(root, *args)
    return None if out is None else out.decode(errors="replace").strip()


def git_root(path, cache):
    p = Path(path).expanduser()
    while not p.exists() and p != p.parent:
        p = p.parent
    if p.is_file():
        p = p.parent
    if p in cache:
        return cache[p]
    root = git(p, "rev-parse", "--show-toplevel")
    cache[p] = Path(root) if root else None
    return cache[p]


def touched_paths(transcript):
    """Files and folders the session wrote to: edit tools plus shell commands that write."""
    touched = set()
    with open(transcript, errors="replace") as f:
        for line in f:
            if '"tool_use"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            content = (entry.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name, inputs = block.get("name"), block.get("input") or {}
                if name in WRITE_TOOLS:
                    path = inputs.get("file_path") or inputs.get("notebook_path")
                    if path:
                        touched.add(path)
                elif name == "Bash":
                    command = inputs.get("command") or ""
                    if not BASH_WRITES.search(command):
                        continue
                    found = QUOTED_PATH.findall(command) + BARE_PATH.findall(command)
                    touched.update(found)
                    if not found and entry.get("cwd"):
                        touched.add(entry["cwd"])
    return touched


def as_list(value):
    if not value:
        return []
    return [value] if isinstance(value, str) else list(value)


def project_by_folder(path, vmap):
    """Project recognised by its folder (`folder` in the map), deepest first: works without a git repo of its own."""
    p = Path(path).expanduser()
    for ancestor in [p, *p.parents]:
        if not ancestor.is_dir():  # a glob like "*/scripts*" must match the folder, never the file itself
            continue
        for project in vmap.get("projects", []):
            patterns = [os.path.expanduser(m) for m in as_list(project.get("folder"))]
            if any(fnmatch.fnmatch(str(ancestor), m) for m in patterns):
                return ancestor, project
    return None


def repo_name(remote):
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", remote.strip(), re.I)
    return m.group(1).lower() if m else ""


def project_of(root, vmap):
    """Project recognised by its GitHub repo: exact "owner/name", or bare "name" (leash is not leash-ops)."""
    name = repo_name(git(root, "remote", "get-url", "origin") or "")
    if not name:
        return None
    for project in vmap.get("projects", []):
        for r in (r.lower() for r in as_list(project.get("repo"))):
            if name == r or ("/" not in r and name.split("/")[1] == r):
                return project
    return None


def is_repo(root):
    top = git(root, "rev-parse", "--show-toplevel")
    return bool(top) and Path(top).resolve() == Path(root).resolve()


IGNORED_DIRS = {"node_modules", "venv", "__pycache__", "dist", "build", "logs", "data", "out"}


def folder_fingerprint(root):
    """Project without its own git repo: fingerprint = names, sizes and dates of the code files."""
    h, n = hashlib.sha1(), 0
    for folder, subdirs, files in os.walk(root):
        subdirs[:] = sorted(d for d in subdirs if d not in IGNORED_DIRS and not d.startswith("."))
        for name in sorted(files):
            path = Path(folder) / name
            try:
                st = path.stat()
            except OSError:
                continue
            h.update(f"{path.relative_to(root)}:{st.st_size}:{st.st_mtime_ns}".encode())
            n += 1
            if n > 20000:
                return h.hexdigest()
    return h.hexdigest()


def fingerprint(root):
    if not is_repo(root):
        h = hashlib.sha1(folder_fingerprint(root).encode())
        for folder in ("node_modules", ".venv"):
            try:
                h.update(f"{folder}:{(root / folder).stat().st_mtime_ns}".encode())
            except OSError:
                pass
        return h.hexdigest()
    h = hashlib.sha1()
    h.update((git(root, "rev-parse", "HEAD") or "").encode())
    h.update(git_bytes(root, "diff", "HEAD") or b"")
    for name in (git(root, "ls-files", "-o", "--exclude-standard") or "").splitlines():
        try:
            st = (root / name).stat()
            h.update(f"{name}:{st.st_size}:{st.st_mtime_ns}".encode())
        except OSError:
            pass
    # Dependencies installed between two turns (npm ci, uv sync): the state changes even if git does not see it.
    for folder in ("node_modules", ".venv"):
        try:
            h.update(f"{folder}:{(root / folder).stat().st_mtime_ns}".encode())
        except OSError:
            pass
    return h.hexdigest()


def changed_files(root, patterns):
    base = None
    for ref in ("origin/HEAD", "origin/main", "origin/master"):
        base = git(root, "merge-base", "HEAD", ref)
        if base:
            break
    names = set((git(root, "diff", "--name-only", "--diff-filter=d", base or "HEAD") or "").splitlines())
    names |= set((git(root, "ls-files", "-o", "--exclude-standard") or "").splitlines())
    return sorted(n for n in names if n and any(fnmatch.fnmatch(n, m) for m in patterns) and (root / n).exists())


def verify(root, project, env):
    """Return (ok, command, output). ok=None: the guard could not judge, let Claude through."""
    for step in project.get("static", []):
        if "{changed}" in step:
            if not is_repo(root):
                continue
            changed = changed_files(root, project.get("changed_glob", ["*"]))
            if not changed:
                continue
            step = step.replace("{changed}", " ".join(shlex.quote(c) for c in changed))
        try:
            r = subprocess.run(step, shell=True, executable="/bin/bash", cwd=root, env=env,
                               capture_output=True, timeout=COMMAND_TIMEOUT)
        except subprocess.TimeoutExpired:
            return None, step, f"timed out after {COMMAND_TIMEOUT} s"
        output = (r.stdout + r.stderr).decode(errors="replace")
        if r.returncode in (126, 127):
            return None, step, output
        if r.returncode != 0:
            return False, step, output
    return True, None, ""


def read_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"green": {}, "sessions": {}}


def write_state(state):
    sessions = state.get("sessions", {})
    if len(sessions) > 300:
        for key in sorted(sessions, key=lambda k: sessions[k].get("seen", 0))[:-300]:
            del sessions[key]
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=1))
    except OSError:
        pass


def block_message(failures, attempt, max_blocks):
    lines = []
    for name, command, output in failures:
        tail = "\n".join(output.strip().splitlines()[-OUTPUT_TAIL:])
        lines += [
            f"ERROR: the check for {name} fails after your changes.",
            f"  command: {command}",
            "--- end of output ---", tail, "---",
        ]
    lines += [
        "WHY: \"done\" means the checks are green (CLAUDE.md, rule 1).",
        "FIX: read the output, fix the cause, and hand back: the check reruns by itself.",
        "If the failure is not caused by your changes (it was there before, or comes from another session),",
        "say so in one line in your answer and hand back without changing anything: the hook will let you through.",
        f"(block {attempt} of {max_blocks} for this session)",
    ]
    return "\n".join(lines)


def main():
    dry_run = len(sys.argv) == 3 and sys.argv[1] == "--dry-run"
    if dry_run:
        hook_input = {"session_id": "dry-run", "transcript_path": sys.argv[2]}
    else:
        hook_input = json.load(sys.stdin)
    vmap = json.loads(MAP.read_text())
    if not dry_run and not (vmap.get("guard_enabled") or os.environ.get("VERIFY_ON_STOP_FORCE")):
        return 0
    session = hook_input.get("session_id", "?")
    transcript = hook_input.get("transcript_path")
    if not transcript or not os.path.exists(transcript):
        return 0

    cache, targets = {}, {}
    for path in touched_paths(transcript):
        found = project_by_folder(path, vmap)
        if not found:
            root = git_root(path, cache)
            project = project_of(root, vmap) if root else None
            found = (root, project) if project else None
        if found:
            targets[found[0]] = found[1]

    state = read_state()
    s = state.setdefault("sessions", {}).setdefault(session, {"blocks": 0, "failures": {}})
    s["seen"] = time.time()
    max_blocks = vmap.get("max_blocks", 3)
    env = tool_env()
    failures = []
    for root in sorted(targets):
        project = targets[root]
        fp = fingerprint(root)
        if state.setdefault("green", {}).get(str(root)) == fp:
            log(f"{session[:8]} {project['name']} already green")
            continue
        if s["failures"].get(str(root)) == fp:
            log(f"{session[:8]} {project['name']} same failure, unchanged, Claude handed back: letting it through")
            continue
        start = time.time()
        ok, command, output = verify(root, project, env)
        duration = round(time.time() - start)
        if ok:
            state["green"][str(root)] = fp
            s["failures"].pop(str(root), None)
            log(f"{session[:8]} {project['name']} green ({duration} s) {root}")
        elif ok is None:
            log(f"{session[:8]} {project['name']} not judged ({duration} s): {command}: {output.strip()[-200:]}")
        else:
            s["failures"][str(root)] = fp
            failures.append((project["name"], command, output))
            log(f"{session[:8]} {project['name']} FAILED ({duration} s): {command}")

    if failures and s["blocks"] < max_blocks:
        s["blocks"] += 1
        message = block_message(failures, s["blocks"], max_blocks)
        if dry_run:
            print(f"[dry run] would have blocked with:\n{message}")
            return 0
        write_state(state)
        print(message, file=sys.stderr)
        return 2
    if dry_run:
        print(f"[dry run] projects touched: {[str(r) for r in sorted(targets)] or 'none'}; nothing to block")
        return 0
    write_state(state)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # the guard never blocks because of its own failure
        log(f"guard failure: {e!r}")
        sys.exit(0)
