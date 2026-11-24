# Changelog

## 0.2.1 (2026-11-24)

- **Subagents count.** The hook read the main session's transcript only, while Claude Code writes each subagent's apart, under `<session>/subagents/` (a workflow's agents one level deeper). A project changed only by a subagent was never checked. On my own sessions since 21/10, that was 12 folders in 5 of the 23 sessions that used subagents. The hook now reads them all. Reported by the same reader, from the code alone.
- **Andon: same-day order.** A complaint logged later the same day counted as earlier than one logged before it, so a valid recurrence could turn invalid after the fact, and the registry test failed on an entry nobody had touched. On the same day, the order of arrival (the id) now decides.

## 0.2.0 (2026-11-24)

- **Blocks are counted per request.** The counter used to be per session and never started over, so in a long session, once 3 blocks were used, every later red check let Claude through. It now resets on the first stop after each new message (`stop_hook_active` false). On my own log, 8 of 16 red stops had gone through that way. Reported by a reader on LinkedIn, from the code alone.
- **The log tells a block from a pass.** A block writes `BLOCKED (n of 3 for this request)`, and a red check let through at the limit writes `block limit reached`. Before, both left the same `FAILED` line.
- **Rules:** for a bug, the test that reproduces it comes first, seen failing before the fix (`CLAUDE.md`, the loop). Suggested by a reader.
- **Example map:** a Playwright end-to-end suite as the last `static` command of the web app.
- **FAQ:** loops and their ceilings, `/goal`, pre-commit hooks, why the rules are not a skill.

## 0.1.0 (2026-11-24)

First public release: the harness as it runs on my machine, translated to English.

- **Rules.** `CLAUDE.md`: four hard rules ("done" means seen working, loop until it passes, never make the human test, verification never touches production), the loop on every change, parallel agents, background loops, complaints.
- **Stop hook.** `hooks/verify_on_stop.py` reruns the checks of every project Claude wrote to before it can hand back, and sends it back to work on red (exit 2). Skips states already green, blocks the same red state only once, at most `max_blocks` per session (per request since 0.2.0), never blocks for its own failure. `--dry-run` replays a past session.
- **Verify map.** `config/verify.example.json`: per project, the commands that say it still works, matched by GitHub repo or by folder, with `{changed}` for changed files only.
- **Andon CLI and skill.** `andon/andon.py` keeps a registry of complaints with their cause, countermeasure and dated check, and refuses a recurrence fixed at the same level as before. `andon/SKILL.md` teaches Claude Code the loop. A fictional example registry ships with it.
- **Morning round.** `andon/morning-round.sh` wakes a model only when a check is due or a countermeasure went live.
- **Helpers.** `hooks/syntax_check.py` for script folders with no tests, `hooks/icloud_nosync.sh` to keep `node_modules` out of iCloud.
- **Installer.** `install.sh` installs into `~/.claude` with backups, never overwrites your `CLAUDE.md` or `verify.json`, and ships the guard switched off. `--dry-run` writes nothing.
- **CI.** Tests on Ubuntu and macOS, Python 3.9 and 3.13.
