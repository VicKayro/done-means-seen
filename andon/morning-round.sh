#!/bin/bash
# Andon: the morning round. Run it from cron or launchd before your daily briefing.
# It only wakes a model when `andon.py todo` finds work: a check due, a countermeasure PR
# merged or closed, the review of chronic causes on Mondays. The model does not read
# production, writes to nobody and changes no repo: it runs the checks it can, dates the
# ones whose countermeasure is live, and hands back what belongs to you. Its report goes
# to last-round.md, for your briefing to pick up.
#
#   morning-round.sh             real run: the registry is committed and pushed if it changed
#                                (only when registry.json is tracked by git)
#   morning-round.sh --dry-run   works on a copy of the registry in a temp folder, writes nothing here
#
# Environment: ANDON_REGISTRY (registry to read, default registry.json next to this script),
# ANDON_ON (pretend today is YYYY-MM-DD), ANDON_CLAUDE (claude binary, default `claude`),
# ANDON_MODEL (default sonnet).
# Log: logs/round.log; a failure leaves logs/LAST_RUN_FAILED for your briefing to show.

set -o pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
A="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$A/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/round.log"
FAIL_FLAG="$LOG_DIR/LAST_RUN_FAILED"
TODAY="${ANDON_ON:-$(date '+%Y-%m-%d')}"
CLAUDE_BIN="${ANDON_CLAUDE:-claude}"
ON_OPT=()
[ -n "$ANDON_ON" ] && ON_OPT=(--on "$ANDON_ON")

DRY=0
[ "$1" = "--dry-run" ] && DRY=1
SOURCE="${ANDON_REGISTRY:-$A/registry.json}"
if [ "$DRY" = 1 ]; then
  SANDBOX="$(mktemp -d)"
  [ -f "$SOURCE" ] && cp "$SOURCE" "$SANDBOX/registry.json"
  export ANDON_REGISTRY="$SANDBOX/registry.json"
  REPORT="$SANDBOX/last-round.md"
else
  export ANDON_REGISTRY="$SOURCE"
  REPORT="$A/last-round.md"
fi

andon() { python3 "$A/andon.py" "${ON_OPT[@]}" "$@"; }

fail() {
  echo "ERROR: $1"
  if [ "$DRY" = 0 ]; then
    printf '%s\nAndon morning round failed: %s\nLog: %s\nRerun: "%s/morning-round.sh"\n' "$(date '+%Y-%m-%d %H:%M')" "$1" "$LOG" "$A" > "$FAIL_FLAG"
    printf '%s\nThe morning round failed (%s). Nothing was checked today.\n' "$TODAY" "$1" > "$REPORT"
  fi
  exit 1
}

{
  echo "=== round $(date '+%Y-%m-%d %H:%M:%S')$([ "$DRY" = 1 ] && echo ' (dry run)') ==="
  cd "$A" || exit 1

  WORK="$(andon todo)"
  CODE=$?
  if [ "$CODE" = 1 ]; then
    echo "nothing to do, no model woken"
    printf '%s\nNothing to do this morning.\n' "$TODAY" > "$REPORT"
    [ "$DRY" = 0 ] && rm -f "$FAIL_FLAG"
    [ "$DRY" = 1 ] && echo "dry run: registry and report in $SANDBOX"
    echo "=== end $(date '+%H:%M:%S') ==="
    exit 0
  elif [ "$CODE" != 0 ]; then
    fail "andon todo crashed (exit $CODE): $WORK"
  fi
  echo "$WORK"

  ANSWER="$("$CLAUDE_BIN" -p "$(cat "$A/morning-round-prompt.md")

## This morning ($TODAY)

$WORK" \
    --model "${ANDON_MODEL:-sonnet}" \
    --max-turns 40 \
    --allowedTools "Read,Grep,Glob,Bash(python3 andon.py:*),Bash(./andon.py:*),Bash(gh pr view:*),Bash(gh pr list:*),Bash(gh run list:*),Bash(gh run view:*),Bash(uv run --with pytest python -m pytest:*),Bash(npm test:*),Bash(deno test:*)" \
    2>>"$LOG")"
  STATUS=$?
  [ "$STATUS" != 0 ] && fail "claude -p returned exit $STATUS"
  # Only the report goes to the briefing: cut anything the model wrote before it.
  ANSWER="$(printf '%s\n' "$ANSWER" | sed -n '/^Done this morning/,$p')"
  echo "$ANSWER" | grep -q "^For you" || fail "report without \"Done this morning\" then \"For you\""

  # The registry must always pass the tool's rules, even after an unattended run.
  andon review >/dev/null || fail "the registry no longer reads after the round"

  printf '%s\n%s\n' "$TODAY" "$ANSWER" > "$REPORT"
  echo "$ANSWER"

  if [ "$DRY" = 0 ]; then
    if git ls-files --error-unmatch "$ANDON_REGISTRY" >/dev/null 2>&1 && ! git diff --quiet -- "$ANDON_REGISTRY"; then
      git add "$ANDON_REGISTRY" && git commit -q -m "Morning round $TODAY" && git push -q 2>&1 | tail -2
    fi
    rm -f "$FAIL_FLAG"
  else
    echo "dry run: registry and report in $SANDBOX"
  fi
  echo "=== end $(date '+%H:%M:%S') ==="
} >> "$LOG" 2>&1
