#!/usr/bin/env python3
"""Duplicate-guard tests (the user, Nov 7, 2026 — the #471 replay).

ISOLATED BY CONSTRUCTION: every file this suite touches is a fresh
temp file — a synthetic prose log, an event book beside it under the
derived name, and a piles file beside that. Nothing here reads or
writes the live outreach log or the live event book, so this suite
can never poison another suite (the guard's first version shipped
inside run_tests.py, whose copy Spine shares the accumulated tests/
scratch book with run_events_tests.py — cross-suite state made both
suites' results depend on run order; this file is the fix).

The mechanism under test (from the #471 forensics): the harness
re-delivered ONE record call ~26 times; the FIRST delivery wrote its
prose line but the event twin never landed; every later delivery
appended BOTH sides. record() therefore refuses — before writing
anything — a record whose outcome already sits in the prose log with
NO outcome event in the book (a half-completed write being replayed).
Legitimate sequences all carry event twins and must keep recording:
a fresh outcome on a stocked item, a second outcome after the first,
and a repeat park (staged -> staged).

Run: python3 tests/run_duplicate_guard_tests.py
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
import log_writer  # noqa: E402
from pipeline import Spine  # noqa: E402

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name
          + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


HEADER = ("# Outreach log (duplicate-guard fixture)\n\n"
          "## 2026-11-06 — LinkedIn Recommended applications batch — "
          "2026-11-06: STARTED\n\n")


def _spine(tmp: Path) -> Spine:
    log = tmp / "fixture-log.md"
    log.write_text(HEADER, encoding="utf-8")
    return Spine(log_path=str(log))


def _book(sp: Spine, iid: int) -> list[dict]:
    return [e for e in events_mod.read_events(sp.events_path)
            if int(e.get("item") or -1) == iid]


def _refused(sp: Spine, result: dict, log: str) -> bool:
    try:
        sp.record(result, log_path=log)
    except ValueError:
        return True
    return False


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        sp = _spine(tmp)
        log = str(tmp / "fixture-log.md")

        def stock(iid: int, company: str):
            log_writer.append_entry(
                log, f"STOCKED — #{iid} {company}, Data Scientist. "
                     f"SOURCE TAG: LINKEDIN.")

        # (1) Fresh outcome on a stocked item records normally.
        stock(901, "Freshco")
        entry = sp.record(
            {"item_id": 901, "outcome": "submitted",
             "portal": "Ashby (TEST)", "confirmation": "TEST fresh"},
            log_path=log)
        check("fresh outcome records (prose + event)",
              "SUBMITTED" in entry
              and [e["type"] for e in _book(sp, 901)] == ["submitted"])

        # (2) A second, different outcome records (record again OK).
        sp.record({"item_id": 901, "outcome": "email_verified",
                   "message_id": "m1", "sender": "s@example.com",
                   "subject": "Application received"}, log_path=log)
        check("second outcome records (submitted -> verified)",
              [e["type"] for e in _book(sp, 901)]
              == ["submitted", "verified"])

        # (3) A repeat park records: staged -> staged is a designed
        # legit sequence (a session re-parks with a new blocker).
        stock(902, "Parkco")
        _stage = {"item_id": 902, "outcome": "staged",
                  "step": "Employer questions page",
                  "blocker": "approval card presented at Submit",
                  "blocker_kind": "approval_card"}
        sp.record(dict(_stage), log_path=log)
        sp.record(dict(_stage), log_path=log)
        check("repeat park records (staged -> staged)",
              [e["type"] for e in _book(sp, 902)]
              == ["staged", "staged"])

        # (4) THE GUARD: an outcome in prose with NO book twin (the
        # half-completed first write), re-recorded -> REFUSED, and
        # nothing is written on either side.
        stock(903, "Guardco")
        _view = {"id": 903, "company": "Guardco",
                 "role": "Data Scientist"}
        log_writer.append_entry(log, log_writer.submitted(
            _view, "Ashby (TEST)", "TEST half-completed seed",
            "LINKEDIN", ""))
        lines_before = len(Path(log).read_text(
            encoding="utf-8").splitlines())
        check("prose-only outcome refuses its replay",
              _refused(sp, {"item_id": 903, "outcome": "submitted",
                            "portal": "Ashby (TEST)",
                            "confirmation": "TEST replay"}, log))
        check("refused replay wrote nothing",
              _book(sp, 903) == []
              and len(Path(log).read_text(
                  encoding="utf-8").splitlines()) == lines_before)

        # (5) THE GUARD, staged flavor: a prose-only STAGED entry,
        # re-recorded as staged -> REFUSED.
        stock(904, "Stagedco")
        log_writer.append_entry(log, log_writer.staged(
            {"id": 904, "company": "Stagedco",
             "role": "Data Scientist"},
            "Employer questions page", "approval card presented"))
        check("prose-only staged refuses its replay",
              _refused(sp, {"item_id": 904, "outcome": "staged",
                            "step": "Employer questions page",
                            "blocker": "approval card presented",
                            "blocker_kind": "approval_card"}, log))

        # (6) A DIFFERENT outcome after a prose-only one is not the
        # replay: it records (and its event twin starts the book).
        sp.record({"item_id": 904, "outcome": "skipped",
                   "reason": "TEST — posting closed",
                   "why": "closed"}, log_path=log)
        check("different outcome after prose-only records",
              [e["type"] for e in _book(sp, 904)] == ["skipped"])

    if FAILS:
        print(f"\n{len(FAILS)} FAILURE(S): {FAILS}")
        return 1
    print("\nALL DUPLICATE-GUARD TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
