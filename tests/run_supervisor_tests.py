#!/usr/bin/env python3
"""Supervisor tests — worker supervision (the user, Nov 6, 2026).

The supervisor owns the hand-off between worker legs: liveness is a
HEARTBEAT fact, and the launch decision + claim lock live in code.

Coverage:
  (a) friction set -> FRICTION_STOP, whatever the heartbeat says.
      (Scope-less status dicts — the pre-Nov-7 shape — keep this
      meaning: friction with no scope info is a full stop.)
  (a2) friction with scope "linkedin" (the user, Nov 7, 2026: "when
      LinkedIn stopped stocking, use jobright") -> JOBRIGHT_ONLY
      with launch slots, never FRICTION_STOP; scope "all" stays
      FRICTION_STOP; JOBRIGHT_ONLY still yields to CLOSED and
      COMPLETE and to filled slots (WORKER_ALIVE).
  (b) window closed -> CLOSED.  (c) target reached -> COMPLETE.
  (d) fresh heartbeat -> WORKER_ALIVE (slow is not stuck).
  (e) no heartbeat, no claim -> LAUNCH.
  (f) stale heartbeat (past the stale threshold) -> LAUNCH.
  (g) fresh launch claim, claimed worker not heartbeat yet ->
      CLAIM_PENDING (never double-start).
  (h) expired launch claim -> LAUNCH (a died launch self-heals).
  (i) heartbeat from the claimed job -> not CLAIM_PENDING.
  (j) heartbeat_age_minutes: another window's heartbeat, a missing
      stamp, and a bad stamp all read as None.
  (k) stall_check reads the same heartbeat file: fresh -> usable age,
      wrong window -> None.
  (l) ONE APPLICATION PER WORKER: a fresh but ENDED heartbeat (the
      worker's tombstone) -> LAUNCH at any age, never WORKER_ALIVE;
      an ended heartbeat under an unexpired claim for the SAME job
      still launches (the claim was for the leg that just ended);
      stall_check.heartbeat_state reports the ended flag.
  (q) PROGRESS-BASED LIVENESS (the user, Nov 10, 2026 — freeze fixes
      1+2+4): a heartbeat-dark worker whose bridged browser task
      is still progressing counts live and fills its slot; a
      completed/silent/unbridged task, a stale bridge check, or an
      ended worker falls back to the heartbeat rules; the bridge
      record normalizes task ids; the template carries the
      --browser-task recording discipline and the wall-clock
      browser-task bound.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "checks"))
import stall_check  # noqa: E402
import state as state_mod  # noqa: E402
import supervisor  # noqa: E402

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name
          + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


NOW = datetime(2026, 11, 6, 12, 0, tzinfo=state_mod.CT)
RULES = {"supervisor": {"heartbeat_stale_minutes": 20,
                        "launch_claim_ttl_minutes": 15}}


def status(verified=10, friction=False, closes="2026-11-07T08:23:00-06:00",
           friction_scope="ABSENT"):
    s = {"window": {"date": "2026-11-06", "closes": closes},
         "targets": {"linkedin": 40, "jobright": 20, "total": 60},
         "verified_total": verified,
         "verified_counts": {"LINKEDIN": 6, "JOBRIGHT": 4},
         "bench": [], "staged": [], "captcha": [], "limbo": [],
         "friction": friction}
    if friction_scope != "ABSENT":
        s["friction_scope"] = friction_scope
    return s


def hb(minutes_ago, run="worker-a", window="2026-11-06", ended=False):
    d = {"run": run, "window": window,
         "ts": (NOW - timedelta(minutes=minutes_ago)).isoformat()}
    if ended:
        d["ended"] = True
    return d


def claim(minutes_ago, job="worker-b"):
    return {"launch_claim": {"job": job,
                             "ts": (NOW - timedelta(
                                 minutes=minutes_ago)).isoformat()}}


def main() -> int:
    v = supervisor.verdict_for
    check("a friction -> FRICTION_STOP",
          v(status(friction=True), RULES, NOW, hb(1), {})["verdict"]
          == "FRICTION_STOP")
    _jo = v(status(friction=True, friction_scope="linkedin"),
            RULES, NOW, {}, {})
    check("a2 linkedin-scoped friction -> JOBRIGHT_ONLY launch",
          _jo["verdict"] == "JOBRIGHT_ONLY"
          and _jo.get("launch_slots", 0) >= 1
          and _jo.get("jobright_only") is True,
          str(_jo.get("verdict")))
    check("a2 all-scoped friction -> FRICTION_STOP",
          v(status(friction=True, friction_scope="all"),
            RULES, NOW, {}, {})["verdict"] == "FRICTION_STOP")
    check("a2 jobright_only yields to a closed window",
          v(status(friction=True, friction_scope="linkedin"),
            RULES, datetime(2026, 11, 7, 9, 0, tzinfo=state_mod.CT),
            {}, {})["verdict"] == "CLOSED")
    check("a2 jobright_only yields to filled slots",
          v(status(friction=True, friction_scope="linkedin"),
            RULES, NOW, hb(1), {})["verdict"] == "WORKER_ALIVE")
    check("b closed window -> CLOSED",
          v(status(), RULES,
            datetime(2026, 11, 7, 9, 0, tzinfo=state_mod.CT),
            {}, {})["verdict"] == "CLOSED")
    check("c target reached -> COMPLETE",
          v(status(verified=60), RULES, NOW, {}, {})["verdict"]
          == "COMPLETE")
    check("d fresh heartbeat -> WORKER_ALIVE",
          v(status(), RULES, NOW, hb(3), {})["verdict"]
          == "WORKER_ALIVE")
    check("e no heartbeat, no claim -> LAUNCH",
          v(status(), RULES, NOW, {}, {})["verdict"] == "LAUNCH")
    check("f stale heartbeat -> LAUNCH",
          v(status(), RULES, NOW, hb(45), {})["verdict"] == "LAUNCH")
    check("g fresh claim -> CLAIM_PENDING",
          v(status(), RULES, NOW, {}, claim(2))["verdict"]
          == "CLAIM_PENDING")
    check("h expired claim -> LAUNCH",
          v(status(), RULES, NOW, {}, claim(30))["verdict"] == "LAUNCH")
    check("i claimed job heartbeat -> WORKER_ALIVE",
          v(status(), RULES, NOW, hb(1, run="worker-b"),
            claim(2))["verdict"] == "WORKER_ALIVE")
    age = supervisor.heartbeat_age_minutes
    check("j1 other window -> None",
          age(hb(5, window="2026-11-05"), "2026-11-06", NOW) is None)
    check("j2 missing stamp -> None",
          age({"run": "x", "window": "2026-11-06"}, "2026-11-06",
              NOW) is None)
    check("j3 bad stamp -> None",
          age({"run": "x", "window": "2026-11-06", "ts": "junk"},
              "2026-11-06", NOW) is None)
    check("j4 age value",
          abs(age(hb(10), "2026-11-06", NOW) - 10.0) < 0.01)

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "heartbeat.json"
        old = stall_check.HEARTBEAT
        old_dir = stall_check.HEARTBEATS_DIR
        stall_check.HEARTBEAT = p
        # Parallel workers (Nov 6, 2026): heartbeat_state also reads
        # the per-run directory — point it at an empty temp dir so
        # these checks see only the fixture file.
        stall_check.HEARTBEATS_DIR = Path(td) / "heartbeats"
        try:
            check("k1 no file -> None",
                  stall_check.heartbeat_age_minutes(
                      "2026-11-06", NOW) is None)
            p.write_text('{"run": "w", "window": "2026-11-06", '
                         '"ts": "%s"}' % hb(7)["ts"], encoding="utf-8")
            got = stall_check.heartbeat_age_minutes("2026-11-06", NOW)
            check("k2 fresh file -> age", got is not None
                  and abs(got - 7.0) < 0.01, f"got {got}")
            check("k3 wrong window -> None",
                  stall_check.heartbeat_age_minutes(
                      "2026-11-05", NOW) is None)
            p.write_text('{"run": "w", "window": "2026-11-06", '
                         '"ended": true, "ts": "%s"}' % hb(2)["ts"],
                         encoding="utf-8")
            age2, ended2 = stall_check.heartbeat_state("2026-11-06",
                                                       NOW)
            check("l3 stall heartbeat_state reports ended",
                  ended2 is True and age2 is not None
                  and abs(age2 - 2.0) < 0.01,
                  f"got {(age2, ended2)}")
        finally:
            stall_check.HEARTBEAT = old
            stall_check.HEARTBEATS_DIR = old_dir

    check("l1 fresh but ended heartbeat -> LAUNCH",
          v(status(), RULES, NOW, hb(1, ended=True), {})["verdict"]
          == "LAUNCH")
    check("l2 ended heartbeat carries the reason",
          "ended cleanly" in v(status(), RULES, NOW,
                               hb(1, ended=True), {})["reason"])
    check("l4 ended leg under its own claim -> LAUNCH (not pending)",
          v(status(), RULES, NOW, hb(1, run="worker-b", ended=True),
            claim(2))["verdict"] == "LAUNCH")

    # Back-to-back workers (the user, Nov 6, 2026 — reversal of the
    # one-application rule the same evening, on pace): the real
    # config carries the reversal, and the worker template tells
    # the worker to take the next order after every record
    # instead of ending after one application.
    import pathlib as _pls
    import yaml as _yaml
    _real_rules = _yaml.safe_load(_pls.Path(
        __file__).resolve().parent.parent.joinpath(
        "config", "rules.yaml").read_text())
    _sup_cfg = _real_rules.get("supervisor") or {}
    check("l5 back-to-back in config (one-app rule reversed)",
          _sup_cfg.get("one_application_per_worker") is False
          and _sup_cfg.get("worker_runs_back_to_back") is True
          and _sup_cfg.get("max_parallel_workers") == 3)
    _tpl = _pls.Path(__file__).resolve().parent.parent.joinpath(
        "worker_template.md").read_text()
    check("l6 template runs back to back (no one-app leg)",
          "work through applications back to back" in _tpl
          and "TAKE IT and go back to step 3" in _tpl
          and "ONE application, then end" not in _tpl)

    # Parallel workers (the user, Nov 6, 2026: "Run 3 workers in
    # parallel"): the verdict counts live heartbeats + unexpired
    # claims against max_parallel_workers and returns launch_slots.
    RULES3 = {"supervisor": {"heartbeat_stale_minutes": 20,
                             "launch_claim_ttl_minutes": 15,
                             "max_parallel_workers": 3}}

    def claims3(*jobs):
        return {"launch_claims": {
            j: {"ts": (NOW - timedelta(minutes=2)).isoformat()}
            for j in jobs}}

    _p1 = v(status(), RULES3, NOW, [hb(2, run="worker-a")], {})
    check("p1 one live of three -> LAUNCH with 2 slots",
          _p1["verdict"] == "LAUNCH" and _p1["launch_slots"] == 2
          and _p1["live_workers"] == ["worker-a"])
    check("p2 three live -> WORKER_ALIVE",
          v(status(), RULES3, NOW,
            [hb(2, run="worker-a"), hb(3, run="worker-b"),
             hb(4, run="worker-c")], {})["verdict"] == "WORKER_ALIVE")
    _p3 = v(status(), RULES3, NOW, [hb(2, run="worker-a")],
            claims3("worker-d"))
    check("p3 one live + one pending claim -> LAUNCH with 1 slot",
          _p3["verdict"] == "LAUNCH" and _p3["launch_slots"] == 1)
    check("p4 three pending claims, none live -> CLAIM_PENDING",
          v(status(), RULES3, NOW, [],
            claims3("worker-d", "worker-e", "worker-f"))["verdict"]
          == "CLAIM_PENDING")
    _p5 = v(status(), RULES3, NOW,
            [hb(2, run="worker-a"), hb(3, run="worker-b"),
             hb(1, run="worker-c", ended=True)], {})
    check("p5 two live + one ended -> LAUNCH with 1 slot",
          _p5["verdict"] == "LAUNCH" and _p5["launch_slots"] == 1)
    check("p6 claim for a worker that already heartbeat is not "
          "pending",
          v(status(), RULES3, NOW, [hb(2, run="worker-a")],
            claims3("worker-a"))["launch_slots"] == 2)

    # Progress-based liveness (the user, Nov 10, 2026 — freeze
    # investigation fix 2): a heartbeat-dark worker whose browser
    # task is still progressing counts LIVE — it fills its slot
    # (fix 4 slot accounting) and stall_check's shared judgment
    # (supervisor.worker_liveness) agrees. A task that stopped
    # progressing, finished, or was never bridged falls back to
    # the heartbeat rules.
    import browser_progress as _bp

    RULES_P1 = {"supervisor": {"heartbeat_stale_minutes": 20,
                               "launch_claim_ttl_minutes": 15,
                               "max_parallel_workers": 1,
                               "browser_progress_stale_minutes": 15,
                               "browser_progress_check_fresh_minutes":
                               40}}
    RULES_P3 = {"supervisor": dict(RULES_P1["supervisor"],
                                   max_parallel_workers=3)}

    def hb_task(minutes_ago, task, run="worker-a", ended=False):
        d = hb(minutes_ago, run=run, ended=ended)
        d["browser_task"] = task
        return d

    def prog_entry(status_="running", checked_ago=5, gap=3):
        checked = NOW - timedelta(minutes=checked_ago)
        return {"status": status_,
                "checked_at": checked.isoformat(),
                "last_progress_at":
                (checked - timedelta(minutes=gap)).isoformat(),
                "step_count": 9}

    PROG_OK = {"task-1": prog_entry()}
    _q1 = v(status(), RULES_P1, NOW, hb_task(60, "task-1"), {},
            PROG_OK)
    check("q1 heartbeat-dark + task progressing -> WORKER_ALIVE",
          _q1["verdict"] == "WORKER_ALIVE"
          and _q1["live_workers"] == ["worker-a"]
          and _q1["progress_alive_workers"] == ["worker-a"]
          and _q1["heartbeats"][0]["live_via"] == "browser_progress",
          str(_q1.get("verdict")))
    check("q2 task completed -> not progress-alive -> LAUNCH",
          v(status(), RULES_P1, NOW, hb_task(60, "task-1"), {},
            {"task-1": prog_entry(status_="completed")})["verdict"]
          == "LAUNCH")
    check("q3 bridge check too old -> proves nothing -> LAUNCH",
          v(status(), RULES_P1, NOW, hb_task(60, "task-1"), {},
            {"task-1": prog_entry(checked_ago=50)})["verdict"]
          == "LAUNCH")
    check("q4 task not progressed within stale window -> LAUNCH",
          v(status(), RULES_P1, NOW, hb_task(60, "task-1"), {},
            {"task-1": prog_entry(gap=30)})["verdict"] == "LAUNCH")
    check("q5 no bridge data at all -> heartbeat rules -> LAUNCH",
          v(status(), RULES_P1, NOW, hb_task(60, "task-1"), {},
            None)["verdict"] == "LAUNCH")
    _q6 = v(status(), RULES_P3, NOW,
            [hb(2, run="worker-a"),
             hb_task(70, "task-1", run="worker-b")], {}, PROG_OK)
    check("q6 progress-alive worker fills its slot (fix 4)",
          _q6["verdict"] == "LAUNCH" and _q6["launch_slots"] == 1
          and _q6["live_workers"] == ["worker-a", "worker-b"],
          str(_q6.get("launch_slots")))
    check("q7 browser-task: prefix on heartbeat normalizes",
          v(status(), RULES_P1, NOW,
            hb_task(60, "browser-task:task-1"), {},
            PROG_OK)["verdict"] == "WORKER_ALIVE")
    check("q8 ended worker with progressing task is NOT live",
          v(status(), RULES_P1, NOW,
            hb_task(60, "task-1", ended=True), {},
            PROG_OK)["verdict"] == "LAUNCH")
    _lv = supervisor.worker_liveness(
        [hb_task(80, "task-1")], "2026-11-06", NOW, RULES_P1,
        PROG_OK)
    check("q9 shared liveness: progressing task -> live",
          len(_lv) == 1 and _lv[0]["live"] is True
          and _lv[0]["progress_alive"] is True)
    _lv2 = supervisor.worker_liveness(
        [hb_task(80, "task-1")], "2026-11-06", NOW, RULES_P1,
        {"task-1": prog_entry(gap=45)})
    check("q10 shared liveness: silent task -> not live",
          len(_lv2) == 1 and _lv2[0]["live"] is False
          and _lv2[0]["progress_alive"] is False)
    check("q11 task_progress_alive: no task recorded -> False",
          supervisor.task_progress_alive(hb(80), PROG_OK, NOW,
                                         RULES_P1) is False)
    _tasks = {}
    _bp.record_entry(_tasks, "browser-task:abc-123", "running",
                     "2026-11-06T11:50:00Z", 4, NOW)
    check("q12 bridge record normalizes id + parses Z stamp",
          list(_tasks) == ["abc-123"]
          and _tasks["abc-123"]["status"] == "running"
          and _tasks["abc-123"]["step_count"] == 4)
    check("q13 bridge parse_ts: postgres text form",
          _bp.parse_ts("2026-11-10 20:59:24-06") is not None
          and _bp.parse_ts("junk") is None
          and _bp.parse_ts(None) is None)

    # Browser-task bound discipline (fix 1) + task-id recording
    # (fix 2) live in the worker template.
    check("q14 template: record task id + wall-clock bound",
          "--browser-task" in _tpl and "Return by" in _tpl
          and "browser_task_bound" in _tpl
          and "ONE source" in _tpl)

    # HARD CEILING on progress-based liveness (the user, Nov 10, 2026,
    # later same evening): a browser task older than
    # browser_task_hard_ceiling_minutes no longer makes its worker
    # live, no matter how recently it progressed — the worker
    # falls back to the heartbeat rules, visibly flagged. The age
    # comes from the bridge entry's started_at (the task's muse.db
    # created_at); no recorded start = the ceiling cannot apply.
    RULES_C = {"supervisor": dict(
        RULES_P1["supervisor"],
        browser_task_hard_ceiling_minutes=120)}

    def prog_started(started_ago, **kw):
        e = prog_entry(**kw)
        e["started_at"] = (NOW - timedelta(
            minutes=started_ago)).isoformat()
        return e

    _q15 = v(status(), RULES_C, NOW, hb_task(150, "task-1"), {},
             {"task-1": prog_started(150)})
    check("q15 task progressing but 150 min old -> ceiling: LAUNCH",
          _q15["verdict"] == "LAUNCH"
          and _q15["progress_alive_workers"] == []
          and _q15["ceiling_expired_workers"] == ["worker-a"]
          and _q15["heartbeats"][0]["ceiling_expired"] is True
          and _q15["heartbeats"][0]["live_via"] is None,
          str(_q15.get("verdict")))
    _q16 = v(status(), RULES_C, NOW, hb_task(60, "task-1"), {},
             {"task-1": prog_started(60)})
    check("q16 task progressing, 60 min old -> still progress-alive",
          _q16["verdict"] == "WORKER_ALIVE"
          and _q16["progress_alive_workers"] == ["worker-a"]
          and _q16["ceiling_expired_workers"] == []
          and _q16["heartbeats"][0]["browser_task_age_minutes"]
          == 60.0,
          str(_q16.get("verdict")))
    check("q17 no started_at on entry -> ceiling cannot apply",
          v(status(), RULES_C, NOW, hb_task(60, "task-1"), {},
            PROG_OK)["verdict"] == "WORKER_ALIVE")
    _lv3 = supervisor.worker_liveness(
        [hb_task(150, "task-1")], "2026-11-06", NOW, RULES_C,
        {"task-1": prog_started(150)})
    check("q18 shared liveness: ceiling-expired -> heartbeat rules",
          len(_lv3) == 1 and _lv3[0]["live"] is False
          and _lv3[0]["progress_alive"] is False
          and _lv3[0]["ceiling_expired"] is True)
    _tasks2 = {}
    _bp.record_entry(_tasks2, "task-9", "running",
                     "2026-11-06T11:50:00Z", 4, NOW,
                     started_at="2026-11-06T10:00:00Z")
    _bp.record_entry(_tasks2, "task-9", "running",
                     "2026-11-06T11:55:00Z", 5, NOW)
    _bp.record_entry(_tasks2, "task-9", "running",
                     "2026-11-06T11:58:00Z", 6, NOW,
                     started_at="2026-11-06T10:30:00Z")
    check("q19 bridge record: started_at kept, earliest wins",
          _tasks2["task-9"]["started_at"]
          == "2026-11-06T10:00:00+00:00"
          and _tasks2["task-9"]["step_count"] == 6)

    if FAILS:
        print(f"\n{len(FAILS)} FAILURE(S): {FAILS}")
        return 1
    print("\nALL SUPERVISOR TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
