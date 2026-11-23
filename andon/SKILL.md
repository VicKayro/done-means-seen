---
name: andon
description: "Andon, the loop that turns every complaint into an improvement of the system. Any feedback the user gets on a tool, an agent or a project (a bot, an assistant, a process, Claude's own sessions) becomes one entry in the registry: its cause, the countermeasure put in place right away, then a dated check that says whether it held. Use as soon as the user reports feedback: \"someone told me\", \"X doesn't like\", \"X finds that\", \"it doesn't work for X\", \"feedback on\", a screenshot of a complaint, and for \"/andon\", \"andon round\", \"where are the complaints\", \"is it coming back\"."
---

# Andon

On a Toyota line, the andon is the cord you pull when something is wrong: the line stops, someone comes, and it only restarts once the cause is dealt with. Here, the cord is a complaint made to the user. My job: none gets lost, each one changes the system and not just the case, and afterwards I check that the cause has not come back. That is the only indicator that says whether a countermeasure worked.

Handling a complaint and moving on to the next one is how you become your agent's assistant. A complaint closed without a cause is a complaint you will live again.

## The tool

`andon` (a link to `andon.py`) keeps the registry `registry.json`. All the counting (recurrences, chronic causes, checks due, held rate) happens in the tool, never in my head. It refuses anything that would leave the registry wrong: read its message, fix, rerun. Never write `registry.json` by hand.

- `andon catalogue`: the 10 causes, the countermeasure ladder, the statuses. Read it before filing.
- `andon systems`, `andon search --system X --cause Y`, `andon show A012`
- `andon add '<json>'` and `andon update A012 '<json>'` (JSON as an argument or on stdin)
- `andon review` (the short list for the round), `andon checks`, `andon brief` (the line for a daily briefing)
- `andon live owner/repo#42`: merged AND green on the merge commit? (read on GitHub, never in production)
- `andon todo`: what the morning round can do by itself

Fields of an entry: `system` (reuse a name from `andon systems`; a subsystem after "/", like `project-bot/weekly-emails`, counts as `project-bot`), `who` (first name or role), `channel`, `verbatim` (their words, not mine), `what_happened` (one sentence: what concretely happened), `cause`, `wrong_assumption`, `stage` (A to E), `earlier`, `countermeasures` (a list of {level, text, where}; with `update`, one at a time under the key `countermeasure`), `status`, `owner` and `waiting_for`, `pr` (a list of "owner/repo#number"), `check` ({date, how, proof}), `elsewhere`, `reply` ({to, text, sent}), `different_defect`, `same_level`, `also` (the same feedback from another person), `source`.

## One complaint

One piece of feedback = one axis. Five axes in one message make five entries; the ones that touch disjoint files run in parallel (subagents in a worktree, each looping on its own verification), and I review before handing back.

