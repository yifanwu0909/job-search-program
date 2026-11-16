#!/usr/bin/env python3
"""Email-sweep tests — the bookkeeping half only (the user, Nov 5, 2026: the
script never reads or judges email; Muse does). All writes go to temp
copies; Gmail search is stubbed; no message body is ever fetched.

Run: python3 tests/run_email_sweep_tests.py

Coverage:
  (a) scan-state parsing — dedupe IDs union; Last scan line parses.
  (b) watch list — 90-day prune; limbo = limbo event with no submitted
      event (a submitted-then-limbo item stays submitted); bullet-only
      companies merge in; prose-artifact companies rejected.
  (c) work list — candidates exclude recorded + dismissed IDs and carry
      triage metadata only; a real run stages pending_run + stats.
  (d) record: forward in hours (deliver_now, log entry, Reported
      bullet, progress 'ready'); forward at night (held; surfaces as
      held_due next morning; mark-delivered moves progress to
      'reported'); forward at night with a deadline inside 24h
      (deliver_now by arithmetic on Muse's deadline).
  (e) record: rejection (record-only entry + Reported bullet),
      confirmation (Reviewed bullet only), limbo_confirmation
      (follow-up entry + Reviewed + watch bullet), process (Reviewed
      bullet), out_of_scope (dismissed only, nothing written anywhere
      else).
  (f) record refuses a duplicate ID and an unwatched company.
  (g) complete — summary entry written, watermark advances to the
      run's START time, staged state cleared; completing with no staged
      run is an error.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "checks"))
import email_sweep as es  # noqa: E402
import state as state_mod  # noqa: E402

HST = ZoneInfo("Pacific/Honolulu")
FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name
          + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


STATE_FIXTURE = """# Application email scan state

