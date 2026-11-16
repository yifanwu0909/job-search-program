#!/usr/bin/env python3
"""backfill_invitations.py — ONE-TIME seed of pre-code invitation
history into the LIVE program/events.jsonl (run by hand only; no cron
job runs this — the shadow_pass.py --reconcile precedent).

the user, Nov 10, 2026: "handle the tracking in the code." Invitations were
tracked only in the prose outreach log until tonight. The verified
history below is the Nov 10, 2026 outreach run's own accounting from
that log — all-time 420 = 100 on Oct 30 + 30 each on Oct 31, Nov 1-7
and Nov 9 + 20 on Nov 8 (LinkedIn weekly limit) + 30 on Nov 10 — plus
the three Sent-People counter readings the log records (Nov 9 end
1,178; Nov 10 start 1,174 — the unexplained -4 flake; Nov 10 end
1,203). The seed goes through invitations.record_backfill: one
aggregate invite_backfill event per day, NO person names (the history
is counts only; inventing names would corrupt the record), counters
marked "backfill". Idempotent: a day already seeded is skipped, so a
re-run can never double-count.

The script also appends ONE listing entry to the shadow log
(hidden_files/shadow/shadow-log.md), like prior reconciliations, and
verifies before printing success: all-time == 420 and every day's
code-computed total == the seeded history.

Run: python3 program/backfill_invitations.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))

import invitations as inv  # noqa: E402
from pipeline import Spine  # noqa: E402
from state import CT  # noqa: E402

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
COUNTERS = [
    {"date": "2026-11-09", "phase": "end", "counter": 1178},
    {"date": "2026-11-10", "phase": "start", "counter": 1174},
    {"date": "2026-11-10", "phase": "end", "counter": 1203},
]
EXPECTED_ALL_TIME = 420

SLOG = BASE.parent / "hidden_files" / "shadow" / "shadow-log.md"


def main() -> int:
    sp = Spine()  # live log + LIVE program/events.jsonl
    target = int((sp.rules.get("invitations") or {}).get(
        "daily_target", inv.DEFAULT_DAILY_TARGET))
    res = inv.record_backfill(sp.events_path, HISTORY, COUNTERS)
    s = inv.compute_status(sp.events_path, date="2026-11-10",
                           target=target)
    per_day = {d: s["by_day"].get(d, {}).get("total")
               for d in (r["date"] for r in HISTORY)}
    expected = {r["date"]: r["count"] for r in HISTORY}
    ok = (s["all_time"] == EXPECTED_ALL_TIME and per_day == expected)
    now = datetime.now(CT)
    days_text = ", ".join(f"{r['date']}: {r['count']}" for r in HISTORY)
    entry = (
        f"\n## Invitation backfill — "
        f"{now.strftime('%Y-%m-%d %I:%M %p CT')}\n"
        f"- One-time seed of pre-code invitation history into LIVE "
        f"program/events.jsonl via invitations.record_backfill "
        f"(the user, Nov 10, 2026: invitations tracked in code from today). "
        f"Aggregate invite_backfill events, no person names — the "
        f"history is counts only.\n"
        f"- Days seeded ({len(res['appended'])} new, "
        f"{len(res['skipped'])} already present): {days_text}.\n"
        f"- Counter snapshots seeded "
        f"({len(res['counters_appended'])} new): Nov 9 end 1178; "
        f"Nov 10 start 1174; Nov 10 end 1203 — all marked backfill. "
        f"Nov 10 now computes: counter delta 29 vs recorded 30 -> "
        f"discrepancy -1; cross-day drift -4 (the flaky counter, as "
        f"numbers).\n"
        f"- Verification: code-computed all-time = {s['all_time']} "
        f"(expected {EXPECTED_ALL_TIME}); every day's total matches "
        f"the seeded history: {'YES' if per_day == expected else 'NO'}.\n")
    with SLOG.open("a", encoding="utf-8") as f:
        f.write(entry)
    print(json.dumps({
        "appended_days": len(res["appended"]),
        "skipped_days": len(res["skipped"]),
        "appended_counters": len(res["counters_appended"]),
        "all_time": s["all_time"], "expected_all_time":
        EXPECTED_ALL_TIME, "per_day": per_day,
        "nov10_counter": s["counter"], "verified": ok}, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
