#!/usr/bin/env python3
"""Andon: the registry of complaints and their countermeasures.

Every piece of feedback on a tool, an agent or a project becomes one entry: what was said,
its cause (catalogue.json), the countermeasure put in place, and the check that will say
whether it held. All the counting happens here, in code, never in a model's head.

    andon catalogue              causes and the countermeasure ladder
    andon add < entry.json       new complaint (refuses anything incomplete)
    andon update A012 < patch.json
    andon show A012
    andon search --system bot --cause noise
    andon checks                 countermeasures whose check is due
    andon review                 the short list for the round
    andon brief                  one line for a daily briefing (empty when nothing is due)
    andon todo                   does the morning round have work? (exit 0 yes, 1 no)
    andon systems                systems already named
    andon live owner/repo#42     is the countermeasure merged AND green on GitHub?

Registry: registry.json next to this file, or $ANDON_REGISTRY.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOGUE = json.loads((HERE / "catalogue.json").read_text(encoding="utf-8"))
CAUSES = {c["code"]: c for c in CATALOGUE["causes"]}
LEVELS = {n["code"]: n for n in CATALOGUE["levels"]}

STATUSES = {
    "to_understand": "too vague to act on: find the concrete case or ask the question",
    "in_progress": "countermeasure being put in place",
    "waiting_owner": "countermeasure ready, waiting on someone (merge, decision, go)",
    "to_check": "countermeasure in place, check dated",
    "held": "checked, the cause did not come back (with proof)",
    "recurred": "the same cause came back on the same system",
    "legacy": "countermeasure put in place before Andon, never checked",
    "dropped": "the owner decided not to act (reason written)",
}
OPEN = {"to_understand", "in_progress", "waiting_owner"}
STAGES = {"A", "B", "C", "D", "E"}

RECURRENCE_WINDOW = 180  # days: the same cause on the same system within this window is a recurrence
CHRONIC_WINDOW = 90  # days
CHRONIC_THRESHOLD = 3  # complaints with the same cause, on at least 2 systems
LONG_WAIT = 7  # days waiting on an owner before it shows up in the brief
LONG_VAGUE = 3  # days in "to_understand" before it shows up in the brief


PR_RE = re.compile(r"^[\w.-]+/[\w.-]+#\d+$")


class Refusal(Exception):
    """A write that would leave the registry wrong. The message says what to fix."""


# ---------------------------------------------------------------- registry

def registry_path() -> Path:
    return Path(os.environ.get("ANDON_REGISTRY") or HERE / "registry.json")


def load() -> list[dict]:
    p = registry_path()
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8") or "[]")


def save(entries: list[dict]) -> None:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".registry-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, p)


def day(text: str | None) -> dt.date:
    return dt.date.fromisoformat(text) if text else dt.date.today()


def short(d: str | dt.date | None) -> str:
    if not d:
        return "?"
    d = dt.date.fromisoformat(d) if isinstance(d, str) else d
    return f"{d.strftime('%b')} {d.day}"


def root(system: str) -> str:
    return system.split("/")[0].strip().lower()


def rank(entry: dict) -> int:
    return max((LEVELS[c["level"]]["rank"] for c in entry.get("countermeasures", []) if c.get("level") in LEVELS), default=0)


def next_id(entries: list[dict]) -> str:
    n = max((int(e["id"][1:]) for e in entries if e.get("id", "").startswith("A") and e["id"][1:].isdigit()), default=0)
    return f"A{n + 1:03d}"


def find(entries: list[dict], id_: str) -> dict:
    for e in entries:
        if e["id"] == id_:
            return e
    raise Refusal(f"No complaint {id_} in the registry.")


def earlier_same_cause(entries: list[dict], entry: dict) -> list[dict]:
    """Older complaints with the same cause on the same system, within the recurrence window."""
    d = day(entry["date"])
    out = []
    for e in entries:
        if e is entry or e.get("id") == entry.get("id") or e.get("status") == "dropped":
            continue
        if root(e["system"]) != root(entry["system"]) or e["cause"] != entry["cause"]:
            continue
        de = day(e["date"])
        if de <= d and (d - de).days <= RECURRENCE_WINDOW:
            out.append(e)
    return sorted(out, key=lambda e: (e["date"], e["id"]))


def log(entry: dict, text: str, on: dt.date) -> None:
    entry.setdefault("log", []).append({"date": on.isoformat(), "text": text})


# ---------------------------------------------------------------- validation

def validate(entry: dict, entries: list[dict]) -> None:
    missing = [k for k in ("system", "who", "verbatim", "what_happened", "cause", "status") if not str(entry.get(k) or "").strip()]
    if missing:
        raise Refusal("Missing fields: " + ", ".join(missing) + ".")
    if entry["cause"] not in CAUSES:
        raise Refusal(f"Unknown cause \"{entry['cause']}\". Causes: " + ", ".join(CAUSES) + ".")
    if entry["status"] not in STATUSES:
        raise Refusal(f"Unknown status \"{entry['status']}\". Statuses: " + ", ".join(STATUSES) + ".")
    if entry.get("stage") and entry["stage"] not in STAGES:
        raise Refusal("The detection stage goes from A (the author, before sending) to E (a complaint).")
    for c in entry.get("countermeasures", []):
        if c.get("level") not in LEVELS:
            raise Refusal(f"Unknown countermeasure level \"{c.get('level')}\". Levels: " + ", ".join(LEVELS) + ".")
        if not str(c.get("text") or "").strip():
            raise Refusal("A countermeasure without text does not say what changed.")
    for ref in entry.get("pr", []):
        if not PR_RE.match(str(ref)):
            raise Refusal(f"PR \"{ref}\" is badly written: owner/repo#number, for example acme/tools#42.")
    s = entry["status"]
    check = entry.get("check") or {}
    if s in ("to_check", "held", "recurred", "legacy") and not entry.get("countermeasures"):
        raise Refusal(f"Status \"{s}\" without a countermeasure: write what changed (or will change) first.")
    if s == "to_check" and not (check.get("date") and check.get("how")):
        raise Refusal("\"to_check\" needs check.date (when) and check.how (how we will know it held).")
    if s == "held" and not check.get("proof"):
        raise Refusal("\"held\" needs check.proof: what was seen. Silence is not proof.")
    if s == "waiting_owner" and not (entry.get("owner") and entry.get("waiting_for")):
        raise Refusal("\"waiting_owner\" needs owner (who) and waiting_for (what, in one sentence).")
    if s == "dropped" and not entry.get("reason"):
        raise Refusal("\"dropped\" needs the owner's reason.")
    # Recurrence: the countermeasure must go one level up, unless a different defect is stated plainly.
    if entry.get("recurs_from") and entry.get("countermeasures") and not entry.get("different_defect"):
        before = earlier_same_cause(entries, entry)
        ceiling = max((rank(e) for e in before), default=0)
        r = rank(entry)
        # Words (instruction, example) that did not hold are not repeated: we move to code.
        # At code level, another countermeasure of the same level can be defended, in writing (same_level).
        same_level_ok = ceiling >= LEVELS["guardrail"]["rank"] and r >= ceiling and entry.get("same_level")
        if ceiling and r <= ceiling and not same_level_ok:
            names = {n["rank"]: n["code"] for n in LEVELS.values()}
            raise Refusal(
                f"Recurrence of {entry['recurs_from']}: the last countermeasure went up to level "
                f"\"{names[ceiling]}\" and the cause came back. Go above it "
                f"({', '.join(names[x] for x in sorted(names) if x > ceiling) or 'no level above: run a five-whys first'}), "
                "or say plainly that it is a different defect (different_defect)"
                + (", or write why this level is enough this time (same_level)." if ceiling >= LEVELS["guardrail"]["rank"] else ".")
            )


# ---------------------------------------------------------------- writes

def add(data: dict, on: dt.date | None = None) -> tuple[dict, list[str]]:
    on = on or dt.date.today()
    entries = load()
    entry = dict(data)
    entry.pop("id", None)
    entry.setdefault("date", on.isoformat())
    entry["system"] = str(entry.get("system") or "").strip().lower()
    entry.setdefault("countermeasures", [])
    for c in entry["countermeasures"]:
        c.setdefault("date", on.isoformat())
    entry.setdefault("status", "to_understand" if not entry["countermeasures"] else "in_progress")
    if entry["status"] == "waiting_owner":
        entry.setdefault("since", entry["date"])
    entry["id"] = next_id(entries)
    notes: list[str] = []

    before = earlier_same_cause(entries, entry) if entry.get("cause") in CAUSES and entry["system"] else []
    still_open = [e for e in before if e["status"] in OPEN]
    if still_open and not entry.get("different_defect"):
        o = still_open[-1]
        raise Refusal(
            f"{o['id']} is still open on the same cause ({o['status']}): it is the same problem, not fixed yet. "
            f"Attach this feedback to {o['id']} with andon update {o['id']} and "
            '{"also": {"who": "...", "verbatim": "..."}}. '
            'If it is a different defect, say so: "different_defect": "how it differs".'
        )
    if before and not entry.get("different_defect"):
        previous = before[-1]
        entry["recurs_from"] = previous["id"]
        notes.append(
            f"RECURRENCE: {entry['cause']} on {root(entry['system'])} already reported "
            + ", ".join(f"{e['id']} on {short(e['date'])} ({e['status']}, max level {rank(e)})" for e in before)
            + ". The next countermeasure must go one level up."
        )
    elif before:
        notes.append(f"Same cause already seen on this system ({', '.join(e['id'] for e in before)}), declared a different defect: {entry['different_defect']}")

    validate(entry, entries + [entry])
    log(entry, "complaint logged" + (f", recurrence of {entry['recurs_from']}" if entry.get("recurs_from") else ""), on)

    # The cause came back: the previous countermeasures did not hold.
    if entry.get("recurs_from"):
        for e in before:
            if e["status"] in ("to_check", "held", "legacy"):
                old = e["status"]
                e["status"] = "recurred"
                e["recurred_by"] = entry["id"]
                e["recurred_on"] = entry["date"]
                log(e, f"{old} -> recurred: the cause came back ({entry['id']})", on)
                notes.append(f"{e['id']} moves to \"recurred\" (was {old}).")

    entries.append(entry)
    save(entries)
    return entry, notes


def update(id_: str, patch: dict, on: dt.date | None = None) -> tuple[dict, list[str]]:
    on = on or dt.date.today()
    entries = load()
    entry = find(entries, id_)
    patch = dict(patch)
    notes: list[str] = []
    old = entry["status"]
    new_cm = patch.pop("countermeasure", None)
    log_text = patch.pop("log", None)
    also = patch.pop("also", None)
    for forbidden in ("id", "recurs_from", "recurred_by"):
        patch.pop(forbidden, None)
    if "check" in patch and isinstance(patch["check"], dict):
        entry["check"] = {**(entry.get("check") or {}), **patch.pop("check")}
    entry.update(patch)
    if new_cm:
        new_cm = dict(new_cm)
        new_cm.setdefault("date", on.isoformat())
        entry.setdefault("countermeasures", []).append(new_cm)
        log(entry, f"countermeasure {new_cm.get('level')}: {new_cm.get('text')}", on)
    if also:
        also = dict(also)
        also.setdefault("date", on.isoformat())
        entry.setdefault("also", []).append(also)
        log(entry, f"same feedback from {also.get('who', '?')}", on)
        notes.append(f"{len(entry['also']) + 1} people have reported this problem.")
    if entry["status"] == "waiting_owner" and old != "waiting_owner":
        entry["since"] = on.isoformat()
    if entry["status"] == "held" and old != "held":
        entry.setdefault("check", {}).setdefault("done_on", on.isoformat())
    validate(entry, entries)
    if entry["status"] != old:
        log(entry, f"{old} -> {entry['status']}", on)
    if log_text:
        log(entry, str(log_text), on)
    save(entries)
    return entry, notes


# ---------------------------------------------------------------- reads

def checks_due(entries: list[dict], on: dt.date) -> list[dict]:
    return sorted(
        (e for e in entries if e["status"] == "to_check" and day((e.get("check") or {}).get("date")) <= on),
        key=lambda e: e["check"]["date"],
    )


def chronic(entries: list[dict], on: dt.date) -> list[dict]:
    by_cause: dict[str, list[dict]] = {}
    for e in entries:
        if e["status"] == "dropped":
            continue
        if 0 <= (on - day(e["date"])).days <= CHRONIC_WINDOW:
            by_cause.setdefault(e["cause"], []).append(e)
    out = []
    for cause, es in by_cause.items():
        systems = sorted({root(e["system"]) for e in es})
        if len(es) >= CHRONIC_THRESHOLD and len(systems) >= 2:
            standard = any(rank(e) >= LEVELS["standard"]["rank"] for e in es)
            out.append({"cause": cause, "times": len(es), "systems": systems, "standard_set": standard,
                        "ids": [e["id"] for e in sorted(es, key=lambda e: e["date"])]})
    return sorted(out, key=lambda c: -c["times"])


def recurrences(entries: list[dict], on: dt.date) -> list[dict]:
    return sorted(
        (e for e in entries if e.get("recurs_from") and (on - day(e["date"])).days <= RECURRENCE_WINDOW),
        key=lambda e: e["date"],
    )


def held_90d(entries: list[dict], on: dt.date) -> dict:
    """The indicator: of the countermeasures judged in the last 90 days, how many held."""
    held = recurred = 0
    for e in entries:
        check = e.get("check") or {}
        if e["status"] == "held" and (on - day(check.get("done_on") or e["date"])).days <= CHRONIC_WINDOW:
            held += 1
        elif e["status"] == "recurred" and (on - day(e.get("recurred_on") or e["date"])).days <= CHRONIC_WINDOW:
            recurred += 1
    return {"held": held, "recurred": recurred}


def waiting(entries: list[dict], on: dt.date) -> list[dict]:
    return sorted((e for e in entries if e["status"] == "waiting_owner"), key=lambda e: e.get("since") or e["date"])


def review_text(entries: list[dict], on: dt.date) -> str:
    out = [f"Andon on {on.isoformat()}"]

    def block(title: str, items: list[str]) -> None:
        if items:
            out.append("")
            out.append(f"{title} ({len(items)})")
            out.extend("  " + i for i in items)

    due = checks_due(entries, on)
    block("To check", [
        f"{e['id']} {e['system']}, {e['cause']}: {e['what_happened']} Check due on {short(e['check']['date'])}: {e['check']['how']}"
        for e in due])
    coming = sorted((e for e in entries if e["status"] == "to_check" and e not in due),
                    key=lambda e: e["check"]["date"])
    if coming:
        out.append("")
        out.append(f"In place, check coming ({len(coming)}): "
                   + ", ".join(f"{e['id']} on {short(e['check']['date'])}" for e in coming))
    block("Waiting on someone", [
        f"{e['id']} {e['system']}, {e['cause']}: {e['owner']} for {(on - day(e.get('since') or e['date'])).days} d, {e['waiting_for']}"
        for e in waiting(entries, on)])
    block("To understand", [
        f"{e['id']} {e['system']} ({e['who']}, {short(e['date'])}): {e['what_happened']}"
        for e in entries if e["status"] == "to_understand"])
    block("In progress", [f"{e['id']} {e['system']}, {e['cause']}: {e['what_happened']}" for e in entries if e["status"] == "in_progress"])
    block(f"Recurrences over {RECURRENCE_WINDOW} days", [
        f"{e['system']}, {e['cause']}: {e['recurs_from']} then {e['id']} on {short(e['date'])}" for e in recurrences(entries, on)])
    block(f"Chronic causes over {CHRONIC_WINDOW} days", [
        f"{c['cause']}: {c['times']} times, on {', '.join(c['systems'])} ({', '.join(c['ids'])}). "
        + ("A standard was set, check that it is applied everywhere." if c["standard_set"]
           else "No common standard set: the cause travels from one system to the next.")
        for c in chronic(entries, on)])
    t = held_90d(entries, on)
    total = t["held"] + t["recurred"]
    out.append("")
    if total:
        out.append(f"Countermeasures judged over {CHRONIC_WINDOW} days: {t['held']} held, "
                   f"{t['recurred']} recurred ({round(100 * t['held'] / total)} % held).")
    else:
        out.append(f"Countermeasures judged over {CHRONIC_WINDOW} days: none yet.")
    return "\n".join(out)


def brief_text(entries: list[dict], on: dt.date) -> str:
    def plural(n: int, word: str) -> str:
        return f"{n} {word}{'s' if n > 1 else ''}"

    parts = []
    due = checks_due(entries, on)
    if due:
        parts.append(plural(len(due), "countermeasure") + " to check")
    for e in waiting(entries, on):
        days = (on - day(e.get("since") or e["date"])).days
        if days > LONG_WAIT:
            parts.append(f"{e['id']} waiting on {e['owner']} for {days} d")
    vague = [e for e in entries if e["status"] == "to_understand" and (on - day(e["date"])).days > LONG_VAGUE]
    if vague:
        parts.append(plural(len(vague), "complaint") + " not understood yet")
    recent = [e for e in recurrences(entries, on) if (on - day(e["date"])).days <= 7]
    if recent:
        parts.append(plural(len(recent), "recurrence") + " this week")
    if not parts:
        return ""
    return "Andon: " + ", ".join(parts) + "."


def _gh() -> str | None:
    return os.environ.get("ANDON_GH") or shutil.which("gh")


def pr_state(ref: str) -> str | None:
    """MERGED, OPEN, CLOSED, or None if GitHub does not answer (nothing is concluded from silence)."""
    gh = _gh()
    if not gh:
        return None
    repo, num = ref.split("#")
    try:
        r = subprocess.run([gh, "pr", "view", num, "-R", repo, "--json", "state", "-q", ".state"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def _gh_json(args: list[str]):
    gh = _gh()
    if not gh:
        return None
    try:
        r = subprocess.run([gh, *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


FAILED = {"failure", "error", "cancelled", "timed_out", "action_required", "startup_failure", "stale"}
IGNORED = {"neutral", "skipped"}


def live(ref: str, gh=_gh_json) -> tuple[str, str]:
    """Is a merged countermeasure actually in service? Read on GitHub only, never in production.

    Live = the PR is merged AND every commit status and every check run on the merge commit is
    green (deployments usually report there: Vercel, Netlify, CI). Nothing readable = unknown.
    Returns ("live" | "not_yet" | "unknown", the detail in one sentence).
    """
    repo, num = ref.split("#")
    pr = gh(["pr", "view", num, "-R", repo, "--json", "state,mergeCommit"])
    if not pr:
        return "unknown", f"{ref}: GitHub does not answer"
    if pr.get("state") != "MERGED":
        return "not_yet", f"{ref}: not merged ({str(pr.get('state', '?')).lower()})"
    sha = (pr.get("mergeCommit") or {}).get("oid")
    if not sha:
        return "unknown", f"{ref}: merge commit unreadable"
    status = gh(["api", f"repos/{repo}/commits/{sha}/status"])
    runs = gh(["api", f"repos/{repo}/commits/{sha}/check-runs"])
    if status is None and runs is None:
        return "unknown", f"{ref}: statuses of the merge commit unreadable"
    results = [(s.get("context", "?"), s.get("state")) for s in (status or {}).get("statuses", [])]
    for c in (runs or {}).get("check_runs", []):
        state = c.get("conclusion") if c.get("status") == "completed" else (c.get("status") or "pending")
        results.append((c.get("name", "?"), state))
    results = [(name, state) for name, state in results if state not in IGNORED]
    if not results:
        return "unknown", f"{ref}: merged, but no status or check run on the merge commit"
    failed = [name for name, state in results if state in FAILED]
    pending = [name for name, state in results if state != "success" and state not in FAILED]
    if failed:
        return "not_yet", f"{ref}: failed on the merge commit ({', '.join(failed)})"
    if pending:
        return "not_yet", f"{ref}: not green yet on the merge commit ({', '.join(pending)})"
    return "live", f"{ref}: {len(results)} status{'es' if len(results) > 1 else ''} and checks green on the merge commit"


def todo(entries: list[dict], on: dt.date, state=pr_state, deployment=live) -> list[str]:
    """What the morning round can do by itself. Empty = no need to wake a model."""
    out = [f"{e['id']}: check due ({e['check']['how']})" for e in checks_due(entries, on)]
    for e in waiting(entries, on):
        refs = e.get("pr") or []
        if refs:
            states = [state(r) for r in refs]
            if all(s == "MERGED" for s in states):
                verdicts = [deployment(r) for r in refs]
                if all(v == "live" for v, _ in verdicts):
                    out.append(f"{e['id']}: countermeasure live ({'; '.join(d for _, d in verdicts)}), date the check and prepare the message")
                elif not any(v == "not_yet" for v, _ in verdicts):
                    out.append(f"{e['id']}: merged but going live cannot be established ({'; '.join(d for _, d in verdicts)}), tell the user")
            elif any(s == "CLOSED" for s in states):
                out.append(f"{e['id']}: a PR was closed without merge ({', '.join(r for r, s in zip(refs, states) if s == 'CLOSED')}), find what replaces it")
    if on.weekday() == 0:
        found = chronic(entries, on)
        if found:
            out.append("monday: review of chronic causes (" + ", ".join(c["cause"] for c in found) + ")")
    return out


# ---------------------------------------------------------------- command line

def read_json_input(arg: str | None) -> dict:
    raw = arg if arg else sys.stdin.read()
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as e:
        raise Refusal(f"Unreadable JSON: {e}")
    if not isinstance(d, dict):
        raise Refusal("Expected a JSON object.")
    return d


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="andon", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--on", help="today's date (YYYY-MM-DD), for dry runs and tests")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("catalogue")
    a = sub.add_parser("add"); a.add_argument("json", nargs="?")
    u = sub.add_parser("update"); u.add_argument("id"); u.add_argument("json", nargs="?")
    s = sub.add_parser("show"); s.add_argument("id")
    f = sub.add_parser("search"); f.add_argument("--system"); f.add_argument("--cause")
    sub.add_parser("checks"); sub.add_parser("review"); sub.add_parser("brief"); sub.add_parser("systems")
    sub.add_parser("todo")
    lv = sub.add_parser("live"); lv.add_argument("pr", help="owner/repo#number")
    args = p.parse_args(argv)
    on = day(args.on)

    try:
        if args.cmd == "catalogue":
            print("Causes")
            for c in CATALOGUE["causes"]:
                print(f"  {c['code']:<12} {c['when']}")
            print("\nCountermeasures, from weakest to strongest")
            for n in CATALOGUE["levels"]:
                print(f"  {n['rank']} {n['code']:<12} {n['what']}")
            print("\nStatuses")
            for k, t in STATUSES.items():
                print(f"  {k:<14} {t}")
        elif args.cmd == "add":
            entry, notes = add(read_json_input(args.json), on)
            print(f"{entry['id']} logged ({entry['system']}, {entry['cause']}, {entry['status']}).")
            for n in notes:
                print(n)
        elif args.cmd == "update":
            entry, notes = update(args.id, read_json_input(args.json), on)
            print(f"{entry['id']}: {entry['status']}.")
            for n in notes:
                print(n)
        elif args.cmd == "show":
            print(json.dumps(find(load(), args.id), ensure_ascii=False, indent=2))
        elif args.cmd == "search":
            es = [e for e in load()
                  if (not args.system or root(e["system"]) == root(args.system))
                  and (not args.cause or e["cause"] == args.cause)]
            for e in sorted(es, key=lambda e: e["date"]):
                print(f"{e['id']} {short(e['date'])} {e['system']}, {e['cause']}, {e['status']}, max level {rank(e)}: {e['what_happened']}")
            if not es:
                print("Nothing.")
        elif args.cmd == "checks":
            due = checks_due(load(), on)
            for e in due:
                print(f"{e['id']} {e['system']}: {e['check']['how']} (due on {short(e['check']['date'])})")
            if not due:
                print("No check due.")
        elif args.cmd == "review":
            print(review_text(load(), on))
        elif args.cmd == "brief":
            r = brief_text(load(), on)
            if r:
                print(r)
        elif args.cmd == "todo":
            work = todo(load(), on)
            for w in work:
                print(w)
            if not work:
                print("Nothing to do this morning.")
                return 1
        elif args.cmd == "live":
            if not PR_RE.match(args.pr):
                raise Refusal("Expected a PR as owner/repo#number.")
            verdict, detail = live(args.pr)
            print(f"{verdict}: {detail}")
        elif args.cmd == "systems":
            counts: dict[str, int] = {}
            for e in load():
                counts[e["system"]] = counts.get(e["system"], 0) + 1
            for name, n in sorted(counts.items()):
                print(f"{name} ({n})")
    except Refusal as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
