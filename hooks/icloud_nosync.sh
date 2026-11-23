#!/bin/bash
# Move a JS project's dependencies out of iCloud (macOS, Desktop/Documents synced).
#
# Why: when the Desktop is synced with "Optimize Mac Storage", iCloud evicts
# node_modules, and every read waits on the network or freezes (tsc going from 6 s to
# 28 min, next dev stuck at 0 % CPU on a .js.map, even an `ls` that never returns).
# Moving files iCloud already holds is not enough: reinstall from scratch.
#
# How: npm ci runs in a work folder outside the Desktop (never seen by iCloud), with a
# copy of package.json and package-lock.json; the result is moved in one go to
# node_modules.nosync/node_modules (the .nosync suffix keeps the folder out of iCloud)
# and node_modules becomes a symlink to it. The inner folder keeps the name
# node_modules: tsc, eslint, vitest and Node ignore it or find it on their own. Nothing
# is installed in the project and no file tracked by git changes (exclusions go to
# .git/info/exclude, package-lock.json is never rewritten). The old dependencies are
# set aside, then deleted in the background.
#
# A later npm ci run inside the project replaces the symlink with a real folder:
# rerunning this script puts everything back.
#
#   bash ~/.claude/hooks/icloud_nosync.sh "$HOME/Desktop/<project>"            # only if needed
#   bash ~/.claude/hooks/icloud_nosync.sh "$HOME/Desktop/<project>" --redo     # reinstall no matter what
set -euo pipefail

cd "$1"
REDO="${2:-}"
[ -f package.json ] || { echo "ERROR: no package.json in $PWD"; exit 1; }
if pgrep -f "$PWD/node_modules" >/dev/null; then
  echo "ERROR: a server or tool is running on $PWD (pgrep -fl \"$PWD/node_modules\"). Stop it, then rerun."
  exit 2
fi

if git rev-parse --git-dir >/dev/null 2>&1; then
  exclude="$(git rev-parse --git-path info/exclude)"
  mkdir -p "$(dirname "$exclude")"
  for pattern in "node_modules" "node_modules.nosync/" "node_modules.old-*.nosync/"; do
    grep -qxF "$pattern" "$exclude" 2>/dev/null || echo "$pattern" >> "$exclude"
  done
fi

TARGET="node_modules.nosync/node_modules"
if [ "$REDO" != "--redo" ] && [ -L node_modules ] && [ "$(readlink node_modules)" = "$TARGET" ] && [ -d "$TARGET/.bin" ]; then
  echo "OK: already outside iCloud ($PWD)"
  exit 0
fi

# 1. Fresh install, outside the Desktop.
mkdir -p "$HOME/.cache"
WORK="$(mktemp -d "$HOME/.cache/nosync.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
cp package.json "$WORK/"
[ -f package-lock.json ] && cp package-lock.json "$WORK/"
[ -f .npmrc ] && cp .npmrc "$WORK/"
if ! ( cd "$WORK" && { [ -f package-lock.json ] && npm ci --no-audit --no-fund || npm install --no-audit --no-fund; } ); then
  echo "ERROR: install failed, the project was not touched ($PWD)"
  exit 3
fi

# 2. Switch: the old folder is set aside (a rename, instant even if iCloud holds its files).
OLD="node_modules.old-$(date +%Y%m%d%H%M%S).nosync"
mkdir "$OLD"
[ -L node_modules ] && rm node_modules
[ -e node_modules ] && mv node_modules "$OLD/node_modules"
[ -e node_modules.nosync ] && mv node_modules.nosync "$OLD/nosync"
mkdir node_modules.nosync
mv "$WORK/node_modules" "$TARGET"
ln -s "$TARGET" node_modules

# 3. Delete the old folder in the background: a file held by iCloud does not hold the shell.
nohup rm -rf "$PWD/$OLD" >/dev/null 2>&1 &
echo "OK: reinstalled from scratch, $(find "$TARGET" -type f | wc -l | tr -d ' ') files outside iCloud ($PWD)"
