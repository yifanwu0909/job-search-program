"""supervisor.py — the worker supervisor (the user, Nov 6, 2026: the clean
fix for the stall/recovery relay noise).

The supervisor owns the hand-off between worker legs IN CODE. Workers
prove liveness with a HEARTBEAT (state/heartbeat.json, touched via
`supervisor.py heartbeat` on every work-order pull and every recorded
outcome), not with outcome counts — a worker busy inside long browser
tasks or pacing gaps is SLOW, not stuck, and earns no alarm, no stop,
and no duplicate launch.

WORKERS RUN BACK TO BACK (the user, Nov 6, 2026 — the one-application
rule was reversed the same evening for pace): a worker flies
application after application, taking the next order spine.py
record hands back after every outcome, and ends only when the
program stops it (complete / closed / friction / cutoff). When a
run ends it writes its tombstone — `supervisor.py done` marks the
heartbeat ended. An ended heartbeat means "no live worker" at ANY
age: the supervisor launches the next worker on the next pass,
with no staleness wait.

PARALLEL WORKERS (the user, Nov 6, 2026: "Run 3 workers in parallel"):
up to `max_parallel_workers` (rules.yaml `supervisor:`, currently 3)
workers fly at once. Each worker heartbeats into its OWN file
(state/heartbeats/<run>.json; the legacy state/heartbeat.json is
still written and read as a fallback), so liveness is per worker.
The verdict counts live workers + unexpired launch claims against
the cap and returns how many more may start.

PROGRESS-BASED LIVENESS (the user, Nov 10, 2026 — freeze investigation
fixes 1+2+4): a worker waiting on a browser task cannot heartbeat —
delegating via browser.browse ends its turn — so a heartbeat-only
judgment reads every long browser wait as death (Nov 10: three
false freezes, one worker stopped while it was finishing). A
worker now records the browser task it is waiting on in its
heartbeat (`heartbeat --browser-task <id>`, written immediately
after delegating, before the turn ends). The guardian and watcher
bridge that task's progress from muse.db (runtime.browser_tasks —
plain Python cannot query it) into state/browser_progress.json via
program/browser_progress.py. A non-ended worker whose browser task
is still "running" and progressed within
supervisor.browser_progress_stale_minutes of the last bridge check
(check itself fresher than
supervisor.browser_progress_check_fresh_minutes) counts LIVE,
exactly like a heartbeat-fresh worker: it fills its slot, the
verdict names it in live_workers and in progress_alive_workers,
and the guardian's Step 2a treats its in-flight run as ours. A
worker whose browser task has also stopped progressing falls back
to the 45-minute heartbeat rule unchanged. HARD CEILING (the user, Nov
10, 2026, later same evening): progress-alive stops applying once
the browser task itself is older than
supervisor.browser_task_hard_ceiling_minutes (120) — no worker
rides one browser task past ~2 hours regardless of progress; such
a worker carries ceiling_expired in the verdict and falls back to
the heartbeat rules. The age comes from the bridge entry's
started_at (the task's muse.db created_at); an entry with no
recorded start cannot be ceiling-judged.

The verdict (one JSON line):
  LAUNCH         window open, target unmet, no stopping friction, and at
                 least one worker slot free — carries launch_slots
                 (how many to start) and live_workers. The guardian
                 carries it out per slot: `claim` -> create a worker
                 from program/worker_template.md -> `launched`.
                 Exit 3.
  WORKER_ALIVE   every slot is filled by a live worker (heartbeat
                 fresh: < heartbeat_stale_minutes in rules.yaml
                 `supervisor:`). Start nothing.
  CLAIM_PENDING  slots are filled by unexpired launch claims whose
                 workers have not heartbeat yet. Start nothing —
                 someone is already starting workers.
  COMPLETE       window target reached.
  CLOSED         window closed — closeout governs, no launch.
  FRICTION_STOP  a full-stop friction flag is set (scope "all") —
                 never launch over it.
  JOBRIGHT_ONLY  LinkedIn-lane friction (scope "linkedin", the user,
                 Nov 7, 2026): LinkedIn stopped stocking, so workers
                 launch in Jobright-only mode — spine.next_order
                 serves Jobright items and Jobright discovery only.
                 Carries launch_slots / live_workers like LAUNCH.
                 Since Nov 12, 2026 (the user: Indeed added "along
                 jobright... exact same rule") the mode covers BOTH
                 external sources — Jobright + Indeed: next_order
                 serves Jobright- and Indeed-sourced items and both
                 sources' discovery. The verdict name is unchanged.
                 Since Nov 16, 2026 the mode also covers the
                 CareerOps scan (CAREEROPS), added as a third external
                 worker source alongside Jobright + Indeed (the user
                 reversed a scan-replaces-both change the same day:
                 "Use career ops as additional resources").
                 LinkedIn job alerts (the user, Nov 12, 2026) ride the same
                 mode: LINKEDIN_ALERT is its own lane — alert-sourced
                 items stay servable under LinkedIn-lane friction
                 (Easy Apply via the alert email is allowed for them;
                 "EZ applies are okay"), and next_order serves them
                 alongside the external sources.

The launch claims in state/supervisor.json (launch_claims, keyed by
job id) are the idempotency lock: two supervisor consumers can never
double-start the same slot. A claim expires after
launch_claim_ttl_minutes, so a launch that died between claim and
creation self-heals on a later pass; `clear-claim` is the manual
escape hatch when the creator knows a creation failed.

Workers never create their own continuation/recovery jobs; when a
worker leg ends, the supervisor starts the next one.

Usage:
  python3 supervisor.py verdict
  python3 supervisor.py heartbeat --run <worker job id> [--note TEXT]
      [--browser-task <browser task id>]
  python3 supervisor.py done --run <worker job id> [--note TEXT]
  python3 supervisor.py claim --job <new worker job id>
  python3 supervisor.py launched --job <worker job id>
  python3 supervisor.py clear-claim
Exit 3 on a LAUNCH verdict and on a refused claim; 0 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))

import browser_progress as bp_mod  # noqa: E402
import state as state_mod  # noqa: E402
from pipeline import Spine  # noqa: E402

HEARTBEAT = BASE / "state" / "heartbeat.json"
HEARTBEATS_DIR = BASE / "state" / "heartbeats"
SUP_STATE = BASE / "state" / "supervisor.json"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _load_heartbeats() -> list:
    """Every worker heartbeat on file: the per-run files in
    state/heartbeats/ (parallel workers, Nov 6, 2026), plus the
    legacy single state/heartbeat.json when its run has no per-run
    file (workers launched before the split)."""
    out, seen = [], set()
    if HEARTBEATS_DIR.exists():
        for p in sorted(HEARTBEATS_DIR.glob("*.json")):
            d = _load(p)
            if d.get("run"):
                out.append(d)
                seen.add(d["run"])
    legacy = _load(HEARTBEAT)
    if legacy.get("run") and legacy["run"] not in seen:
        out.append(legacy)
    return out


def _save_heartbeat(data: dict) -> None:
    _save(HEARTBEATS_DIR / f"{data['run']}.json", data)
    _save(HEARTBEAT, data)


def _hb_list(hb) -> list:
    """Normalize the heartbeat argument: a list of per-worker dicts,
    or the legacy single dict."""
    if isinstance(hb, list):
        return [h for h in hb if isinstance(h, dict)]
    if isinstance(hb, dict) and hb:
        return [hb]
    return []


def _claim_list(sup: dict) -> list:
    """All launch claims as [{job, ts}]: the parallel launch_claims
    dict, plus the legacy single launch_claim when not already in
    the dict."""
    out = []
    claims = sup.get("launch_claims") or {}
    if isinstance(claims, dict):
        for job, c in claims.items():
            if isinstance(c, dict) and c.get("ts"):
                out.append({"job": job, "ts": c["ts"]})
    legacy = sup.get("launch_claim") or {}
    if legacy.get("ts") and not any(
            c["job"] == legacy.get("job") for c in out):
        out.append({"job": legacy.get("job"), "ts": legacy["ts"]})
    return out


def heartbeat_age_minutes(hb: dict, window_date: str,
                          now: datetime) -> float | None:
    """Age of the heartbeat in minutes, or None when there is no usable
    heartbeat for this window (no file, another window, bad stamp)."""
    if not hb or hb.get("window") != window_date or not hb.get("ts"):
        return None
    try:
        ts = datetime.fromisoformat(hb["ts"])
    except Exception:
        return None
    return (now - ts).total_seconds() / 60.0


def load_browser_progress() -> dict:
    """The bridge file's contents ({task_id: entry}); {} when the
    bridge has not run — liveness then degrades to heartbeat-only,
    exactly the pre-Nov-10 behavior."""
    return bp_mod.load_progress()


def task_progress_state(hb: dict, progress: dict | None,
                        now: datetime, rules: dict) -> dict:
    """The browser-progress judgment for heartbeat `hb`, per the
    bridge file: {"alive": bool, "ceiling_expired": bool,
    "task_age_minutes": float | None}.

    alive requires ALL of: the heartbeat records a browser task;
    the bridge holds an entry for it; the entry's status is
    "running" (a terminal task — completed, failed, needs_user,
    superseded — is not progress); the bridge check itself is fresh
    (<= supervisor.browser_progress_check_fresh_minutes old — older
    data proves nothing); and at check time the task had progressed
    within supervisor.browser_progress_stale_minutes.

    HARD CEILING (the user, Nov 10, 2026, later same evening): progress
    stops counting once the task itself is older than
    supervisor.browser_task_hard_ceiling_minutes (~2 hours), no
    matter how recently it progressed — ceiling_expired then reads
    True (the entry WAS progressing, but too old) and the worker
    falls back to the heartbeat rules. The age is measured from the
    entry's started_at (the task's muse.db created_at, bridged in);
    an entry with no recorded start cannot be ceiling-judged, so
    the progress rules apply to it unchanged. Pure —
    unit-testable."""
    out = {"alive": False, "ceiling_expired": False,
           "task_age_minutes": None}
    if not progress:
        return out
    task = bp_mod.normalize_task_id(hb.get("browser_task"))
    if not task:
        return out
    entry = progress.get(task)
    if not isinstance(entry, dict):
        return out
    if str(entry.get("status") or "") != "running":
        return out
    sup_rules = rules.get("supervisor") or {}
    stale_min = float(sup_rules.get(
        "browser_progress_stale_minutes", 15))
    check_fresh_min = float(sup_rules.get(
        "browser_progress_check_fresh_minutes", 40))
    checked = bp_mod.parse_ts(entry.get("checked_at"))
    last_prog = bp_mod.parse_ts(entry.get("last_progress_at"))
    if checked is None or last_prog is None:
        return out
    if (now - checked).total_seconds() / 60.0 > check_fresh_min:
        return out
    gap = (checked - last_prog).total_seconds() / 60.0
    if gap > stale_min:
        return out
    started = bp_mod.parse_ts(entry.get("started_at"))
    if started is not None:
        age_min = (now - started).total_seconds() / 60.0
        out["task_age_minutes"] = age_min
        ceiling_min = float(sup_rules.get(
            "browser_task_hard_ceiling_minutes", 120))
        if age_min > ceiling_min:
            out["ceiling_expired"] = True
            return out
    out["alive"] = True
    return out


def task_progress_alive(hb: dict, progress: dict | None,
                        now: datetime, rules: dict) -> bool:
    """True when heartbeat `hb` names a browser task that is still
    progressing (see task_progress_state for the full rule,
    including the 2-hour hard ceiling)."""
    return task_progress_state(hb, progress, now, rules)["alive"]


def worker_liveness(hbs_raw: list, window_date: str, now: datetime,
                    rules: dict, progress: dict | None) -> list:
    """Per-worker liveness for one window (shared by the verdict
    and stall_check): [{run, age, ended, browser_task,
    progress_alive, ceiling_expired, task_age_minutes, live}]. A
    worker is LIVE when it has not ended AND (its heartbeat is
    fresh OR its browser task is still progressing). A worker whose
    browser task passed the hard ceiling carries
    ceiling_expired=True and is judged on its heartbeat alone.
    Heartbeats with no usable stamp for this window are dropped, as
    in heartbeat_age_minutes."""
    sup_rules = rules.get("supervisor") or {}
    stale_min = float(sup_rules.get("heartbeat_stale_minutes", 20))
    out = []
    for h in hbs_raw:
        age = heartbeat_age_minutes(h, window_date, now)
        if age is None:
            continue
        ended = bool(h.get("ended"))
        state = (task_progress_state(h, progress, now, rules)
                 if not ended else {"alive": False,
                                    "ceiling_expired": False,
                                    "task_age_minutes": None})
        prog = state["alive"]
        out.append({"run": h.get("run"), "age": age, "ended": ended,
                    "browser_task": bp_mod.normalize_task_id(
                        h.get("browser_task")),
                    "progress_alive": prog,
                    "ceiling_expired": state["ceiling_expired"],
                    "task_age_minutes": state["task_age_minutes"],
                    "live": (not ended) and (age < stale_min or prog)})
    return out


def verdict_for(status: dict, rules: dict, now: datetime,
                hb, sup: dict, progress: dict | None = None) -> dict:
    """Pure verdict from spine status + heartbeats + supervisor
    state — unit-testable (same pattern as bench_check.verdict_for).
    `hb` is one heartbeat dict (legacy) or a list of per-worker
    dicts (parallel workers); `sup` carries launch_claims (a dict
    keyed by job) and/or the legacy single launch_claim;
    `progress` is the browser-progress bridge map ({task_id:
    entry}, from program/browser_progress.py) — a heartbeat-dark
    worker whose browser task is still progressing counts live
    (Nov 10, 2026 fix 2)."""
    w = status["window"]
    targets = status["targets"]
    verified = status["verified_total"]
    sup_rules = rules.get("supervisor") or {}
    stale_min = float(sup_rules.get("heartbeat_stale_minutes", 20))
    ttl_min = float(sup_rules.get("launch_claim_ttl_minutes", 15))
    max_par = int(sup_rules.get("max_parallel_workers", 1) or 1)
    hbs = worker_liveness(_hb_list(hb), w["date"], now, rules,
                          progress)
    live = [h for h in hbs if h["live"]]
    live_runs = {h["run"] for h in live}
    hb_runs = {h["run"] for h in hbs}
    pending = []
    for c in _claim_list(sup):
        try:
            cage = (now - datetime.fromisoformat(
                c["ts"])).total_seconds() / 60.0
        except Exception:
            continue
        if cage < ttl_min and c["job"] not in hb_runs:
            pending.append({"job": c["job"], "age": cage})
    slots = max_par - len(live) - len(pending)
    freshest = min(hbs, key=lambda h: h["age"]) if hbs else None
    base = {"window": w["date"], "verified": verified,
            "targets": {**{k: targets[k] for k in
                           ("linkedin", "jobright", "total")},
                        # Indeed passthrough (the user, Nov 12, 2026): a
                        # status dict from before the change has no
                        # indeed target — default 0, never KeyError.
                        "indeed": targets.get("indeed", 0),
                        # CareerOps passthrough (the user, Nov 16,
                        # 2026): same default-0 rule as Indeed.
                        "careerops": targets.get("careerops", 0),
                        # LinkedIn-alert passthrough (the user, Nov 12,
                        # 2026): same default-0 rule as Indeed.
                        "linkedin_alert": targets.get(
                            "linkedin_alert", 0)},
            "verified_by_source": status["verified_counts"],
            "bench": [b["id"] for b in status["bench"]],
            "staged": [s["id"] for s in status["staged"]],
            "captcha": [c["id"] for c in status["captcha"]],
            "limbo": [l["id"] for l in status["limbo"]],
            "heartbeat": ({"run": freshest["run"],
                           "age_minutes": round(freshest["age"], 1),
                           "ended": freshest["ended"]}
                          if freshest else None),
            "heartbeats": [{"run": h["run"],
                            "age_minutes": round(h["age"], 1),
                            "ended": h["ended"],
                            "browser_task": h["browser_task"],
                            "progress_alive": h["progress_alive"],
                            "ceiling_expired": h["ceiling_expired"],
                            "browser_task_age_minutes": (
                                round(h["task_age_minutes"], 1)
                                if h["task_age_minutes"] is not None
                                else None),
                            "live_via": ("browser_progress"
                                         if h["progress_alive"]
                                         and h["age"] >= stale_min
                                         else "heartbeat"
                                         if h["live"] else None)}
                           for h in hbs],
            "live_workers": sorted(r for r in live_runs if r),
            "progress_alive_workers": sorted(
                h["run"] for h in hbs
                if h["progress_alive"] and h["run"]),
            "ceiling_expired_workers": sorted(
                h["run"] for h in hbs
                if h["ceiling_expired"] and h["run"]),
            "pending_claims": [p["job"] for p in pending],
            "max_parallel_workers": max_par,
            "heartbeat_stale_minutes": stale_min,
            "friction_scope": status.get("friction_scope")}
    # Friction split (the user, Nov 7, 2026): a full-stop flag (scope "all",
    # or a status dict with no scope info — the pre-change shape,
    # which must keep its old meaning) halts everything. A
    # LinkedIn-scoped flag does NOT return here: the flow below runs
    # with jobright_only set, and a launch verdict is named
    # JOBRIGHT_ONLY so the guardian launches Jobright-mode workers.
    jobright_only = status.get("friction_scope") == "linkedin"
    if status["friction"] and not jobright_only:
        return {**base, "verdict": "FRICTION_STOP",
                "detail": "friction flag set — all work halted until "
                          "cleared; never launch"}
    if now >= datetime.fromisoformat(w["closes"]):
        return {**base, "verdict": "CLOSED",
                "detail": "window closed — no launch; spine.py closeout "
                          "governs the accounting"}
    if verified >= targets["total"]:
        return {**base, "verdict": "COMPLETE",
                "detail": "window target reached"}
    if slots > 0:
        ended_any = any(h["ended"] for h in hbs)
        if ended_any and not live:
            reason = "worker run ended cleanly — start the next"
        elif freshest is None:
            reason = "no heartbeat on file for this window"
        elif not live and not pending:
            reason = (f"heartbeat stale ({freshest['age']:.0f} min "
                      f">= {stale_min:.0f})")
        else:
            reason = (f"{len(live)} of {max_par} worker slots "
                      f"filled — top up")
        return {**base,
                "verdict": "JOBRIGHT_ONLY" if jobright_only else "LAUNCH",
                "launch_slots": slots,
                "reason": reason,
                "jobright_only": jobright_only,
                "template": "program/worker_template.md",
                "detail": ("LinkedIn lane stopped by friction — "
                           "the external sources (Jobright + Indeed + "
                           "the CareerOps scan) "
                           "and the LinkedIn-alert lane "
                           "carry the window (the user, Nov 7, 2026; Indeed "
                           "and LinkedIn alerts added Nov 12, 2026; "
                           "CareerOps scan added Nov 16, 2026): "
                           "work remains and "
                           "worker slots are "
                           "free — the guardian claims each launch, "
                           "creates external-source workers from the "
                           "template, then confirms each with "
                           "`launched`"
                           if jobright_only else
                           "work remains and worker slots are free — "
                           "the guardian claims each launch, creates "
                           "the workers from the template, then "
                           "confirms each with `launched`")}
    if live:
        prog_live = [h["run"] for h in live if h["progress_alive"]]
        return {**base, "verdict": "WORKER_ALIVE",
                "detail": f"{len(live)} worker(s) live "
                          f"({', '.join(sorted(r for r in live_runs if r))}) "
                          f"and every slot filled — slow is not stuck; "
                          "start nothing"
                          + (f"; {len(prog_live)} live via browser "
                             f"progress ({', '.join(sorted(prog_live))}) "
                             f"— heartbeat-dark but their browser "
                             f"tasks are still moving (Nov 10, 2026 "
                             f"fix 2)" if prog_live else "")}
    if pending:
        p0 = pending[0]
        return {**base, "verdict": "CLAIM_PENDING",
                "claim": {"job": p0["job"],
                          "age_minutes": round(p0["age"], 1)},
                "detail": "launch(es) claimed and unexpired; the "
                          "claimed worker(s) have not heartbeat yet "
                          "and every slot is spoken for — start "
                          "nothing"}
    return {**base, "verdict": "WORKER_ALIVE",
            "detail": "worker slots full — start nothing"}


def _rules() -> dict:
    return yaml.safe_load(open(BASE / "config" / "rules.yaml"))


def cmd_verdict(args) -> int:
    sp = Spine()
    status = sp.status(args.date)
    out = verdict_for(status, _rules(), datetime.now(state_mod.CT),
                      _load_heartbeats(), _load(SUP_STATE),
                      load_browser_progress())
    if out["verdict"] in ("LAUNCH", "JOBRIGHT_ONLY"):
        out["next_order_status"] = sp.next_order(
            args.date).get("status")
    print(json.dumps(out))
    return 3 if out["verdict"] in ("LAUNCH", "JOBRIGHT_ONLY") else 0


def cmd_heartbeat(args) -> int:
    sp = Spine()
    window_date = sp.status(args.date)["window"]["date"]
    now = datetime.now(state_mod.CT)
    data = {"run": args.run, "ts": now.isoformat(),
            "window": window_date, "note": args.note or ""}
    task = bp_mod.normalize_task_id(
        getattr(args, "browser_task", None))
    if task:
        # The worker is about to wait on this browser task
        # (delegating ends its turn, so this heartbeat is its last
        # word before the wait). The id is stored normalized (bare
        # UUID) so the bridge file and the verdict compare equal.
        data["browser_task"] = task
        data["browser_task_since"] = now.isoformat()
    # A heartbeat WITHOUT --browser-task deliberately carries no
    # browser_task: heartbeats are written between browser calls,
    # so a plain heartbeat means "not waiting on a task right now"
    # and any earlier task id is dropped.
    _save_heartbeat(data)
    print(json.dumps({"ok": True, "heartbeat": data}))
    return 0


def cmd_done(args) -> int:
    """The worker's tombstone (written once, when its run ends):
    mark its own heartbeat ended so the next supervisor verdict
    frees the slot and launches a fresh worker, with no staleness
    wait."""
    sp = Spine()
    window_date = sp.status(args.date)["window"]["date"]
    now = datetime.now(state_mod.CT)
    data = {"run": args.run, "ts": now.isoformat(),
            "window": window_date, "ended": True,
            "note": args.note or ""}
    _save_heartbeat(data)
    print(json.dumps({"ok": True, "done": data}))
    return 0


def cmd_claim(args) -> int:
    sp = Spine()
    status = sp.status(args.date)
    rules = _rules()
    now = datetime.now(state_mod.CT)
    sup = _load(SUP_STATE)
    verdict = verdict_for(status, rules, now, _load_heartbeats(), sup,
                          load_browser_progress())
    if verdict["verdict"] not in ("LAUNCH", "JOBRIGHT_ONLY"):
        print(json.dumps({"ok": False, "refused": verdict["verdict"],
                          "detail": verdict["detail"]}))
        return 3
    claims = dict(sup.get("launch_claims") or {})
    if args.job in claims:
        print(json.dumps({"ok": False, "refused": "already_claimed",
                          "detail": f"{args.job} already holds a "
                                    "launch claim"}))
        return 3
    legacy = sup.pop("launch_claim", None)
    if legacy and legacy.get("job") and legacy.get("ts"):
        claims.setdefault(legacy["job"], {"ts": legacy["ts"]})
    claims[args.job] = {"ts": now.isoformat()}
    sup["launch_claims"] = claims
    _save(SUP_STATE, sup)
    print(json.dumps({"ok": True, "claimed": args.job,
                      "window": status["window"]["date"],
                      "launch_slots_left": verdict["launch_slots"] - 1}))
    return 0


def cmd_launched(args) -> int:
    now = datetime.now(state_mod.CT)
    sup = _load(SUP_STATE)
    claims = dict(sup.get("launch_claims") or {})
    claims.pop(args.job, None)
    sup["launch_claims"] = claims
    claim = sup.get("launch_claim") or {}
    if claim.get("job") == args.job:
        sup.pop("launch_claim", None)
    sup["last_launch"] = {"job": args.job, "ts": now.isoformat()}
    _save(SUP_STATE, sup)
    print(json.dumps({"ok": True, "launched": args.job}))
    return 0


def cmd_clear_claim(args) -> int:
    sup = _load(SUP_STATE)
    cleared = None
    if args.job:
        claims = dict(sup.get("launch_claims") or {})
        cleared = claims.pop(args.job, None)
        sup["launch_claims"] = claims
        claim = sup.get("launch_claim") or {}
        if claim.get("job") == args.job:
            cleared = sup.pop("launch_claim", None)
    else:
        cleared = {"launch_claims": sup.pop("launch_claims", {}),
                   "launch_claim": sup.pop("launch_claim", None)}
    _save(SUP_STATE, sup)
    print(json.dumps({"ok": True, "cleared": cleared}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="supervisor.py")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("verdict", "heartbeat", "done", "claim", "launched",
                 "clear-claim"):
        p = sub.add_parser(name)
        p.add_argument("--date", default=None)
        if name in ("heartbeat", "done"):
            p.add_argument("--run", required=True)
            p.add_argument("--note", default=None)
        if name == "heartbeat":
            p.add_argument("--browser-task", default=None,
                           help="id of the browser task this worker "
                                "is about to wait on (recorded in "
                                "the heartbeat so the supervisor can "
                                "judge liveness by the task's "
                                "progress — Nov 10, 2026 fix 2)")
        if name in ("claim", "launched"):
            p.add_argument("--job", required=True)
        if name == "clear-claim":
            p.add_argument("--job", default=None)
    args = ap.parse_args()
    cmd = args.cmd or "verdict"
    return {"verdict": cmd_verdict, "heartbeat": cmd_heartbeat,
            "done": cmd_done, "claim": cmd_claim,
            "launched": cmd_launched,
            "clear-claim": cmd_clear_claim}[cmd](args)


if __name__ == "__main__":
    sys.exit(main())
