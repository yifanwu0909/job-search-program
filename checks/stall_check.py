"""stall_check.py — the stall detector (the user, Nov 4, 2026: "Always stop it.
Burn this into code." / "Try to build it into the code").

The CODE decides whether the batch is stalled; the watcher agent only
carries out the verdict (the tower/plane split, same as the rest of the
program).

HEARTBEAT FIRST (the user, Nov 6, 2026 — supervisor fix): when a worker
heartbeat exists for the open window (state/heartbeat.json, written by
program/supervisor.py), the heartbeat is the liveness fact and the
counts are not consulted:
  age < supervisor.heartbeat_stale_minutes (45) -> ALIVE. A worker
    inside long browser tasks or pacing gaps is slow, not stuck —
    frozen counts earn no alarm and no stop.
  age >= guardian.stall_span_minutes (60) -> STALL: the worker has
    not heartbeat for a full span; it is hung or gone.
  between the two -> QUIET (gray zone; the supervisor's launch lock
    and the guardian's cron check govern any relaunch).

PROGRESS-BASED LIVENESS (the user, Nov 10, 2026 — freeze investigation
fix 2): a worker waiting on a browser task cannot heartbeat at all
(delegating ends its turn), so a heartbeat-dark worker whose
browser task is still progressing counts ALIVE too. The judgment
is shared code — supervisor.worker_liveness over the heartbeats
plus the browser-progress bridge file (state/browser_progress
.json, refreshed from muse.db by the watcher/guardian via
program/browser_progress.py): any worker live by EITHER signal
(fresh heartbeat, or a "running" browser task that progressed
within supervisor.browser_progress_stale_minutes of a fresh
bridge check) makes the batch ALIVE. Only when NO worker is live
by either signal do the heartbeat-age rules above decide — so a
worker whose browser task has also stopped progressing still
reads STALL on the full span, exactly as before. HARD CEILING
(the user, Nov 10, 2026, later same evening): a browser task older
than supervisor.browser_task_hard_ceiling_minutes (120) no
longer counts as progress at all — its worker is exposed in the
verdict's ceiling_expired_workers and judged on its heartbeat
alone, so a worker riding one endless task can still STALL.

FALLBACK (no heartbeat for the window — a worker that predates the
supervisor): the original count rule. A stall is: the window is open,
the verified target is unmet, and NOTHING has advanced — verified
count, event-book lines, and log progress entries all frozen — for at
least the span in rules.yaml (guardian.stall_span_minutes, 60).

Progress lines = outreach-log entry lines ("- [...") excluding the
watchers' own noise (guardian lines, shadow lines, email-scan summaries),
so the detectors can never fake progress for each other.

State: program/state/stall_state.json holds the last snapshot
{window, frozen_since, verified, events, progress_lines}. A pass that sees
advancement re-baselines the snapshot. A STALL verdict re-arms the clock
(frozen_since = now) so a continuing freeze re-fires only after another
full span — by then the stop + relaunch should already have happened.

Usage: python3 stall_check.py
Prints ONE JSON verdict line. Exit 3 on STALL, 0 otherwise.
The verdict never stops anything itself — it has no hands. The watcher
(linkedin-spine-shadow) reads the verdict, confirms a run is in flight,
stops it, alerts the user, and triggers the guardian to relaunch.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))

import state as state_mod  # noqa: E402
import supervisor  # noqa: E402
from pipeline import Spine  # noqa: E402

SNAP = BASE / "state" / "stall_state.json"
# Noise: entries that land on a schedule whether or not the batch is
# moving (audit fix, Nov 4, 2026 — the first version counted inbox-sweep
# summaries as progress, which could mask a stall for hours).
NOISE = ("Guardian", "EMAIL SCAN", "email scan", "application email scan",
         "inbox sweep", "Inbox sweep", "Inbox Sweep", "SHADOW",
         "shadow pass", "AUDIT", "RULE CHANGE", "STANDING RULE")
# Progress counts ONLY batch-work dispositions: an entry that stocks,
# claims, submits, parks, skips, verifies, or limbos a real item.
BATCH_MARKERS = ("SUBMITTED", "STAGED FOR", "STOCKED", "AWAITING CAPTCHA",
                 "IN LIMBO", "SKIPPED —", "EMAIL-VERIFIED", "CLAIM —",
                 "DISPOSITIONED", "BATCH CLOSED")


def progress_lines(log_path: str) -> int:
    n = 0
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("- ["):
                continue
            if any(w in line for w in NOISE):
                continue
            if any(m in line for m in BATCH_MARKERS):
                n += 1
    return n


HEARTBEAT = BASE / "state" / "heartbeat.json"
HEARTBEATS_DIR = BASE / "state" / "heartbeats"


def _all_heartbeats() -> list:
    """Every worker heartbeat on file: per-run files under
    state/heartbeats/ (parallel workers, Nov 6, 2026) plus the
    legacy single file when its run has no per-run file."""
    out, seen = [], set()
    try:
        if HEARTBEATS_DIR.exists():
            for p in sorted(HEARTBEATS_DIR.glob("*.json")):
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if d.get("run"):
                    out.append(d)
                    seen.add(d["run"])
    except Exception:
        pass
    try:
        d = json.loads(HEARTBEAT.read_text(encoding="utf-8"))
        if d.get("run") and d["run"] not in seen:
            out.append(d)
    except Exception:
        pass
    return out


def heartbeat_age_minutes(window_date: str, now: datetime) -> float | None:
    """Age of the freshest usable worker heartbeat in minutes, or
    None when there is none for this window."""
    age, _ended = heartbeat_state(window_date, now)
    return age


def heartbeat_state(window_date: str, now: datetime):
    """(age_minutes | None, ended) across ALL worker heartbeats for
    this window (parallel workers each carry their own file): the
    freshest NON-ended age when any worker is still running (its
    freshness is judged by the caller against the stale span);
    (freshest age, True) when every heartbeat on file is a clean
    tombstone (supervisor.py done) — a clean end is never a stall;
    (None, False) when no heartbeat exists for this window."""
    ages_live, ages_ended = [], []
    for hb in _all_heartbeats():
        if hb.get("window") != window_date or not hb.get("ts"):
            continue
        try:
            ts = datetime.fromisoformat(hb["ts"])
        except Exception:
            continue
        age = (now - ts).total_seconds() / 60.0
        (ages_ended if hb.get("ended") else ages_live).append(age)
    if ages_live:
        return min(ages_live), False
    if ages_ended:
        return min(ages_ended), True
    return None, False


def main() -> int:
    rules = yaml.safe_load(open(BASE / "config" / "rules.yaml"))
    span_min = int((rules.get("guardian") or {}).get("stall_span_minutes", 60))
    hb_stale_min = float((rules.get("supervisor") or {}).get(
        "heartbeat_stale_minutes", 20))
    targets = rules["window"]["targets"]

    sp = Spine()
    status = sp.status()
    wdate = status["window"]["date"]
    verified = status["verified_total"]
    events_n = sum(1 for _ in open(sp.events_path, encoding="utf-8"))
    prog = progress_lines(sp.log_path)
    now = datetime.now(state_mod.CT)

    snap = {}
    if SNAP.exists():
        snap = json.loads(SNAP.read_text(encoding="utf-8"))

    def save(frozen_since: datetime):
        SNAP.parent.mkdir(exist_ok=True)
        SNAP.write_text(json.dumps({
            "window": wdate, "frozen_since": frozen_since.isoformat(),
            "verified": verified, "events": events_n,
            "progress_lines": prog,
        }, indent=1), encoding="utf-8")

    base = {"window": wdate, "verified": verified,
            "target": targets["total"], "span_minutes": span_min,
            "events": events_n, "progress_lines": prog}

    if snap.get("window") != wdate:
        save(now)
        print(json.dumps({**base, "verdict": "BASELINE",
                          "detail": "new window or first pass — snapshot set"}))
        return 0
    if verified >= targets["total"]:
        save(now)
        print(json.dumps({**base, "verdict": "COMPLETE",
                          "detail": "window target reached"}))
        return 0

    # Liveness per worker, shared with the supervisor verdict
    # (Nov 10, 2026 fix 2): a worker counts live on a fresh
    # heartbeat OR on a still-progressing browser task.
    states = supervisor.worker_liveness(
        _all_heartbeats(), wdate, now, rules,
        supervisor.load_browser_progress())
    if states:
        save(now)  # keep the fallback snapshot fresh either way
        non_ended = [s for s in states if not s["ended"]]
        hb_age = min(s["age"] for s in (non_ended or states))
        hb_ended = not non_ended
        prog_workers = sorted(s["run"] for s in states
                              if s["progress_alive"])
        ceiling_workers = sorted(s["run"] for s in states
                                 if s["ceiling_expired"])
        hb_base = {**base, "heartbeat_age_minutes": round(hb_age, 1),
                   "heartbeat_stale_minutes": hb_stale_min,
                   "progress_alive_workers": prog_workers,
                   "ceiling_expired_workers": ceiling_workers}
        if hb_ended:
            print(json.dumps({**hb_base, "verdict": "ENDED",
                              "detail": "worker run ended "
                                        "cleanly — the supervisor "
                                        "starts the next worker; "
                                        "not a stall"}))
            return 0
        live_states = [s for s in states if s["live"]]
        if live_states:
            via_progress = any(
                s["progress_alive"] and s["age"] >= hb_stale_min
                for s in live_states)
            print(json.dumps({**hb_base, "verdict": "ALIVE",
                              "detail": ("worker heartbeat-dark but "
                                         "its browser task is still "
                                         "progressing — slow is not "
                                         "stuck; counts not "
                                         "consulted (Nov 10, 2026 "
                                         "fix 2)"
                                         if via_progress else
                                         "worker heartbeat fresh — "
                                         "slow is not stuck; counts "
                                         "not consulted")}))
            return 0
        if hb_age >= span_min:
            print(json.dumps({**hb_base, "verdict": "STALL",
                              "frozen_minutes": int(hb_age),
                              "detail": "no worker heartbeat for the "
                                        "full stall span — the worker "
                                        "is hung or gone"}))
            return 3
        print(json.dumps({**hb_base, "verdict": "QUIET",
                          "frozen_minutes": int(hb_age),
                          "detail": "heartbeat in the gray zone "
                                    "(stale but under the stall span)"}))
        return 0

    advanced = (verified > snap["verified"] or events_n > snap["events"]
                or prog > snap["progress_lines"])
    if advanced:
        save(now)
        print(json.dumps({**base, "verdict": "PROGRESS",
                          "detail": "counts advanced since the last snapshot"}))
        return 0

    frozen_since = datetime.fromisoformat(snap["frozen_since"])
    frozen_min = int((now - frozen_since).total_seconds() // 60)
    if frozen_min >= span_min:
        save(now)  # re-arm: a continuing freeze re-fires after another span
        print(json.dumps({**base, "verdict": "STALL",
                          "frozen_minutes": frozen_min,
                          "frozen_since": snap["frozen_since"],
                          "detail": "no advancement in verified, events, or "
                                    "log progress entries for the full span"}))
        return 3
    print(json.dumps({**base, "verdict": "QUIET",
                      "frozen_minutes": frozen_min,
                      "detail": "frozen, but under the stall span"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
