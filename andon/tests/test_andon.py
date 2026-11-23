import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import andon  # noqa: E402

D = dt.date(2026, 11, 4)  # a Wednesday


@pytest.fixture(autouse=True)
def empty_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("ANDON_REGISTRY", str(tmp_path / "registry.json"))


def base(**kw):
    d = {"system": "project-bot", "who": "a project manager", "verbatim": "The bot writes too much",
         "what_happened": "40-line threads.", "cause": "noise"}
    d.update(kw)
    return d


def cm(level, text="changed"):
    return {"level": level, "text": text}


def checked(**kw):
    d = {"status": "to_check", "countermeasures": [cm("instruction")],
         "check": {"date": "2026-11-11", "how": "reread the next 10 threads"}}
    d.update(kw)
    return base(**d)


def test_minimal_complaint_is_to_understand():
    e, notes = andon.add(base(), D)
    assert e["id"] == "A001" and e["status"] == "to_understand" and e["date"] == "2026-11-04"
    assert notes == []
    assert andon.load()[0]["log"][0]["text"] == "complaint logged"


@pytest.mark.parametrize("field", ["system", "who", "verbatim", "what_happened", "cause"])
def test_required_field(field):
    with pytest.raises(andon.Refusal, match=field):
        andon.add(base(**{field: ""}), D)
    assert andon.load() == []


def test_unknown_cause_and_level():
    with pytest.raises(andon.Refusal, match="Unknown cause"):
        andon.add(base(cause="meh"), D)
    with pytest.raises(andon.Refusal, match="Unknown countermeasure level"):
        andon.add(base(countermeasures=[cm("pray")]), D)


def test_to_check_needs_a_dated_check():
    with pytest.raises(andon.Refusal, match="check.date"):
        andon.add(base(status="to_check", countermeasures=[cm("instruction")]), D)


def test_held_needs_proof_silence_is_not_enough():
    e, _ = andon.add(checked(), D)
    with pytest.raises(andon.Refusal, match="Silence"):
        andon.update(e["id"], {"status": "held"}, D)
    e, _ = andon.update(e["id"], {"status": "held", "check": {"proof": "10 threads reread, all under 8 lines"}}, D)
    assert e["check"]["done_on"] == "2026-11-04"
    assert e["check"]["how"] == "reread the next 10 threads"  # merged, not overwritten


def test_recurrence_marks_the_previous_one_and_forces_one_level_up():
    a, _ = andon.add(checked(date="2026-10-01"), D)
    b, notes = andon.add(base(who="a cofounder"), D)
    assert b["recurs_from"] == a["id"]
    assert any("RECURRENCE" in n for n in notes)
    assert andon.find(andon.load(), a["id"])["status"] == "recurred"
    with pytest.raises(andon.Refusal, match="Go above it"):
        andon.update(b["id"], {"countermeasure": cm("instruction"), "status": "in_progress"}, D)
    b, _ = andon.update(b["id"], {"countermeasure": cm("guardrail", "sending blocked above 8 lines"), "status": "in_progress"}, D)
    assert andon.rank(b) == 3


def test_same_level_allowed_only_at_code_level_and_in_writing():
    andon.add(checked(date="2026-09-01", countermeasures=[cm("mechanism")]), D)
    b, _ = andon.add(base(date="2026-10-01"), D)
    with pytest.raises(andon.Refusal, match="same_level"):
        andon.update(b["id"], {"countermeasure": cm("mechanism"), "status": "in_progress"}, D)
    b, _ = andon.update(b["id"], {"countermeasure": cm("mechanism"), "status": "in_progress",
                                  "same_level": "the first change cut the daily digest, this one filters the flicker"}, D)
    # Below the guardrail, no written excuse holds: you have to go up.
    andon.add(checked(system="tutor", date="2026-09-01"), D)
    c, _ = andon.add(base(system="tutor", date="2026-10-01"), D)
    with pytest.raises(andon.Refusal, match="Go above it"):
        andon.update(c["id"], {"countermeasure": cm("instruction"), "status": "in_progress", "same_level": "promise"}, D)


def test_an_awaited_decision_can_come_before_the_countermeasure():
    e, _ = andon.add(base(status="waiting_owner", owner="the CEO", waiting_for="pick the feedback channel"), D)
    assert e["status"] == "waiting_owner" and e["since"] == "2026-11-04"
    m, _ = andon.add(base(system="tutor", date="2026-10-01", status="waiting_owner", owner="the CTO", waiting_for="merge"), D)
    assert m["since"] == "2026-10-01"  # the wait starts on the day of the complaint
    with pytest.raises(andon.Refusal, match="owner"):
        andon.add(base(system="tutor", status="waiting_owner"), D)


def test_different_defect_is_not_a_recurrence():
    a, _ = andon.add(checked(date="2026-10-01"), D)
    b, notes = andon.add(base(different_defect="this is the Monday email, not the threads", countermeasures=[cm("instruction")]), D)
    assert "recurs_from" not in b
    assert andon.find(andon.load(), a["id"])["status"] == "to_check"
    assert any("different defect" in n for n in notes)


