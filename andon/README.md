# Andon

Every piece of feedback I get on a tool, an agent or a project becomes one entry: what was said, its cause, the countermeasure put in place right away, and a dated check that says whether it held. The only number that matters: does the same cause come back.

On a Toyota line, the andon is the cord anyone pulls when something is wrong. Here the cord is a complaint, and the registry makes sure each one changes the system instead of just the case.

## The ladder

A countermeasure sits on one of five levels, from weakest to strongest:

1. **instruction**: a prompt, a skill, a CLAUDE.md line. A model can ignore it.
2. **example**: a regression test or eval case that fails if the complaint comes back.
3. **guardrail**: the mistake made impossible or blocking in code.
4. **mechanism**: the way the system works changes (where the data comes from, when it speaks, who does what).
5. **standard**: the rule shared by every system changes, because the cause showed up in more than one.

When a cause comes back on the same system, the tool refuses a new countermeasure at the same level or below. Words that did not hold go to code. At code level, staying on the same level has to be defended in writing (`same_level`). `held` needs a proof: silence is not one.

## Commands

```
andon catalogue                     the 10 causes, the ladder, the statuses
andon add '<json>'                  log a complaint (refuses anything incomplete)
andon update A012 '<json>'          move it forward
andon show A012
andon search --system bot --cause noise
andon review                        the short list: checks due, waits, recurrences, chronic causes, held rate
andon brief                         one line for a daily briefing
andon todo                          does the morning round have work? (exit 0 yes, 1 no)
andon live owner/repo#42            merged AND green on the merge commit? (read on GitHub only)
```

Try it on the fictional example registry:

```
ANDON_REGISTRY=registry.example.json python3 andon.py review
```

## Install

```
ln -s "$PWD/andon.py" ~/.local/bin/andon
mkdir -p ~/.claude/skills/andon && cp SKILL.md ~/.claude/skills/andon/SKILL.md
```

The registry is `registry.json` next to `andon.py` (or `$ANDON_REGISTRY`). It is ignored by git in this repo: keep yours in a private repo, it holds what people told you.

In Claude Code, tell it about the feedback ("someone told me that…") or type `/andon <the feedback>`; the skill does the rest and only writes through the tool. If `gh` on your PATH is not the GitHub CLI, point `ANDON_GH` at the right one.

## The morning round

`morning-round.sh` runs from cron or launchd. It only wakes a model (`claude -p`, read-only tools) when `andon todo` finds work, writes its report to `last-round.md`, and never writes to anyone. Try it first with `--dry-run`, which works on a copy of the registry.

## Tests

```
uv run --with pytest python -m pytest -q
```