1. **Log it right away**, before analysing: `andon add` with who, channel, verbatim, what_happened, system, a provisional cause, status `to_understand`. Nothing gets lost, even if the session stops there. If the tool answers that an entry is still open on the same cause, it is the same problem not fixed yet: `update` that entry with `also`.
2. **Go and see the real case** (the bot's message, the conversation, the screen, the log) before fixing anything. Vague feedback ("they don't like the bot") gets brought down to a concrete case; if I can't find one, I prepare for the user a single question to ask the person, and the entry stays `to_understand`. Reading production to understand needs the user's go in the session.
3. **File and analyse**: the cause (catalogue), the wrong assumption that produced the defect, the stage where it was seen (A the author before sending, B the team, C the person in charge, D the client before complaining, E the complaint) and how it could have been seen earlier.
4. **Look at the history**: `andon search --system X --cause Y`. If the tool said RECURRENCE, the previous countermeasure did not hold and I don't do the same thing again. Words that did not hold (instruction, example) move to code, the tool enforces it. At code level, another countermeasure of the same level is defended in writing (`same_level`). A truly different defect under the same cause is said plainly (`different_defect`). At the second recurrence, a five-whys before touching the code.
5. **Put the countermeasure in place right away**, at the highest level possible (make the mistake impossible rather than add a check):
   - `instruction` alone, only if nothing stronger is possible now. When the project has tests, the complaint also goes in as a regression case (`example`) that fails if it comes back.
   - `guardrail` as soon as the mistake can be made impossible in code: validation before sending, a CI check, a threshold.
   - `mechanism` when the way it works produces the defect: where the data comes from, when it speaks, where it lives, who does what.
   - `standard` when the cause is chronic (see the round): the rule shared by every system.
   The verification loop applies: write, check, run, see the effect, test. Each system's repo and check command are in `~/.claude/verify.json`.
   When the countermeasure depends on someone, I prepare everything that can be prepared (PR opened, decision framed as one question with its options, text ready) and the entry moves to `waiting_owner` with `owner` and `waiting_for`, and `pr` when a PR carries the countermeasure: the morning round sees by itself the day it is merged and live, and dates the check. A repo where a push to main goes to production: the user's go. A product decision: the user.
6. **Look elsewhere**: does the same cause exist in the other agents and tools? ("Too long" on one bot: look at the other bots and digests.) Fix it there too, or note it in `elsewhere`.
7. **Date the check** once the countermeasure is live (deployed and seen, not just merged): `check.date` (one week by default, or the next natural occurrence: the next weekly email, the next meeting) and `check.how`, a verification that needs no guessing (reread the next 10 messages, rerun the test, count the threads with a human reply, ask the person). Status `to_check`.
8. **Close the loop with whoever reported it**: prepare for the user the message, in the user's own voice: what we heard, what changed, and "if you see it again, tell me". That is what makes people want to report the next time, and counting problems raised is good news. Nothing goes out without the user: they copy it, or say go and I send it through the right channel. `reply` = {to, text, sent}.
9. **Keep the trace**: commit the registry with a message like `A0xx <system>: <what changed>` and push it to a private repo.

**Complaints about me.** Criticism of my own work ("you told me done and it didn't work", "that's the third time you used that word") is a complaint on the system `harness`, same loop. A feedback memory is an `instruction`-level countermeasure: if the criticism comes back, the tool forces a hook, a test or a command in `verify.json`.

## What the user gets after a complaint

Three to six lines, in sentences: the real case I found, the cause, what changed and where (with the proof that I saw it work), what is waiting on whom, the date of the check, and the message for the person, ready to copy. Whatever is still unverified, said plainly. No table, no jargon.

## The round

The round runs on its own every morning (`morning-round.sh`, instructions in `morning-round-prompt.md`). It only wakes a model when `andon todo` finds work, does what can be done without reading production and without writing to anyone, and its report (`last-round.md`) lands in the user's daily briefing. `/andon round` in a session picks up what it left for the user (checks that read production, with their go; recurrences to fix; messages to send), in this order:

1. `andon review`.
2. **Each check due**: do the verification written in `check.how`, preferably through a subagent that did not put the countermeasure in place (whoever produces does not judge their own work). A verification that reads production needs the user's go: one line to ask for it.
   - Nothing came back, and I saw it: `held` with `check.proof` (what I saw, with a number or a link).
   - It came back: `andon add` a new entry (the tool moves the old one to `recurred`), then step 5 at the level above.
   - Impossible to know (no occurrence since, unreadable source): silence is not proof. Push `check.date` to the next occurrence, or prepare the question for the person who reported it.
3. **The waits**: for each `waiting_owner`, check whether it is unblocked (PR merged and deployed, decision made). Unblocked: date the check. Blocked for more than 7 days: one line for the user (who, what, since when) with the nudge ready.
4. **Chronic causes** (the same cause on several systems): the organisation is producing the defect, not one agent. Propose the `standard` countermeasure (a doctrine, a shared bot template, a rule in `~/.claude/CLAUDE.md`, a shared guardrail). If a standard already exists, find out why it is not applied everywhere and make it impossible to get around.
5. **Hand back to the user** five lines at most: what held, what came back and what I am doing about it, what is waiting on whom, and the held rate over 90 days.

## Never

- "We'll be careful" as a countermeasure, or a countermeasure that does not say what changed.
- Cutting a tool's scope because people complain about it: a cut is only proposed as a replacement (the system finds by itself what it was asking for), the ambition stays.
- Fixing the substance when the criticism is about form: a remark on form gets fixed in the rendering.
- Concluding `held` on silence.
- Writing a client's name in the registry (it goes to GitHub, even private): "an industrial client".
- Writing to the person who reported it without the user.
- Acting on a complaint without logging it first.
