#!/usr/bin/env bash
# Install done-means-seen from this clone into ~/.claude and ~/.local/bin.
#
#   ./install.sh            install (never overwrites without a backup, safe to rerun)
#   ./install.sh --dry-run  print every action, write nothing
#
# The Stop hook is installed switched off ("guard_enabled": false in ~/.claude/verify.json):
# replay a past session with --dry-run first, then switch it on.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
BIN_DIR="$HOME/.local/bin"
STAMP="$(date +%Y%m%d%H%M%S)"
HOOK_CMD='python3 "$HOME/.claude/hooks/verify_on_stop.py"'

DRY=0
case "${1:-}" in
  "") ;;
  --dry-run) DRY=1 ;;
  -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "Unknown option: $1 (use --dry-run or --help)" >&2; exit 2 ;;
esac

TILDE='~'
# Paths are shown with ~ for readability.
show() { printf '%s' "${1/#$HOME/$TILDE}"; }
step() {
  if [ "$DRY" = 1 ]; then echo "■ [dry run] $*"; else echo "■ $*"; fi
}
# Run a command, or do nothing in a dry run (the step line already says what it would do).
run() {
  [ "$DRY" = 1 ] || "$@"
}

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required (3.9 or later)." >&2; exit 1; }

[ "$DRY" = 1 ] && echo "Dry run: nothing will be written."
echo "Installing done-means-seen from $(show "$REPO")"
echo

# Copy a file, backing up a different existing file first. Same content: nothing to do.
install_file() {
  local src="$1" dst="$2"
  if [ -e "$dst" ] && cmp -s "$src" "$dst"; then
    step "$(show "$dst") is up to date"
    return
  fi
  if [ -e "$dst" ]; then
    step "backing up $(show "$dst") to $(show "$dst").bak-$STAMP"
    run cp -p "$dst" "$dst.bak-$STAMP"
  fi
  step "copying $(basename "$src") to $(show "$dst")"
  run cp "$src" "$dst"
}

run mkdir -p "$CLAUDE_DIR/hooks" "$CLAUDE_DIR/skills/andon" "$BIN_DIR"

# 1. The hooks.
for f in verify_on_stop.py syntax_check.py icloud_nosync.sh; do
  install_file "$REPO/hooks/$f" "$CLAUDE_DIR/hooks/$f"
done

# 2. The verify map, born switched off. An existing map is never touched.
if [ -e "$CLAUDE_DIR/verify.json" ]; then
  step "~/.claude/verify.json already exists, left as is"
else
  step "creating ~/.claude/verify.json from the example, with the guard switched off"
  if [ "$DRY" = 0 ]; then
    python3 - "$REPO/config/verify.example.json" "$CLAUDE_DIR/verify.json" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
data = json.load(open(src, encoding="utf-8"))
data["guard_enabled"] = False
with open(dst, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY
  fi
fi

# 3. The Stop hook in settings.json: every other key and hook is kept, never added twice.
SETTINGS="$CLAUDE_DIR/settings.json"
if [ -e "$SETTINGS" ] && grep -q "verify_on_stop.py" "$SETTINGS"; then
  step "~/.claude/settings.json already has the Stop hook"
else
  if [ -e "$SETTINGS" ]; then
    step "backing up ~/.claude/settings.json to ~/.claude/settings.json.bak-$STAMP"
    run cp -p "$SETTINGS" "$SETTINGS.bak-$STAMP"
  fi
  step "adding the Stop hook to ~/.claude/settings.json"
  if [ "$DRY" = 0 ]; then
    python3 - "$SETTINGS" "$HOOK_CMD" <<'PY'
import json, os, sys
path, command = sys.argv[1], sys.argv[2]
settings = {}
if os.path.exists(path):
    text = open(path, encoding="utf-8").read().strip()
    if text:
        settings = json.loads(text)
if not isinstance(settings, dict):
    sys.exit(f"ERROR: {path} is not a JSON object, left untouched.")
stop = settings.setdefault("hooks", {}).setdefault("Stop", [])
already = any("verify_on_stop.py" in (h.get("command") or "")
              for group in stop for h in (group.get("hooks") or []))
if not already:
    stop.append({"hooks": [{
        "type": "command",
        "command": command,
        "timeout": 600,
        "statusMessage": "End-of-turn verification",
    }]})
with open(path, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY
  fi
fi

# 4. The rules. An existing CLAUDE.md is yours: merge by hand.
if [ -e "$CLAUDE_DIR/CLAUDE.md" ]; then
  step "~/.claude/CLAUDE.md already exists, not overwritten. Merge by hand: diff \"$REPO/CLAUDE.md\" ~/.claude/CLAUDE.md"
else
  step "copying CLAUDE.md to ~/.claude/CLAUDE.md (replace \"Victor\" with your name)"
  run cp "$REPO/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"
fi

# 5. Andon: the command and the skill.
step "linking ~/.local/bin/andon to $(show "$REPO")/andon/andon.py"
run ln -sf "$REPO/andon/andon.py" "$BIN_DIR/andon"
install_file "$REPO/andon/SKILL.md" "$CLAUDE_DIR/skills/andon/SKILL.md"

# Next steps.
LATEST=""
if [ -d "$CLAUDE_DIR/projects" ]; then
  LATEST="$(ls -t "$CLAUDE_DIR"/projects/*/*.jsonl 2>/dev/null | head -1 || true)"
fi
echo
echo "Next steps"
echo "  1. Put your projects and their check commands in ~/.claude/verify.json."
if [ -n "$LATEST" ]; then
  echo "  2. Replay your latest session without blocking anything:"
  echo "       python3 ~/.claude/hooks/verify_on_stop.py --dry-run \"$LATEST\""
else
  echo "  2. No past session found in ~/.claude/projects yet. After your next session, replay it:"
  echo "       python3 ~/.claude/hooks/verify_on_stop.py --dry-run ~/.claude/projects/<project>/<session>.jsonl"
fi
echo "  3. When the dry run looks right, set \"guard_enabled\": true in ~/.claude/verify.json."
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "  Note: ~/.local/bin is not on your PATH, add it to run \`andon\` from anywhere." ;;
esac
[ "$DRY" = 1 ] && echo && echo "Dry run: nothing was written."
exit 0
