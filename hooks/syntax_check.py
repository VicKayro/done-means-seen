#!/usr/bin/env python3
"""Syntax check for a folder of scripts, run from its root (or given as an argument).

For projects with no typecheck, build or tests (a folder of cron scripts, prompt
runners...): reads every .py (ast), .sh (bash -n), .js/.mjs/.cjs (node --check) and
.json file, without running or writing anything. New files are covered automatically.
Exits 1 if any file does not parse.

    python3 ~/.claude/hooks/syntax_check.py [folder]
"""

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

IGNORED = {"node_modules", "venv", "__pycache__", "dist", "build", "data", "logs", "out", "_archive"}
MAX_FILES = 3000
JSON_MAX_BYTES = 2_000_000


def files(root):
    n = 0
    for folder, subdirs, names in os.walk(root):
        subdirs[:] = sorted(d for d in subdirs if d not in IGNORED and not d.startswith("."))
        for name in sorted(names):
            yield Path(folder) / name
            n += 1
            if n >= MAX_FILES:
                return


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    node = shutil.which("node")
    errors, read = [], 0
    for f in files(root):
        rel = f.relative_to(root)
        try:
            if f.suffix == ".py":
                ast.parse(f.read_text(encoding="utf-8"), str(rel))
            elif f.suffix == ".sh":
                r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
                if r.returncode:
                    raise SyntaxError(r.stderr.strip())
            elif f.suffix in (".js", ".mjs", ".cjs") and node:
                r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
                if r.returncode:
                    raise SyntaxError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "node --check")
            elif f.suffix == ".json" and f.name != "package-lock.json" and f.stat().st_size < JSON_MAX_BYTES:
                json.loads(f.read_text(encoding="utf-8"))
            else:
                continue
            read += 1
        except (SyntaxError, ValueError, UnicodeDecodeError) as e:
            errors.append(f"{rel}: {e}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"{read} files read, {len(errors)} with errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
