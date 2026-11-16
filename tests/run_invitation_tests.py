#!/usr/bin/env python3
"""Invitation-tracking tests (the user, Nov 10, 2026 — invitations in code).

ISOLATED BY CONSTRUCTION: every file this suite touches is a fresh
temp event book under tempfile.mkdtemp. Nothing here reads or writes
the live program/events.jsonl or the live outreach log — the Nov 7,
2026 incident rule (a test briefly deleted the LIVE friction flag) is
why this suite never resolves a live path: the book path is built
from the temp dir only, and the suite asserts that before writing.

Covered: record validation (refusals write nothing), the duplicate
person+date guard, daily / all-time counting across the REAL
backfilled history (420 through Nov 10, 2026 — the same numbers
backfill_invitations.py seeded into the live book), quota math
vs the 30/day target, backfill idempotence, counter snapshots with
the within-day discrepancy flag (the Nov 10 flake: counter delta 29
vs 30 recorded -> discrepancy -1) and cross-day drift (start 1,174
after a prior end of 1,178 -> drift -4), and the architectural
guarantee that the application fold (state.fold_events) cannot see
invitation events.

Run: python3 tests/run_invitation_tests.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))

import events as events_mod  # noqa: E402
import invitations as inv  # noqa: E402
import outreach_targets as ot  # noqa: E402
import state as state_mod  # noqa: E402

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name
          + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# The verified pre-code history (the Nov 10 outreach run's own
# accounting in the prose log; all-time 420 through Nov 10, 2026).
HISTORY = [
    {"date": "2026-10-30", "count": 100},
    {"date": "2026-10-31", "count": 30},
    {"date": "2026-11-01", "count": 30},
    {"date": "2026-11-02", "count": 30},
    {"date": "2026-11-03", "count": 30},
    {"date": "2026-11-04", "count": 30},
    {"date": "2026-11-05", "count": 30},
    {"date": "2026-11-06", "count": 30},
    {"date": "2026-11-07", "count": 30},
    {"date": "2026-11-08", "count": 20},
    {"date": "2026-11-09", "count": 30},
    {"date": "2026-11-10", "count": 30},
]
TS = "2026-11-11T10:30:00-06:00"  # a live-style send on Nov 11 CT


def _book(tmp: Path) -> Path:
    book = tmp / "events.jsonl"
    assert BASE not in book.parents or "tmp" in str(book), book
    return book


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="invite-tests-"))
    book = _book(tmp)
    live = BASE / "events.jsonl"
    check("t0 book is a temp file, never the live book", book != live)

    # --- validation: refusals write nothing -------------------------
    for bad, label in [
            ({"note": True}, "missing person"),
            ({"person": "  ", "note": True}, "blank person"),
            ({"person": "Ada Lovelace"}, "missing note flag"),
            ({"person": "Ada Lovelace", "note": "yes"},
             "note flag not a bool"),
            ({"person": "Ada Lovelace", "note": True,
              "ts": "not-a-date"}, "unparseable ts")]:
        res = inv.record_invites(book, bad)
        check(f"v: {label} refused, nothing recorded",
              res["recorded"] == [] and len(res["refused"]) == 1)
    check("v: refused packets left the book absent/empty",
          not book.exists() or book.read_text() == "")

    # --- record + daily counting + quota ----------------------------
    res = inv.record_invites(book, {"invites": [
        {"person": "Ada Lovelace", "note": True, "source": "contacto",
         "company": "Analytical Engines", "role": "Recruiter", "ts": TS},
        {"person": "Grace Hopper", "note": False, "source": "contacto",
         "ts": TS},
        {"person": "Alan Turing", "note": True, "source": "contacto",
         "ts": TS}]})
    check("r: batch of 3 recorded", len(res["recorded"]) == 3
          and res["refused"] == [])
    st = inv.compute_status(book, date="2026-11-11")
    check("r: daily count 3", st["sent_on_date"] == 3)
    check("r: all-time 3", st["all_time"] == 3)
    check("r: quota remaining 27 of 30", st["remaining_today"] == 27
          and st["target"] == 30)

    # --- duplicate guard ---------------------------------------------
    res = inv.record_invites(book, {"person": "ada  lovelace",
                                    "note": True, "source": "contacto",
                                    "ts": TS})
    check("d: same person+date (case/space variant) refused",
          res["recorded"] == [] and len(res["refused"]) == 1
          and "duplicate" in res["refused"][0]["error"])
    res = inv.record_invites(book, {
        "person": "Ada Lovelace", "note": True, "source": "contacto",
        "ts": "2026-11-12T09:00:00-06:00"})
    check("d: same person on a DIFFERENT date records fine",
          len(res["recorded"]) == 1)
    st = inv.compute_status(book, date="2026-11-11")
    check("d: daily count unchanged by the refused duplicate",
          st["sent_on_date"] == 3)

    # --- contacto-only source gate on recording (the user, Nov 14, 2026) ---
    res = inv.record_invites(book, {"person": "No Source",
                                    "note": True, "ts": TS})
    check("s: send with NO source refused, nothing recorded",
          res["recorded"] == [] and len(res["refused"]) == 1
          and "source" in res["refused"][0]["error"])
    res = inv.record_invites(book, {"person": "Network Person",
                                    "note": True, "ts": TS,
                                    "source": "my_network"})
    check("s: send sourced from My Network refused (contacto only)",
          res["recorded"] == [] and len(res["refused"]) == 1
          and "not contacto" in res["refused"][0]["error"])
    st = inv.compute_status(book, date="2026-11-11")
    check("s: daily count still 3 after the source refusals",
          st["sent_on_date"] == 3)

    # --- counter snapshots: the Nov 10 flake, as numbers -------------
    inv.record_counter(book, "start", 100, day="2026-11-11", ts=TS)
    inv.record_counter(book, "end", 103, day="2026-11-11", ts=TS)
    st = inv.compute_status(book, date="2026-11-11")
    check("c: clean day reconciles (delta 3 == recorded 3)",
          st["counter"]["counter_delta"] == 3
          and st["counter"]["discrepancy"] == 0
          and st["counter"]["reconciled"] is True)
    try:
        inv.record_counter(book, "start", 101, day="2026-11-11", ts=TS)
        dup_snap = False
    except ValueError:
        dup_snap = True
    check("c: second start snapshot for a day refused", dup_snap)
    try:
        inv.record_counter(book, "middle", 101, day="2026-11-11", ts=TS)
        bad_phase = False
    except ValueError:
        bad_phase = True
    check("c: bad phase refused", bad_phase)

    # --- backfill: the real history, in a SECOND temp book -----------
    tmp2 = Path(tempfile.mkdtemp(prefix="invite-tests-bf-"))
    book2 = _book(tmp2)
    res = inv.record_backfill(book2, HISTORY, counters=[
        {"date": "2026-11-09", "phase": "end", "counter": 1178},
        {"date": "2026-11-10", "phase": "start", "counter": 1174},
        {"date": "2026-11-10", "phase": "end", "counter": 1203}])
    check("b: 12 days + 3 counters appended",
          len(res["appended"]) == 12
          and len(res["counters_appended"]) == 3)
    st = inv.compute_status(book2, date="2026-11-10")
    check("b: all-time == 420", st["all_time"] == 420,
          f"got {st['all_time']}")
    for row in HISTORY:
        got = st["by_day"][row["date"]]["total"]
        check(f"b: {row['date']} == {row['count']}", got == row["count"],
              f"got {got}")
    check("b: Nov 10 quota remaining 0 (30 of 30)",
          inv.compute_status(book2, date="2026-11-10")
          ["remaining_today"] == 0)
    check("b: Nov 8 quota remaining 10 (20 of 30)",
          inv.compute_status(book2, date="2026-11-08")
          ["remaining_today"] == 10)
    c = st["counter"]
    check("b: Nov 10 counter delta 29 vs recorded 30 -> discrepancy -1",
          c["counter_delta"] == 29 and c["discrepancy"] == -1
          and c["reconciled"] is False)
    check("b: cross-day drift -4 (start 1174 vs prior end 1178)",
          c["drift_from_prior_end"] == -4 and c["prior_end"] == 1178)
    res2 = inv.record_backfill(book2, HISTORY)
    check("b: re-running the backfill is idempotent (all skipped)",
          len(res2["appended"]) == 0 and len(res2["skipped"]) == 12)
    check("b: all-time still 420 after the idempotent re-run",
          inv.compute_status(book2)["all_time"] == 420)

    # backfill + individual sends share one count
    inv.record_invites(book2, {"person": "Synthetic Person",
                               "note": True, "source": "contacto",
                               "ts": "2026-11-08T11:00:00-06:00"})
    st8 = inv.compute_status(book2, date="2026-11-08")
    check("b: Nov 8 total 21 after one live-style send "
          "(20 backfilled + 1)", st8["sent_on_date"] == 21
          and st8["remaining_today"] == 9)

    # --- the application fold cannot see invitation events -----------
    folded = state_mod.fold_events(events_mod.read_events(book2))
    check("f: fold_events yields no verified items from invites",
          folded["verified"] == set() and folded["items"] == {})

    # --- outreach targets: code dictates, agent does not judge -------
    # (the user, Nov 13, 2026: contacto returns a JSON packet; code decides
    # yes/no per person from rules.yaml invitations.hiring_contacts —
    # NO per-role cap, NO peers.)
    import yaml as _yaml
    _rules = _yaml.safe_load(
        (BASE / "config" / "rules.yaml").read_text(encoding="utf-8"))
    _hc = (_rules.get("invitations") or {}).get("hiring_contacts") or {}
    check("t: config carries hiring_contacts with max_per_role null "
          "(no cap, the user Nov 13 2026)",
          _hc.get("max_per_role", "missing") is None
          and "allow_title_keywords" in _hc)

    def _t(person, title, company="Acme", typ="influencer",
           link="https://www.linkedin.com/in/x", cur=True,
           source="contacto"):
        t = {"person": person, "title": title, "company": company,
             "type": typ, "link": link, "current_employee": cur,
             "role": "Data Scientist"}
        if source is not None:
            t["source"] = source
        return t

    _blocked = {state_mod.normalize_company("Cognizant")}
    _out = ot.validate_targets({"targets": [
        _t("Rita", "Senior Technical Recruiter", typ="recruiter"),
        _t("Hank", "Director of Data Science", typ="hiring_manager"),
        _t("Vera", "VP, Machine Learning", typ="hiring_manager"),
        _t("Stan", "Staff Data Scientist"),
        _t("Priya", "Principal Machine Learning Engineer"),
        _t("Lena", "Data Science Lead"),
        _t("Mona", "Data Science Manager", typ="hiring_manager"),
        _t("Pete", "Senior Data Scientist"),
        _t("June", "Junior Data Scientist"),
        _t("Dana", "Data Scientist"),
        _t("Mike", "Senior Machine Learning Engineer"),
        _t("Paul", "Data Scientist", typ="peer"),
        _t("Bree", "Director of Data Science", company="Cognizant",
           typ="hiring_manager"),
        _t("Former", "Principal Data Scientist", cur=False),
        _t("Nolink", "Director of Data Science", link="",
           typ="hiring_manager"),
        _t("Nosrc", "Director of Data Science", source=None,
           typ="hiring_manager"),
        _t("Linky", "Director of Data Science", source="linkedin_search",
           typ="hiring_manager"),
    ]}, _hc, _blocked)
    _acc = {r["person"] for r in _out["accepted"]}
    _rej = {r["person"]: r["reason"] for r in _out["rejected"]}
    check("t: recruiter/hiring-manager/VP/staff/principal/lead/manager "
          "all accepted", _acc == {"Rita", "Hank", "Vera", "Stan",
                                   "Priya", "Lena", "Mona"},
          f"accepted={sorted(_acc)}")
    check("t: SEVEN accepted for ONE role — no per-role cap in code",
          len(_out["accepted"]) == 7)
    check("t: senior/junior/plain DS and senior MLE rejected as peers",
          all(_rej.get(p) == "peer_or_below_no_influence_title"
              for p in ("Pete", "June", "Dana", "Mike")))
    check("t: finder-labelled peer rejected even with a DS title",
          _rej.get("Paul") == "peer_type_labelled_by_finder")
    check("t: blocked company rejected",
          _rej.get("Bree") == "blocked_company")
    check("t: unverified current employment rejected",
          _rej.get("Former") == "current_employment_not_verified")
    check("t: missing profile link rejected",
          _rej.get("Nolink") == "not_a_linkedin_profile_link")
    check("t: config carries contacto_only (the user, Nov 14 2026)",
          _hc.get("contacto_only") is True
          and _hc.get("linkedin_search_for_outreach") == "never")
    check("t: target with NO source label rejected (contacto only)",
          _rej.get("Nosrc") == "source_missing_contacto_only")
    check("t: target labelled LinkedIn search rejected (contacto only)",
          _rej.get("Linky") == "non_contacto_source_refused")
    try:
        ot.validate_targets({"nope": []}, _hc, _blocked)
        check("t: malformed packet refused whole", False)
    except ValueError:
        check("t: malformed packet refused whole", True)

    print(f"\n{'ALL PASS' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}"
          f" ({len(FAILS)} failed)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