def test_same_open_problem_gets_attached_instead_of_duplicated():
    a, _ = andon.add(base(), D)
    with pytest.raises(andon.Refusal, match="still open"):
        andon.add(base(who="a consultant"), D)
    a, notes = andon.update(a["id"], {"also": {"who": "a consultant", "verbatim": "same"}}, D)
    assert len(a["also"]) == 1 and "2 people" in notes[0]


def test_subsystem_counts_as_the_system():
    andon.add(checked(date="2026-10-01"), D)
    b, _ = andon.add(base(system="Project-Bot/weekly-emails"), D)
    assert b["recurs_from"] == "A001" and b["system"] == "project-bot/weekly-emails"


def test_old_complaint_outside_the_window_is_not_a_recurrence():
    andon.add(checked(date="2026-01-01"), D)
    b, _ = andon.add(base(), D)
    assert "recurs_from" not in b


def test_identity_and_recurrence_link_cannot_be_rewritten():
    a, _ = andon.add(base(), D)
    a, _ = andon.update(a["id"], {"id": "A999", "recurs_from": "A000", "what_happened": "40-line threads, every day."}, D)
    assert a["id"] == "A001" and "recurs_from" not in a


def test_chronic_cause_same_cause_on_several_systems():
    andon.add(base(system="project-health", status="legacy", countermeasures=[cm("mechanism")], date="2026-08-11"), D)
    andon.add(base(system="chat-bots", status="legacy", countermeasures=[cm("mechanism")], date="2026-08-22"), D)
    assert andon.chronic(andon.load(), D) == []  # only twice
    andon.add(base(date="2026-11-03"), D)
    ch = andon.chronic(andon.load(), D)
    assert ch[0]["cause"] == "noise" and ch[0]["times"] == 3 and not ch[0]["standard_set"]
    assert "No common standard set" in andon.review_text(andon.load(), D)


def test_checks_due_and_brief():
    assert andon.brief_text(andon.load(), D) == ""
    andon.add(checked(check={"date": "2026-11-04", "how": "reread"}), D)
    andon.add(checked(system="tutor", check={"date": "2026-11-20", "how": "reread"}), D)
    due = andon.checks_due(andon.load(), D)
    assert [e["system"] for e in due] == ["project-bot"]
    assert andon.brief_text(andon.load(), D) == "Andon: 1 countermeasure to check."
    assert "check coming (1)" in andon.review_text(andon.load(), D)


def test_long_wait_on_an_owner_shows_up_in_the_brief():
    e, _ = andon.add(base(status="waiting_owner", countermeasures=[cm("guardrail")], owner="the CTO", waiting_for="merge of PR #900"),
                     dt.date(2026, 10, 20))
    assert e["since"] == "2026-10-20"
    assert "A001 waiting on the CTO for 15 d" in andon.brief_text(andon.load(), D)
    assert andon.brief_text(andon.load(), dt.date(2026, 10, 25)) == ""


def test_held_indicator():
    a, _ = andon.add(checked(date="2026-10-01"), D)
    andon.update(a["id"], {"status": "held", "check": {"proof": "seen"}}, D)
    andon.add(checked(system="tutor", date="2026-10-01"), D)
    andon.add(base(system="tutor"), D)  # recurrence: A002 came back
    assert andon.held_90d(andon.load(), D) == {"held": 1, "recurred": 1}
    assert "1 held, 1 recurred (50 % held)" in andon.review_text(andon.load(), D)


def test_command_line(capsys):
    assert andon.main(["--on", "2026-11-04", "add", json.dumps(base())]) == 0
    assert "A001 logged" in capsys.readouterr().out
    assert andon.main(["add", json.dumps(base(cause="meh"))]) == 2
    assert "REFUSED" in capsys.readouterr().err
    assert andon.main(["--on", "2026-11-04", "review"]) == 0
    assert "To understand (1)" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["registry.json", "registry.example.json"])
def test_shipped_registries_are_valid(name):
    """A registry on disk must always pass the rules: nothing written by hand gets around them."""
    path = Path(andon.__file__).resolve().parent / name
    if not path.exists():
        pytest.skip(f"no {name} yet")
    entries = json.loads(path.read_text(encoding="utf-8"))
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids))
    for e in entries:
        andon.validate(e, entries)


def test_badly_written_pr_refused():
    with pytest.raises(andon.Refusal, match="PR"):
        andon.add(base(status="waiting_owner", owner="the CTO", waiting_for="merge", pr=["#886"]), D)


