# done-means-seen

**Claude doesn't get to say "done" until it has seen the thing work.**

I run an AI consulting company in France and I'm not a developer. Most of our internal tools, our agents and my side projects are built with Claude Code, and for months my real job was being the tester of my own agents: "done!", I open it, it doesn't work, I paste the error back, and again. On 21/10/2026, after a talk called "Stop babysitting your agents", I wrote one rule, and then the few pieces of code that make it hard to skip. This is what runs on my Mac today, across 28 projects, translated from French and stripped of what only makes sense inside my company.

## What's inside

| Piece | What it does |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | The global instructions: four hard rules, the loop on every change, parallel agents, background loops, complaints. Goes in `~/.claude/CLAUDE.md`. |
| [`hooks/verify_on_stop.py`](hooks/verify_on_stop.py) | A Stop hook. Before Claude hands back, it reruns the checks of every project Claude wrote to in the session. Red means Claude gets the error and keeps working. |
| [`config/verify.example.json`](config/verify.example.json) | The map the hook reads: per project, the commands that say "it still builds". |
| [`andon/`](andon/) | A registry where every complaint about an agent becomes a cause, a countermeasure and a dated check, and where a cause that comes back forces the next fix one level up. |
| [`hooks/syntax_check.py`](hooks/syntax_check.py), [`hooks/icloud_nosync.sh`](hooks/icloud_nosync.sh) | Small helpers: a syntax check for script folders with no tests, and a way to keep `node_modules` out of iCloud when your projects live on the Desktop. |

## The four rules

1. **"Done" means I have seen it work.** Run it for real and see the effect (a screen, a log line, a row, a file). Re-reading the code does not count.
2. **Loop on your own until it passes.** Stop only on a real blocker (a missing secret, production access, a decision that belongs to the human) and name it in one sentence.
3. **Never make the human test in your place.** Hand back the proof, and say in plain words what is still unverified.
4. **Verification never touches production.** Local, preview, branch or dry run.

Rules in a prompt get ignored on a bad day, which is why the rest of this repo exists.

## The Stop hook

