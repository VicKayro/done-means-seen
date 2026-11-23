# Changelog

## 0.1.0 (2026-11-24)

First public release: the harness as it runs on my machine, translated to English.

- **Rules.** `CLAUDE.md`: four hard rules ("done" means seen working, loop until it passes, never make the human test, verification never touches production), the loop on every change, parallel agents, background loops, complaints.
- **Stop hook.** `hooks/verify_on_stop.py` reruns the checks of every project Claude wrote to before it can hand back, and sends it back to work on red (exit 2). Skips states already green, blocks the same red state only once, at most `max_blocks` per session, never blocks for its own failure. `--dry-run` replays a past session.
- **Verify map.** `config/verify.example.json`: per project, the commands that say it still works, matched by GitHub repo or by folder, with `{changed}` for changed files only.
- **Andon CLI and skill.** `andon/andon.py` keeps a registry of complaints with their cause, countermeasure and dated check, and refuses a recurrence fixed at the same level as before. `andon/SKILL.md` teaches Claude Code the loop. A fictional example registry ships with it.
- **Morning round.** `andon/morning-round.sh` wakes a model only when a check is due or a countermeasure went live.
- **Helpers.** `hooks/syntax_check.py` for script folders with no tests, `hooks/icloud_nosync.sh` to keep `node_modules` out of iCloud.
- **Installer.** `install.sh` installs into `~/.claude` with backups, never overwrites your `CLAUDE.md` or `verify.json`, and ships the guard switched off. `--dry-run` writes nothing.
- **CI.** Tests on Ubuntu and macOS, Python 3.9 and 3.13.
