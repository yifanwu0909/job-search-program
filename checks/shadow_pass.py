#!/usr/bin/env python3
"""shadow_pass.py — ONE shadow-mode pass of the application program.

Shadow mode (the user, Nov 4, 2026: "Run shadow mode now"): the tower computes
alongside the real prose runs and touches NOTHING. Each pass:
  (a) tower status for the current window (Spine.status — read-only);
  (b) folds any NEW prose dispositions into
      hidden_files/shadow/shadow-events.jsonl, using the same derivation
      as tests/backfill_events.py (verified -> submitted+verified events,
      staged -> staged with `why` mapped from the step text, captcha ->
      captcha with no why, limbo -> limbo), incremental against the
      watermark in shadow-state.json (prose-log line count folded + the
      per-item dispositions already emitted for the window);
  (c) state-check: prose state vs the shadow event stream (divergences);
  (d) the tower's next pick (Spine.next_order — read-only);
  (e) one entry appended to hidden_files/shadow/shadow-log.md.

HARD RULES: never calls record / clear-friction; never writes the live
outreach log; never writes program/events.jsonl; the only files written
are inside hidden_files/shadow/. Prints a JSON summary on stdout;
"counting_divergence" is true when the shadow-events-folded VERIFIED
total for the open window differs from the prose VERIFIED total.

Run: python3 program/shadow_pass.py

DRIVER MODE (the user, Nov 4, 2026 — the program is live; the watcher job was
rebuilt fresh as a driver-mode checker):
  python3 program/shadow_pass.py --driver
    One driver-mode check: tower status for the open window + state-check
    of the prose log against the LIVE program/events.jsonl + ONE entry in
    hidden_files/shadow/shadow-log.md labeled as a driver-mode check.
    Read-only against the live log and the live events file.
    DIVERGENCE ALERT RULE (the user, Nov 5, 2026): state_check classifies every
    divergence in code (pipeline.classify_divergences) as benign or deep.
    The JSON summary carries "deep_divergence" / "deep_divergences" /
    "benign_divergences"; the watcher messages the user only when a counting
    divergence includes at least one DEEP item. Benign divergences
    (catch-up re-mentions, carried prose-only notes, presence-only park
    mismatches) are recorded here and in the morning report, never
    messaged.
  python3 program/shadow_pass.py --reconcile
    ONE-TIME reconciliation (run by hand at the driver-mode cutover of the
    rebuilt watcher, never by the cron job): outcomes recorded in prose
    after the 5:44 PM CT events backfill — by runs launched before
    go-live, whose bodies predate spine.py record — have no events yet.
    This folds exactly those items' current prose dispositions into the
    LIVE program/events.jsonl using the same derivation as the backfill
    (desired_events), lists the reconciled items in shadow-log.md, and
    re-runs state-check so the driver baseline can be verified.
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

import events as events_mod  # noqa: E402
import state as state_mod  # noqa: E402
from pipeline import Spine  # noqa: E402

GOAL = BASE.parent
SHADOW = GOAL / "hidden_files" / "shadow"
EVENTS = SHADOW / "shadow-events.jsonl"
SLOG = SHADOW / "shadow-log.md"
SSTATE = SHADOW / "shadow-state.json"
CT = state_mod.CT


def _load_sstate() -> dict:
    if SSTATE.exists():
        try:
            return json.loads(SSTATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"window": None, "log_lines_folded": 0, "passes": 0,
            "emitted": {}, "divergences_total": 0}


def desired_events(st, ws, w) -> dict:
    """item_id -> (disposition, [append_event kwargs]) — the backfill
    derivation (tests/backfill_events.py), generalized to the window the
    parser says is current, plus limbo (state-check compares it too)."""
    out: dict[int, tuple[str, list[dict]]] = {}
    source_of: dict[int, str] = {}
    for src, items in ws["verified_by_source"].items():
        for it in items:
            source_of[it.id] = (src or "").upper()
    for it in ws["verified"]:
        sub = it.submitted_event
        ts = sub[1].isoformat() if sub and sub[1] else w.open_dt.isoformat()
        src = source_of.get(it.id) or None
        out[it.id] = ("verified", [
            {"etype": "submitted", "item": it.id, "src": src,
             "win": w.date, "ts": ts},
            {"etype": "verified", "item": it.id, "src": src,
             "win": w.date, "ts": ts}])
    entry_by_line = {e.line_no: e for e in st.entries}
    for it in ws["staged"]:
        if it.id in out:
            continue
        staged_ev = it.events_of("staged")
        last = staged_ev[-1] if staged_ev else None
        ts = last[1].isoformat() if last and last[1] else w.open_dt.isoformat()
        step_text = ""
        if last is not None:
            entry = entry_by_line.get(last[0])
            seg = (dict(state_mod.segments(entry)).get(it.id, "")
                   if entry is not None else "")
            idx = seg.lower().find("step:")
            step_text = seg[idx + 5:] if idx >= 0 else (last[3] or "")
        out[it.id] = ("staged", [
            {"etype": "staged", "item": it.id,
             "src": (it.source or "").upper() or None,
             "win": w.date, "ts": ts,
             "why": events_mod.why_code(step_text)}])
    for it in ws["captcha"]:
        if it.id in out:
            continue
        cap_ev = it.events_of("captcha")
        last = cap_ev[-1] if cap_ev else None
        ts = last[1].isoformat() if last and last[1] else w.open_dt.isoformat()
        out[it.id] = ("captcha", [
            {"etype": "captcha", "item": it.id,
             "src": (it.source or "").upper() or None,
             "win": w.date, "ts": ts}])
    for it in ws["limbo"]:
        if it.id in out:
            continue
        lim_ev = it.events_of("limbo")
        last = lim_ev[-1] if lim_ev else None
        ts = last[1].isoformat() if last and last[1] else w.open_dt.isoformat()
        out[it.id] = ("limbo", [
            {"etype": "limbo", "item": it.id,
             "src": (it.source or "").upper() or None,
             "win": w.date, "ts": ts}])
    return out


def shadow_main() -> int:
    SHADOW.mkdir(parents=True, exist_ok=True)
    sp = Spine(events_path=str(EVENTS))
    sstate = _load_sstate()

    # (a) tower status (read-only against the live log)
    status = sp.status()
    wdate = status["window"]["date"]
    counts = status["verified_counts"]
    li = counts.get("LINKEDIN", 0)
    jr = counts.get("JOBRIGHT", 0)

    # (b) incremental fold of new prose dispositions into shadow events
    st = sp.load_state()
    w = st.window_for(wdate)
    ws = st.window_status(wdate)
    if sstate.get("window") != wdate:
        sstate["emitted"] = {}
        sstate["log_lines_folded"] = 0
    emitted: dict = sstate.get("emitted") or {}
    desired = desired_events(st, ws, w)
    folded = 0
    for iid in sorted(desired):
        disp, evs = desired[iid]
        if emitted.get(str(iid)) == disp:
            continue
        for kw in evs:
            events_mod.append_event(EVENTS, **kw)
            folded += 1
        emitted[str(iid)] = disp

    # (c) state-check: prose vs shadow event stream
    chk = sp.state_check(wdate)
    divergences = chk["divergences"]
    counting_div = (chk["prose"]["verified_total"]
                    != chk["events"]["verified_total"])

    # (d) tower's next pick (read-only)
    nxt = sp.next_order(wdate)
    if nxt.get("status") == "work_order":
        wo = nxt["work_order"]
        pick = (f"work order — #{wo['item_id']} {wo['company']} "
                f"({wo['source']})")
    else:
        pick = f"{nxt.get('status')}: {nxt.get('reason', '')}"

    # (e) shadow-log entry + watermark update
    now = datetime.now(CT)
    sstate["window"] = wdate
    sstate["passes"] = int(sstate.get("passes", 0)) + 1
    lines_before = int(sstate.get("log_lines_folded", 0))
    sstate["log_lines_folded"] = status["log_lines"]
    sstate["emitted"] = emitted
    sstate["divergences_total"] = (int(sstate.get("divergences_total", 0))
                                   + len(divergences))
    sstate["last_pass_ts"] = now.isoformat()
    SSTATE.write_text(json.dumps(sstate, indent=2), encoding="utf-8")

    div_text = "none"
    if divergences:
        div_text = "; ".join(
            f"#{d['item_id']} {d['company']}: prose={d['prose']} "
            f"events={d['events']}" for d in divergences)
    entry = (
        f"\n## Shadow pass #{sstate['passes']} — "
        f"{now.strftime('%Y-%m-%d %I:%M %p CT')} (window {wdate})\n"
        f"- Tower status: VERIFIED {status['verified_total']} of "
        f"{status['targets']['total']} (LinkedIn {li}/"
        f"{status['targets']['linkedin']}, Jobright {jr}/"
        f"{status['targets']['jobright']}); staged "
        f"{len(status['staged'])}; captcha {len(status['captcha'])}; "
        f"limbo {len(status['limbo'])}; bench {len(status['bench'])}; "
        f"claimed-unfinished {len(status['claimed_unfinished'])}.\n"
        f"- Folded: +{folded} events into shadow-events.jsonl "
        f"(prose log lines folded {lines_before} -> "
        f"{status['log_lines']}).\n"
        f"- State-check: prose verified {chk['prose']['verified_total']} "
        f"vs shadow-events verified {chk['events']['verified_total']}; "
        f"divergences: {div_text}.\n"
        f"- Tower next pick: {pick}.\n"
        f"- Counting divergence: "
        f"{'YES — verified counts differ' if counting_div else 'none'}.\n")
    if not SLOG.exists():
        SLOG.write_text(
            "# Shadow log — application program shadow mode\n"
            "\nOne entry per shadow pass (job linkedin-spine-shadow, "
            "every 30 min).\nThe tower computes alongside the real runs "
            "and touches nothing;\ndivergences found are recorded here "
            "and carried in the morning report.\n", encoding="utf-8")
    with SLOG.open("a", encoding="utf-8") as f:
        f.write(entry)

    print(json.dumps({
        "pass": sstate["passes"], "window": wdate,
        "verified_total": status["verified_total"],
        "verified_linkedin": li, "verified_jobright": jr,
        "staged": len(status["staged"]), "captcha": len(status["captcha"]),
        "limbo": len(status["limbo"]), "bench": len(status["bench"]),
        "events_folded": folded, "divergences": divergences,
        "counting_divergence": counting_div,
        "next_pick": pick}, indent=2))
    return 0


def _div_text(divergences) -> str:
    if not divergences:
        return "none"
    return "; ".join(
        f"#{d['item_id']} {d['company']}: prose={d['prose']} "
        f"events={d['events']}" for d in divergences)


def driver_main() -> int:
    """One driver-mode check: tower status + state-check of the prose log
    against the LIVE program/events.jsonl + one driver-labeled entry in
    shadow-log.md. Read-only: never writes the live log or live events,
    never calls record / clear-friction."""
    SHADOW.mkdir(parents=True, exist_ok=True)
    sp = Spine()  # live log + live program/events.jsonl
    sstate = _load_sstate()

    status = sp.status()
    wdate = status["window"]["date"]
    counts = status["verified_counts"]
    li = counts.get("LINKEDIN", 0)
    jr = counts.get("JOBRIGHT", 0)

    chk = sp.state_check(wdate)
    divergences = chk["divergences"]
    counting_div = (chk["prose"]["verified_total"]
                    != chk["events"]["verified_total"])

    now = datetime.now(CT)
    sstate["driver_passes"] = int(sstate.get("driver_passes", 0)) + 1
    sstate["driver_divergences_total"] = (
        int(sstate.get("driver_divergences_total", 0)) + len(divergences))
    sstate["last_driver_pass_ts"] = now.isoformat()
    SSTATE.write_text(json.dumps(sstate, indent=2), encoding="utf-8")

    entry = (
        f"\n## Driver check #{sstate['driver_passes']} — "
        f"{now.strftime('%Y-%m-%d %I:%M %p CT')} (window {wdate})\n"
        f"- Tower status: VERIFIED {status['verified_total']} of "
        f"{status['targets']['total']} (LinkedIn {li}/"
        f"{status['targets']['linkedin']}, Jobright {jr}/"
        f"{status['targets']['jobright']}); staged "
        f"{len(status['staged'])}; captcha {len(status['captcha'])}; "
        f"limbo {len(status['limbo'])}; bench {len(status['bench'])}; "
        f"claimed-unfinished {len(status['claimed_unfinished'])}.\n"
        f"- State-check (prose vs LIVE program/events.jsonl): prose "
        f"verified {chk['prose']['verified_total']} vs events verified "
        f"{chk['events']['verified_total']}; divergences: "
        f"{_div_text(divergences)}.\n"
        f"- Counting divergence: "
        f"{'YES — verified counts differ' if counting_div else 'none'}; "
        f"deep divergence: "
        f"{'YES — ' + _div_text(chk['deep_divergences']) if chk['deep_divergence'] else 'none'}; "
        f"benign divergences: {len(chk['benign_divergences'])} "
        f"(explained by the records; logged only, never messaged — "
        f"the user, Nov 5, 2026).\n")
    if not SLOG.exists():
        SLOG.write_text(
            "# Shadow log — application program shadow mode\n"
            "\nOne entry per shadow pass (job linkedin-spine-shadow, "
            "every 30 min).\nThe tower computes alongside the real runs "
            "and touches nothing;\ndivergences found are recorded here "
            "and carried in the morning report.\n", encoding="utf-8")
    with SLOG.open("a", encoding="utf-8") as f:
        f.write(entry)

    print(json.dumps({
        "mode": "driver", "pass": sstate["driver_passes"],
        "window": wdate,
        "verified_total": status["verified_total"],
        "verified_linkedin": li, "verified_jobright": jr,
        "staged": len(status["staged"]), "captcha": len(status["captcha"]),
        "limbo": len(status["limbo"]), "bench": len(status["bench"]),
        "prose_verified": chk["prose"]["verified_total"],
        "events_verified": chk["events"]["verified_total"],
        "divergences": divergences,
        "counting_divergence": counting_div,
        "deep_divergence": chk["deep_divergence"],
        "deep_divergences": chk["deep_divergences"],
        "benign_divergences": chk["benign_divergences"]}, indent=2))
    return 0


def reconcile_main() -> int:
    """ONE-TIME cutover reconciliation (by hand only; the cron job never
    runs this). Prose outcomes recorded after the 5:44 PM CT backfill —
    by runs launched before go-live — have no events. Fold exactly the
    diverging items' current prose dispositions into the LIVE events
    file (same derivation as the backfill), list them in shadow-log.md,
    and re-check. Append-only: a divergence the prose side cannot fix
    (prose absent, events present) is reported, never forced."""
    SHADOW.mkdir(parents=True, exist_ok=True)
    sp = Spine()  # live log + live program/events.jsonl
    st = sp.load_state()
    status = sp.status()
    wdate = status["window"]["date"]
    w = st.window_for(wdate)
    ws = st.window_status(wdate)
    chk_before = sp.state_check(wdate)
    desired = desired_events(st, ws, w)

    reconciled = []
    unfixable = []
    for d in chk_before["divergences"]:
        iid = d["item_id"]
        if iid not in desired:
            unfixable.append(d)
            continue
        disp, evs = desired[iid]
        for kw in evs:
            events_mod.append_event(sp.events_path, **kw)
        reconciled.append({
            "item_id": iid, "company": d["company"],
            "was": f"prose={d['prose']} events={d['events']}",
            "appended": [kw["etype"] for kw in evs]})

    chk_after = sp.state_check(wdate)
    now = datetime.now(CT)
    items_text = ("none" if not reconciled else "; ".join(
        f"#{r['item_id']} {r['company']} ({r['was']}; appended "
        f"{'+'.join(r['appended'])})" for r in reconciled))
    entry = (
        f"\n## Reconciliation — {now.strftime('%Y-%m-%d %I:%M %p CT')} "
        f"(window {wdate})\n"
        f"- One-time fold of post-backfill prose outcomes into LIVE "
        f"program/events.jsonl (runs launched before driver go-live "
        f"recorded in prose only).\n"
        f"- Reconciled items: {items_text}.\n"
        f"- State-check: divergences {len(chk_before['divergences'])} "
        f"before -> {len(chk_after['divergences'])} after; prose "
        f"verified {chk_after['prose']['verified_total']} vs events "
        f"verified {chk_after['events']['verified_total']}.\n")
    if chk_after["divergences"]:
        entry += (f"- STILL DIVERGING: "
                  f"{_div_text(chk_after['divergences'])}.\n")
    with SLOG.open("a", encoding="utf-8") as f:
        f.write(entry)

    print(json.dumps({
        "mode": "reconcile", "window": wdate,
        "reconciled": reconciled, "unfixable": unfixable,
        "divergences_before": len(chk_before["divergences"]),
        "divergences_after": chk_after["divergences"],
        "prose_verified": chk_after["prose"]["verified_total"],
        "events_verified": chk_after["events"]["verified_total"]},
        indent=2))
    return 0 if not chk_after["divergences"] else 2


def main() -> int:
    args = sys.argv[1:]
    if args == ["--driver"]:
        return driver_main()
    if args == ["--reconcile"]:
        return reconcile_main()
    if args:
        print(f"unknown arguments: {args}", file=sys.stderr)
        return 64
    return shadow_main()


if __name__ == "__main__":
    raise SystemExit(main())