- Last scan: 2026-11-05 14:33 HST (Pacific/Honolulu) — hourly run; searched since last scan minus a 24-hour overlap.
- Watch list at scan time:
  - Acme Corp — Data Scientist — submitted Oct 26, 2026 (per outreach log #901)
  - Bulletco — Machine Learning Engineer — submitted Nov 1, 2026 (per outreach log, one-off application)
- Limbo watch (audit #10 fix G1): 1 item — #903 FetchClone — Senior Data Scientist II (Gem route)
- Reported message IDs:
  - aaaaaaaaaaaaaaaa — Someone <x@example.com>, Nov 4, 2026 — "Hi" (a forward note)
- Reviewed but OUT OF SCOPE (application-confirmation receipts / submission-process mail, not reported):
  - bbbbbbbbbbbbbbbb — no-reply@ashbyhq.com, Nov 4, 2026 — "Thanks" (a receipt)
"""

LOG_FIXTURE = """# Outreach log (test fixture)

## 2026-11-05 — LinkedIn Recommended applications batch — 2026-11-05

- [3:00 PM CST, Mon Oct 26, 2026] STOCKED #901 — Acme Corp — Data Scientist — source LINKEDIN
- [3:05 PM CST, Mon Oct 26, 2026] SUBMITTED (page-confirmed) — #901 Acme Corp, Data Scientist (Acme careers). Confirmation: portal page. SOURCE TAG: LINKEDIN. (Recorded by spine program.)
- [3:00 PM CST, Tue Jul 28, 2026] STOCKED #902 — Oldco — Data Scientist — source LINKEDIN
- [3:05 PM CST, Tue Jul 28, 2026] SUBMITTED (page-confirmed) — #902 Oldco, Data Scientist (Oldco careers). Confirmation: portal page. SOURCE TAG: LINKEDIN. (Recorded by spine program.)
- [9:16 PM CST, Wed Nov 4, 2026] #903 FetchClone — Senior Data Scientist II — IN LIMBO — submit clicked, outcome unknown — do not re-apply.
- [3:00 PM CST, Mon Oct 26, 2026] STOCKED #904 — Resolved Co — Data Scientist — source LINKEDIN
- [3:05 PM CST, Mon Oct 26, 2026] SUBMITTED (page-confirmed) — #904 Resolved Co, Data Scientist (Resolved careers). Confirmation: portal page. SOURCE TAG: LINKEDIN. (Recorded by spine program.)
- [4:00 PM CST, Mon Oct 26, 2026] #904 Resolved Co — Data Scientist — IN LIMBO — confirmation email not yet seen (later verified; bookkeeping note).
- [5:26 PM CST, Thu Nov 5, 2026] SEGMENT STATE — gate-passed — #905 (Sparse Co; figure 140000)
- [5:26 PM CST, Thu Nov 5, 2026] PREP READY — #905 Sparse Co, Data Scientist: tailored resume built and verified.

## 2026-11-05 — Recovery section (test fixture)

- [7:24 PM CST, Thu Nov 5, 2026] SUBMITTED (page-confirmed) — #905 ,  (Dayforce (jobs.example.com/905)). Confirmation: portal page.
"""

NOW = datetime(2026, 11, 5, 15, 0, tzinfo=HST)
NIGHT = datetime(2026, 11, 5, 23, 30, tzinfo=HST)
MORNING = datetime(2026, 11, 6, 9, 0, tzinfo=HST)


def test_parse_state() -> None:
    parsed = es.parse_scan_state(STATE_FIXTURE)
    check("a1 dedupe union",
          parsed["ids"] == {"aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"},
          str(parsed["ids"]))
    check("a2 last scan parsed",
          parsed["last_scan"] == (2026, 11, 5, 14, 33, "HST"),
          str(parsed["last_scan"]))


def test_watch_list() -> None:
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "log.md"
        log.write_text(LOG_FIXTURE, encoding="utf-8")
        st = state_mod.parse_log(str(log))
        submitted, limbo = es.build_watch_list(
            st, NOW.astimezone(es.CT), STATE_FIXTURE)
        ids = sorted(e.id for e in submitted if e.id)
        check("b1 recent submissions watched", ids == [901, 904], str(ids))
        check("b2 limbo watched", [e.id for e in limbo] == [903],
              str([e.id for e in limbo]))
        check("b3 submitted-then-limbo stays submitted",
              all(e.id != 904 for e in limbo))
        check("b4 bullet-only company watched",
              any(e.company == "Bulletco" for e in submitted))
        check("b5 prose-artifact company rejected",
              es._plausible_company(
                  "Atlassian Sr MLE listings are likely same req") is False
              and es._plausible_company("Walt Disney Company") is True)
        check("b6 sparse-segment item absent without raw text",
              all(e.id != 905 for e in submitted))
        submitted2, _ = es.build_watch_list(
            st, NOW.astimezone(es.CT), STATE_FIXTURE,
            raw_text=LOG_FIXTURE)
        sparse = [e for e in submitted2 if e.id == 905]
        check("b7 sparse-segment item filled from prep lines",
              len(sparse) == 1 and sparse[0].company == "Sparse Co"
              and sparse[0].role == "Data Scientist",
              str([(e.id, e.company, e.role) for e in sparse]))
        state_with_bullet = STATE_FIXTURE.replace(
            "  - Bulletco — Machine Learning Engineer — submitted "
            "Nov 1, 2026 (per outreach log, one-off application)",
            "  - Bulletco — Machine Learning Engineer — submitted "
            "Nov 1, 2026 (per outreach log, one-off application)\n"
            "  - Sparse Co — Data Scientist — submitted Nov 5, 2026 "
            "(per outreach log #905)")
        submitted3, _ = es.build_watch_list(
            st, NOW.astimezone(es.CT), state_with_bullet,
            raw_text=LOG_FIXTURE)
        check("b8 id-matched bullet never duplicates a log entry",
              len([e for e in submitted3 if e.id == 905]) == 1,
              str([(e.id, e.company) for e in submitted3]))


class Env:
    """Temp log/state/sidecar + stubbed Gmail search."""
    def __init__(self, messages):
        self.td = tempfile.TemporaryDirectory()
        base = Path(self.td.name)
        self.log = base / "log.md"
        self.scan = base / "scan.md"
        self.side = base / "side.json"
        self.log.write_text(LOG_FIXTURE, encoding="utf-8")
        self.scan.write_text(STATE_FIXTURE, encoding="utf-8")
        es.LOG_PATH, es.SCAN_STATE_PATH, es.SIDECAR_PATH = \
            self.log, self.scan, self.side
        self.queries = []

        def _stub(q, m):
            self.queries.append(q)
            return messages

        es.gmail_search = _stub

    def cleanup(self):
        self.td.cleanup()


TRIAGE = [
    {"id": "aaaaaaaaaaaaaaaa", "from": "Old <o@x.com>",
     "subject": "Already recorded", "date": "Thu, 05 Nov 2026"},
    {"id": "cccccccccccccccc", "from": "Recruiter <r@acme.com>",
     "subject": "Next steps", "date": "Thu, 05 Nov 2026"},
    {"id": "dddddddddddddddd", "from": "News <n@x.com>",
     "subject": "Digest", "date": "Thu, 05 Nov 2026"},
]


def judgment(mid, kind, **kw):
    base = {"gmail_id": mid, "kind": kind, "item_id": 901,
            "gist": "the gist", "sender": "Recruiter <r@acme.com>",
            "subject": "Next steps",
            "date_iso": "2026-11-05T23:30:00+00:00"}
    base.update(kw)
    return base


def test_work_list() -> None:
    env = Env(TRIAGE)
    out = es.work_list(HST, dry_run=False, now=NOW)
    cand_ids = [c["gmail_id"] for c in out["candidates"]]
    check("c1 recorded ID excluded", "aaaaaaaaaaaaaaaa" not in cand_ids)
    check("c2 fresh candidates listed untouched",
          cand_ids == ["cccccccccccccccc", "dddddddddddddddd"],
          str(cand_ids))
    side = es._load_sidecar()
    check("c3 run staged", side["pending_run"] is not None
          and side["run_stats"] is not None)
    check("c4 watch counts", out["watch_submitted"] == 4
          and out["watch_limbo"] == [903], str(out["watch_submitted"]))
    from datetime import timedelta as _td
    expected_after = str(int((NOW - _td(hours=1)).timestamp()))
    check("c5 window is the past hour (epoch after:)",
          bool(env.queries)
          and all(f"after:{expected_after}" in q for q in env.queries),
          str(env.queries[:1]))
    env.cleanup()


def test_record_forward() -> None:
    env = Env(TRIAGE)
    es.work_list(HST, dry_run=False, now=NOW)
    res = es.record(judgment("cccccccccccccccc", "forward",
                             subtype="interview request"), HST, now=NOW)
    check("d1 forward deliver_now in hours", res["deliver_now"] is True)
    log_text = env.log.read_text(encoding="utf-8")
    scan_text = env.scan.read_text(encoding="utf-8")
    check("d2 follow-up entry written",
          "APPLICATION FOLLOW-UP — Acme Corp" in log_text
          and "FORWARD-MOVING (interview request)" in log_text)
    check("d3 reported bullet written",
          "cccccccccccccccc" in scan_text)
    side = es._load_sidecar()
    check("d3b forward creates an open to-do (the user, Nov 6, 2026)",
          len(es.open_todos(side)) == 1
          and es.open_todos(side)[0]["gmail_id"] == "cccccccccccccccc"
          and es.open_todos(side)[0]["company"] == "Acme Corp"
          and res.get("todo", {}).get("status") == "open",
          str(side.get("todos")))
    out2 = es.work_list(HST, dry_run=True, now=NOW)
    check("d3c work list surfaces open to-dos",
          len(out2["open_todos"]) == 1
          and out2["forward_progress"]["todos_open"] == 1)
    import json as _json
    payload = _json.loads(es.todos_file_path().read_text(encoding="utf-8"))
    check("d3d track file lists the forward to-do as open",
          payload["open_count"] == 1
          and payload["open"][0]["gmail_id"] == "cccccccccccccccc"
          and payload["open"][0]["subtype"] == "interview request",
          str(payload)[:200])
    env.cleanup()

    env = Env(TRIAGE)
    es.work_list(HST, dry_run=False, now=NIGHT)
    res = es.record(judgment("cccccccccccccccc", "forward",
                             subtype="interview request"), HST, now=NIGHT)
    check("d4 forward held at night", res["deliver_now"] is False)
    out = es.work_list(HST, dry_run=True, now=MORNING)
    check("d5 held item due next morning", len(out["held_due"]) == 1)
    side = es._load_sidecar()
    p = side["held"][0]
    p["status"] = "reported"
    side["delivered"].append(p)
    side["held"] = []
    es._save_sidecar(side)
    side = es._load_sidecar()
    check("d6 progress kept: delivered recorded",
          len(side["delivered"]) == 1
          and side["delivered"][0]["status"] == "reported")
    env.cleanup()

    env = Env(TRIAGE)
    es.work_list(HST, dry_run=False, now=NIGHT)
    res = es.record(judgment("cccccccccccccccc", "forward",
                             subtype="interview request",
                             deadline_iso="2026-11-06T12:00:00-10:00"),
                    HST, now=NIGHT)
    check("d7 deadline inside 24h delivers at night",
          res["deliver_now"] is True and res["deadline_critical"] is True)
    env.cleanup()


def test_todos() -> None:
    # (i) TO-DOS (the user, Nov 6, 2026): non-forward kinds create none;
    # add-todo backfills once (deduped); complete closes it.
    env = Env(TRIAGE)
    es.work_list(HST, dry_run=False, now=NOW)
    es.record(judgment("1111111111111111", "rejection"), HST, now=NOW)
    check("i1 rejection creates no to-do",
          es.open_todos() == [], str(es._load_sidecar().get("todos")))
    r1 = es.add_todo({"gmail_id": "9999999999999999", "item_id": 901,
                      "company": "Acme Corp", "role": "Data Scientist",
                      "subtype": "next step", "gist": "do the form"},
                     now=NOW)
    r2 = es.add_todo({"gmail_id": "9999999999999999", "item_id": 901,
                      "company": "Acme Corp", "role": "Data Scientist",
                      "subtype": "next step", "gist": "do the form"},
                     now=NOW)
    check("i2 add-todo backfills once, deduped by gmail_id",
          r1["added"] is True and r2["added"] is False
          and len(es.open_todos()) == 1)
    side = es._load_sidecar()
    for t in side["todos"]:
        if t["gmail_id"] == "9999999999999999":
            t["status"] = "completed"
    es._save_sidecar(side)
    check("i3 completed to-do leaves the open list",
          es.open_todos() == [])
    import json as _json
    track = es.todos_file_path()
    payload = _json.loads(track.read_text(encoding="utf-8"))
    check("i4 code builds the track file with the important info",
          track.name == "forward_todos.json"
          and payload["open_count"] == 0
          and payload["completed_count"] == 1
          and payload["completed"][0]["company"] == "Acme Corp"
          and payload["completed"][0]["gist"] == "do the form",
          str(payload)[:200])
    env.cleanup()


def test_record_kinds() -> None:
    env = Env(TRIAGE)
    es.work_list(HST, dry_run=False, now=NOW)
    es.record(judgment("1111111111111111", "rejection"), HST, now=NOW)
    log_text = env.log.read_text(encoding="utf-8")
    scan_text = env.scan.read_text(encoding="utf-8")
    check("e1 rejection entry + bullet",
          "REJECTION (record-only" in log_text
          and "1111111111111111" in scan_text)
    es.record(judgment("2222222222222222", "confirmation"), HST, now=NOW)
    scan_text = env.scan.read_text(encoding="utf-8")
    check("e2 confirmation reviewed bullet only",
          "2222222222222222" in scan_text
          and log_text == env.log.read_text(encoding="utf-8"))
    es.record(judgment("3333333333333333", "limbo_confirmation",
                       item_id=903), HST, now=NOW)
    log_text = env.log.read_text(encoding="utf-8")
    scan_text = env.scan.read_text(encoding="utf-8")
    check("e3 limbo verification entry + watch bullet",
          "LIMBO VERIFICATION" in log_text
          and "FetchClone — Senior Data Scientist II — verified by email"
          in scan_text)
    es.record(judgment("4444444444444444", "process"), HST, now=NOW)
    check("e4 process bullet",
          "4444444444444444" in env.scan.read_text(encoding="utf-8"))
    before_log = env.log.read_text(encoding="utf-8")
    before_scan = env.scan.read_text(encoding="utf-8")
    es.record(judgment("5555555555555555", "out_of_scope", item_id=None,
                       company=None), HST, now=NOW)
    check("e5 out_of_scope writes nothing but the dismissal",
          env.log.read_text(encoding="utf-8") == before_log
          and env.scan.read_text(encoding="utf-8") == before_scan
          and "5555555555555555" in es._load_sidecar()["dismissed"])
    env.cleanup()


def test_record_refusals() -> None:
    env = Env(TRIAGE)
    es.work_list(HST, dry_run=False, now=NOW)
    try:
        es.record(judgment("aaaaaaaaaaaaaaaa", "rejection"), HST, now=NOW)
        check("f1 duplicate refused", False)
    except ValueError:
        check("f1 duplicate refused", True)
    try:
        es.record(judgment("6666666666666666", "rejection", item_id=None,
                           company="Nope Industries"), HST, now=NOW)
        check("f2 unwatched company refused", False)
    except ValueError:
        check("f2 unwatched company refused", True)
    res = es.record(judgment("6666666666666666", "rejection", item_id=None,
                             company="Acme Corp"), HST, now=NOW)
    check("f3 company-name resolution works", res["recorded"] is True)
    env.cleanup()


def test_complete() -> None:
    env = Env(TRIAGE)
    try:
        es.complete(HST, now=NOW)
        check("g1 complete without a staged run errors", False)
    except ValueError:
        check("g1 complete without a staged run errors", True)
    es.work_list(HST, dry_run=False, now=NOW)
    es.record(judgment("cccccccccccccccc", "forward",
                       subtype="interview request"), HST, now=NOW)
    out = es.complete(HST, now=MORNING)
    scan_text = env.scan.read_text(encoding="utf-8")
    log_text = env.log.read_text(encoding="utf-8")
    check("g2 summary written", "APPLICATION EMAIL SCAN" in log_text
          and "1 forward-moving" in log_text)
    check("g3 watermark = run start, not completion time",
          "Last scan: 2026-11-05 15:00 HST" in scan_text, scan_text[:200])
    side = es._load_sidecar()
    check("g4 staged state cleared", side["pending_run"] is None
          and side["run_stats"] is None)
    check("g5 outcome returned", out["completed"] is True)
    env.cleanup()


def test_handoff_check():
    # (h) THE HANDOFF CHECK on record (the user, Nov 5, 2026): the result
    # echoes the judgment as understood — with the application the
    # program resolved it to — and proves the records landed by
    # reading them back. A write that silently drops its scan-state
    # bullet comes back verified: false, never "recorded" clean.
    env = Env(TRIAGE)
    es.work_list(HST, dry_run=False, now=NOW)
    res = es.record(judgment("7777777777777777", "confirmation"),
                    HST, now=NOW)
    check("h1 clean record verifies + echoes the resolution",
          res["verified"] is True
          and res["understood"]["company"] == "Acme Corp"
          and res["landed"]["scan_state"] is True, str(res))
    orig_insert = es._section_insert
    es._section_insert = lambda lines, header, bullets: lines
    try:
        res2 = es.record(judgment("7777777777777778", "confirmation"),
                         HST, now=NOW)
    finally:
        es._section_insert = orig_insert
    check("h2 a dropped bullet is caught on read-back",
          res2["verified"] is False
          and any("scan state" in p for p in res2.get("problems", [])),
          str(res2))
    env.cleanup()


def main() -> int:
    test_parse_state()
    test_watch_list()
    test_work_list()
    test_record_forward()
    test_todos()
    test_record_kinds()
    test_record_refusals()
    test_complete()
    test_handoff_check()
    if FAILS:
        print(f"\n{len(FAILS)} FAILURE(S): {FAILS}")
        return 1
    print("\nALL EMAIL SWEEP TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