def test_todo_only_wakes_the_round_when_there_is_work():
    states = {"acme/tools#1": "MERGED", "acme/tools#2": "OPEN", "acme/tools#3": "CLOSED"}
    fake_github = states.get  # an unknown PR gives None: nothing is concluded
    assert andon.todo(andon.load(), D, fake_github) == []
    andon.add(base(status="waiting_owner", owner="the CTO", waiting_for="merge", pr=["acme/tools#1"]), D)
    andon.add(base(system="tutor", status="waiting_owner", owner="the CTO", waiting_for="merge",
                   pr=["acme/tools#1", "acme/tools#2"]), D)
    andon.add(base(system="account-analyst", status="waiting_owner", owner="the CTO", waiting_for="merge", pr=["acme/tools#3"]), D)
    andon.add(base(system="revenue-memo", status="waiting_owner", owner="the CTO", waiting_for="merge", pr=["acme/tools#9"]), D)
    andon.add(base(system="assistant", status="waiting_owner", owner="the CEO", waiting_for="decide"), D)
    is_live = lambda r: ("live", f"{r}: green")  # noqa: E731
    work = andon.todo(andon.load(), D, fake_github, is_live)
    assert len(work) == 2
    assert work[0].startswith("A001:") and "date the check" in work[0]  # all merged and live
    assert work[1].startswith("A003:") and "closed without merge" in work[1]  # A002 half, A004 unknown, A005 a decision
    # Merged but not deployed yet: we wait, no model woken for nothing.
    assert andon.todo(andon.load(), D, fake_github, lambda r: ("not_yet", "deploy running"))[0].startswith("A003")
    # Merged, deployment unreadable: tell the user rather than conclude.
    assert "cannot be established" in andon.todo(andon.load(), D, fake_github, lambda r: ("unknown", "nothing readable"))[0]
    andon.add(checked(system="singing-app", check={"date": "2026-11-04", "how": "rerun the test"}), D)
    assert "A006: check due (rerun the test)" in andon.todo(andon.load(), D, fake_github, is_live)


def test_on_monday_the_round_reviews_chronic_causes():
    for i, s in enumerate(["project-health", "chat-bots", "project-bot"]):
        andon.add(base(system=s, status="legacy", countermeasures=[cm("mechanism")], date=f"2026-10-0{i + 1}"), D)
    assert andon.todo(andon.load(), D, lambda r: None) == []  # Wednesday
    monday = dt.date(2026, 11, 9)
    assert andon.todo(andon.load(), monday, lambda r: None) == ["monday: review of chronic causes (noise)"]


def test_todo_on_the_command_line_exit_code(capsys):
    assert andon.main(["--on", "2026-11-04", "todo"]) == 1
    assert "Nothing to do" in capsys.readouterr().out


def fake_gh(pr, statuses=None, checks=None):
    def gh(args):
        if args[:2] == ["pr", "view"]:
            return pr
        if args[0] == "api" and args[1].endswith("/status"):
            return None if statuses is None else {"statuses": list(statuses)}
        if args[0] == "api" and args[1].endswith("/check-runs"):
            return None if checks is None else {"check_runs": list(checks)}
        raise AssertionError(args)
    return gh


PR = {"state": "MERGED", "mergeCommit": {"oid": "abc"}}
REF = "acme/tools#42"
GREEN_STATUS = {"context": "Vercel", "state": "success"}
GREEN_CHECK = {"name": "tests", "status": "completed", "conclusion": "success"}


def test_live_when_every_status_and_check_is_green():
    assert andon.live(REF, fake_gh(PR, [GREEN_STATUS], [GREEN_CHECK]))[0] == "live"
    # A skipped check is neither proof nor failure.
    skipped = {"name": "preview", "status": "completed", "conclusion": "skipped"}
    assert andon.live(REF, fake_gh(PR, [GREEN_STATUS], [GREEN_CHECK, skipped]))[0] == "live"


def test_live_not_yet_when_something_is_pending_or_red():
    assert andon.live(REF, fake_gh(PR, [{**GREEN_STATUS, "state": "pending"}], [GREEN_CHECK]))[0] == "not_yet"
    assert andon.live(REF, fake_gh(PR, [GREEN_STATUS], [{"name": "deploy", "status": "in_progress", "conclusion": None}]))[0] == "not_yet"
    verdict, detail = andon.live(REF, fake_gh(PR, [GREEN_STATUS], [{**GREEN_CHECK, "conclusion": "failure"}]))
    assert verdict == "not_yet" and "failed" in detail


def test_live_unknown_when_nothing_is_readable():
    # Silence is not proof: merged with no status at all, or statuses unreadable.
    assert andon.live(REF, fake_gh(PR, [], []))[0] == "unknown"
    assert andon.live(REF, fake_gh(PR, None, None))[0] == "unknown"
    only_skipped = {"name": "preview", "status": "completed", "conclusion": "skipped"}
    assert andon.live(REF, fake_gh(PR, [], [only_skipped]))[0] == "unknown"


def test_live_open_pr_or_silent_github():
    assert andon.live(REF, fake_gh({"state": "OPEN"}))[0] == "not_yet"
    assert andon.live(REF, lambda args: None)[0] == "unknown"