Claude Code runs [Stop hooks](https://docs.claude.com/en/docs/claude-code/hooks) when the model is about to end its turn. `verify_on_stop.py`:

- reads the session transcript and finds the files Claude wrote to, through the edit tools and through shell commands that write (`sed -i`, heredocs, redirections, `git commit`, `mv`, `cp`),
- maps them to projects in `~/.claude/verify.json`, by GitHub repo or by folder,
- runs each project's `static` commands (`{changed}` expands to the changed files only, so a lint that takes 7 minutes on the whole repo takes 3 seconds),
- on red, exits with code 2: Claude reads the error and keeps working.

What Claude sees when it tries to stop on a red check:

```
ERROR: the check for demo fails after your changes.
  command: grep -qx ok status.txt || { echo "status.txt says: $(cat status.txt)"; exit 1; }
--- end of output ---
status.txt says: broken
---
WHY: "done" means the checks are green (CLAUDE.md, rule 1).
FIX: read the output, fix the cause, and hand back: the check reruns by itself.
If the failure is not caused by your changes (it was there before, or comes from another session), say so in one line in your answer and hand back without changing anything: the guard will let you through.
(block 1 of 3 for this session)
```

It is built to never become the thing you babysit:

- a project already verified green in the same state is skipped,
- the same red state blocks only once: if Claude stops again without changing anything, it decided the failure isn't its doing, and it has to say so,
- at most 3 blocks per session,
- it never blocks for its own failure (missing tool, timeout, unreadable map): it logs and lets the turn end.

Start with `"guard_enabled": false` and replay past sessions without blocking anything:

```bash
python3 ~/.claude/hooks/verify_on_stop.py --dry-run ~/.claude/projects/<project>/<session>.jsonl
```

## Andon

On a Toyota line, the andon is the cord anyone pulls when something is wrong: the line stops, someone comes, and it restarts once the cause is dealt with. Here the cord is a complaint ("the project bot posts too much", "you told me it was done and it wasn't"). Each one becomes a line with its cause (from a catalogue of 10, like *noise*, *wrong*, *silence*, *trust*), the countermeasure, and a dated check that says whether it held.

Countermeasures sit on a ladder, weakest first:

1. **instruction**: change a prompt, a skill, a CLAUDE.md. A model can ignore it.
2. **example**: the case enters the test suite and fails if it comes back.
3. **guardrail**: the mistake becomes impossible or blocking in code.
4. **mechanism**: change how the system works (where the data comes from, when it speaks, who does what).
5. **standard**: change the rule shared by every system, when the cause shows up in several.

The CLI does all the counting and refuses what would leave the registry lying: a recurrence fixed at the same level as last time (words that did not hold have to become code), a countermeasure marked as held without proof, silence taken as proof.

On the fictional example registry, the project bot got chatty again after a mechanism-level fix, and someone tries to answer with a prompt edit:

```
$ andon add '{"system": "project-bot", "cause": "noise", "verbatim": "It is chatty again.",
  "countermeasures": [{"level": "instruction", "text": "Prompt says: only post when something changed."}], ...}'
REFUSED: Recurrence of A002: the last countermeasure went up to level "mechanism" and the cause came back.
Go above it (standard), or say plainly that it is a different defect (different_defect),
or write why this level is enough this time (same_level).
```

`andon review` gives the short list for the morning: checks due, what is waiting on whom, recurrences, causes that travel from one system to another, and the held rate. Try it: `ANDON_REGISTRY=andon/registry.example.json python3 andon/andon.py review`.

## Receipts

From my own logs, first 33 days of the hook (21/10 to 23/11/2026) and four months of the registry:

- **171 sessions** ended through the hook, **386 checks** came back green at the end of a turn, and **16 times** the checks were red when Claude was about to hand back. It blocked 8 times; the other reds came in long sessions that had already used their 3 blocks.
- **198 times** it could not judge (a worktree without dependencies, a timeout) and let the turn end. That's the deal.
- **71 complaints** logged in Andon (the ones before 04/11 backfilled from notes). None of the 66 countermeasures stops at a prompt edit: 9 are guardrails, 46 change the mechanism, 11 became standards. 5 are still being understood. **8 came back**, and each time the tool forced the next fix one level up. 7 of the 71 are about Claude Code itself.
- The honest part: today the registry says *0 held, 10 came back*. That's mostly calendar: the 30 countermeasures waiting for their check haven't been judged yet, while the ones that failed announced themselves. The first checks come due this week.

## Install

```bash
git clone https://github.com/VicKayro/done-means-seen && cd done-means-seen
mkdir -p ~/.claude/hooks ~/.claude/skills/andon ~/.local/bin

# the rules: copy if you have no ~/.claude/CLAUDE.md, otherwise merge by hand
cp -n CLAUDE.md ~/.claude/CLAUDE.md

# the hook and its map (then edit verify.json: your projects, your commands)
cp hooks/verify_on_stop.py hooks/syntax_check.py hooks/icloud_nosync.sh ~/.claude/hooks/
cp -n config/verify.example.json ~/.claude/verify.json
# then add the "Stop" block of config/settings.example.json to ~/.claude/settings.json

# andon
cp andon/SKILL.md ~/.claude/skills/andon/SKILL.md
ln -s "$PWD/andon/andon.py" ~/.local/bin/andon
```

Python 3.9+, no dependencies. If `gh` on your PATH is not the GitHub CLI, point `ANDON_GH` at it. Tests: `uv run --with pytest python -m pytest -q tests/ andon/tests/` (50 tests).

## Limits

- Detecting writes in shell commands is a regex heuristic. It errs on the side of checking: a read-only script fed through a heredoc from inside a project counts as a write to that project, so you may get blocked on a failure someone else left there. That's what the "say it's not yours and hand back" escape is for.
- The hook runs static checks (typecheck, lint, tests). Clicking through a UI and taking a screenshot is still Claude following `CLAUDE.md`; a hook can't see a screen.
- A long session can use its 3 blocks and end on red. The log says so.
- Tested on macOS. Linux paths are handled, less tested.
- The registry is one JSON file in a git repo, for one person.

## See also

- [Leash](https://github.com/VicKayro/leash): see what your agents did last night (costs, loops, dead crons), one `npx` command.

MIT. Built with Claude Code, obviously.
