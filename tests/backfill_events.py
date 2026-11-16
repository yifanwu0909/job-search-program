#!/usr/bin/env python3
"""Seed tests/events_test.jsonl from state.py's parse of the LIVE log.

Fixture builder for the shadow-mode comparison: it derives the event
stream for the Nov 4, 2026 window from the prose parse and writes it to
a TEST events file. The live program/events.jsonl is deliberately NOT
backfilled — driver-mode runs fill it, and seeding it from prose would
make the shadow comparison circular.

The test file is a fixture: each run regenerates it from scratch (the
append-only rule governs the real logs, not this fixture).

HISTORY (Nov 4, 2026, the Fetch #180 limbo fix): this seed originally
wrote ONE event per item — its final folded disposition. That was a
faithful mirror while state-check compared only folded dispositions.
State-check now ALSO compares raw limbo/staged event presence (fix c),
so the seed mirrors the item's full disposition-event history for the
window, in log order: every stocked/claimed/staged/captcha/limbo/
unstaged/skipped/submitted event, plus a `verified` event after the
submitted event of each verified item. Folded state and presence then
agree by construction — the fixture got stronger, not weaker.

Run: python3 tests/backfill_events.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))

import events as events_mod  # noqa: E402
import state as state_mod  # noqa: E402

LIVE = Path.home() / ("workspace/goals/linkedin-ai-recruiter-outreach-weekly/"
                      "hidden_files/outreach-log.md")
OUT = BASE / "tests" / "events_test.jsonl"
WDATE = "2026-11-04"

# Prose kinds the event vocabulary can express (state.EVENT_DISPOSITION).
SEEDABLE = {"stocked", "claimed", "staged", "captcha", "limbo",
            "unstaged", "skipped", "submitted"}


def _staged_why(st, entry_by_line, item, ev) -> str:
    """Why code for one staged event, from ITS entry's segment — the
    segment head carries gate/pay notes that would swamp the code, so
    map from the text after "step:" when present (as the original
    last-event-only seed did)."""
    entry = entry_by_line.get(ev[0])
    seg = (dict(state_mod.segments(entry)).get(item.id, "")
           if entry is not None else "")
    idx = seg.lower().find("step:")
    step_text = seg[idx + 5:] if idx >= 0 else (ev[3] or "")
    return events_mod.why_code(step_text)


def main() -> int:
    if OUT.exists():
        OUT.unlink()
    st = state_mod.parse_log(str(LIVE))
    w = st.window_for(WDATE)
    ws = st.window_status(WDATE)
    verified_ids = {it.id for it in ws["verified"]}
    # Seed ONLY this window's member items (the union of the window's
    # own lists). Full history per member — but an old item merely
    # re-mentioned in this window's section (a rescue note, an all-time
    # one-off like Versa) is not a member, and seeding its stray events
    # would invent window state the prose side never claimed.
    member_ids = set()
    for key in ("verified", "staged", "captcha", "limbo", "bench",
                "claimed"):
        member_ids |= {it.id for it in ws[key]}
    entry_by_line = {e.line_no: e for e in st.entries}
    counts: Counter = Counter()
    for it in sorted(st.items.values(), key=lambda x: x.id):
        if it.id not in member_ids:
            continue
        src = (it.source or "").upper() or None
        for ev in sorted(it.events, key=lambda e: e[0]):
            line, ts, kind, detail = ev[0], ev[1], ev[2], ev[3]
            if kind not in SEEDABLE:
                continue
            # A verified member's SUBMITTED event seeds even when its
            # entry sits in the prior section: STARTING COUNTS can
            # attribute such an item to this window (#186 Turo, whose
            # submission entry precedes the Nov 4 section line), and
            # the event's win stamp carries that attribution — the
            # same way the live event book holds it.
            if line < w.section_line and not (
                    kind == "submitted" and it.id in verified_ids):
                continue
            stamp = ts.isoformat() if ts else w.open_dt.isoformat()
            if kind == "staged":
                events_mod.append_event(
                    OUT, "staged", item=it.id, src=src, win=WDATE,
                    ts=stamp, why=_staged_why(st, entry_by_line, it, ev))
            elif kind == "skipped":
                events_mod.append_event(
                    OUT, "skipped", item=it.id, src=src, win=WDATE,
                    ts=stamp, why=events_mod.why_code(detail or ""))
            elif kind == "submitted":
                events_mod.append_event(
                    OUT, "submitted", item=it.id, src=src, win=WDATE,
                    ts=stamp)
                if it.id in verified_ids:
                    events_mod.append_event(
                        OUT, "verified", item=it.id, src=src, win=WDATE,
                        ts=stamp)
                    counts["verified"] += 1
            else:
                events_mod.append_event(
                    OUT, kind, item=it.id, src=src, win=WDATE, ts=stamp)
            counts[kind] += 1
    total = sum(counts.values())
    print(f"seeded {OUT.name}: {total} events "
          f"({', '.join(f'{k} {v}' for k, v in sorted(counts.items()))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
