#!/usr/bin/env python3
"""One-time backfill for STOCKING AS DATA (the user, Nov 6, 2026, fix #1).

Items stocked before stock.py wrote data records have their route
and salary only in the log's prose. This tool runs the OLD prose
miner (pipeline._route_and_salary, as it existed before the data
migration) over every stocked item in a log ONCE and writes the
results into that log's stocked-items data file, flagged
"backfilled": true. After the backfill verifies, the miner is
deleted from pipeline.py and this tool is kept only as the record
of the migration — it will not run against the new pipeline (the
miner it imports is gone).

Existing data-file entries (written by stock.py at stocking time)
are never overwritten: program-written data wins over mined data.

Usage: python3 backfill_stocked.py [--log PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))
import state as state_mod  # noqa: E402
import stock as stock_mod  # noqa: E402
from pipeline import Spine  # noqa: E402

_URL_RE = re.compile(r"https?://[^\s);]+")
_FIGURE_RE = re.compile(r"figure\s+\$?([\d,]{5,})")


def _own_stocking_bodies(st, it) -> list[str]:
    """The bodies of THIS item's own stocking entries: entries where
    the item's stocked event landed AND the item owns the entry's
    first segment (so a multi-item discovery entry is never mined
    for a later item's route)."""
    line_nos = {e[0] for e in it.events if e[2] == "stocked"}
    out = []
    for e in st.entries:
        if e.line_no not in line_nos:
            continue
        segs = state_mod.segments(e)
        if segs and segs[0][0] == it.id:
            out.append(e.body)
    return out


def _rescue(st, it, route: dict, salary: dict) -> None:
    """Fill gaps the segment miner leaves. Known miner failure
    (found during this migration): segments() ends an item's
    segment at the next distinct #id mention, so a RE-STOCKED
    item's STOCKED line — which names the original item first —
    loses its apply URL, and its SEGMENT STATE 'figure N' line
    carries no $ range for the salary pattern. Both values sit in
    the item's own stocking entries; take them from there."""
    bodies = _own_stocking_bodies(st, it)
    if not route.get("url"):
        for body in bodies:
            for m in _URL_RE.finditer(body):
                cand = m.group(0).rstrip(".")
                if urlparse(cand).netloc not in ("jobright.ai",):
                    route["url"] = cand
                    break
            if route.get("url"):
                break
    if salary.get("figure") is None:
        # The SEGMENT STATE bench line ("…; figure 205000") is a
        # separate entry from the STOCKED line; an item's own
        # segment in ANY entry is unambiguous, so scan those.
        for e in st.entries:
            for iid, seg in state_mod.segments(e):
                if iid != it.id:
                    continue
                m = _FIGURE_RE.search(seg)
                if m:
                    salary["figure"] = int(m.group(1).replace(",", ""))
                    return


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=None,
                    help="log path (default: the live outreach log)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sp = Spine(log_path=args.log) if args.log else Spine()
    log_path = Path(sp.log_path)
    _ev, stocked_path = stock_mod.data_paths(log_path)
    st = sp.load_state()

    existing: dict = {}
    if stocked_path.exists():
        existing = json.loads(stocked_path.read_text(encoding="utf-8"))

    written, kept, no_url = 0, 0, []
    for it in st.items.values():
        if not any(e[2] == "stocked" for e in it.events):
            continue
        if str(it.id) in existing:
            kept += 1
            continue
        route, salary = sp._route_and_salary(st, it)
        _rescue(st, it, route, salary)
        url = route.get("url") or ""
        entry = {
            "item_id": it.id, "company": it.company, "role": it.role,
            "source": it.source, "url": url,
            "host": urlparse(url).netloc.lower() if url else "",
            "ats": route.get("ats") or "",
            "pay": {"figure": salary.get("figure")},
            "salary_range": salary.get("published_range"),
            "backfilled": True, "stocked_at": None,
        }
        if route.get("synthesized"):
            entry["synthesized"] = True
        if not url:
            no_url.append(it.id)
        existing[str(it.id)] = entry
        written += 1

    print(f"log={log_path} stocked_file={stocked_path}")
    print(f"written={written} kept_existing={kept} no_url={no_url}")
    if not args.dry_run:
        stocked_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = stocked_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=1, sort_keys=True),
                       encoding="utf-8")
        os.replace(tmp, stocked_path)
        print("saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
