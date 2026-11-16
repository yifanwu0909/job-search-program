"""browser_progress.py — the browser-progress bridge (the user, Nov 10,
2026 — freeze investigation fix 2).

WHY THIS EXISTS: the liveness decision lives in code
(supervisor.py / stall_check.py), but the browser tasks' progress
lives in muse.db (runtime.browser_tasks), which plain Python on
this VM cannot query (no DB driver, no credentials — muse.db is an
agent tool surface). So the agents that DO have muse.db — the
guardian and the watcher (linkedin-spine-shadow) — read the
progress of the browser tasks named in the workers' heartbeats and
record it here, in program/state/browser_progress.json. The
program then judges liveness from this file IN CODE. The agents
are dumb pipes: they fetch rows and call `record`; every threshold
and every decision stays in supervisor.py / stall_check.py and
rules.yaml.

A worker records the browser task it is waiting on in its own
heartbeat (`supervisor.py heartbeat --run <id> --browser-task
<task id>`) immediately after delegating — delegating ends its
turn, so that heartbeat is the last thing it can write before the
wait. Task ids are normalized to the bare UUID (the
"browser-task:" prefix runtime.browser_tasks carries is stripped)
so every side compares the same string.

File shape:
  {"tasks": {"<uuid>": {"status": "running",
                        "last_progress_at": "<iso>",
                        "step_count": 12,
                        "started_at": "<iso>",
                        "checked_at": "<iso>"}}}

`checked_at` is when the bridge last read the row from muse.db.
supervisor.py ignores any entry whose check is older than
supervisor.browser_progress_check_fresh_minutes in rules.yaml —
stale bridge data proves nothing, in either direction.

`started_at` is the browser task's own start (runtime.browser_tasks
.created_at), bridged the same way. supervisor.py measures the
task's age from it for the hard ceiling
(supervisor.browser_task_hard_ceiling_minutes: past ~2 hours a
task's progress no longer makes its worker live). A task's start
never moves, so the earliest recorded started_at wins and a record
without one preserves the stored value; an entry with no started_at
at all simply cannot be ceiling-judged.

Usage:
  python3 browser_progress.py record --task <id> --status <status>
      --last-progress <iso timestamp> [--step-count N]
      [--started-at <iso timestamp>]
  python3 browser_progress.py show
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))

import state as state_mod  # noqa: E402

PROGRESS = BASE / "state" / "browser_progress.json"
TASK_PREFIX = "browser-task:"


def normalize_task_id(task_id: str | None) -> str | None:
    """The bare task UUID: runtime.browser_tasks stores ids as
    "browser-task:<uuid>"; browse receipts and heartbeats may carry
    either form. Compare on the bare UUID everywhere."""
    if not task_id:
        return None
    t = str(task_id).strip()
    if t.lower().startswith(TASK_PREFIX):
        t = t[len(TASK_PREFIX):]
    return t or None


def parse_ts(text: str | None) -> datetime | None:
    """Lenient ISO parse (accepts a trailing Z and the Postgres
    text form "2026-11-10 20:59:24-06"); None when unusable. A
    naive stamp is read as Central (the bridge runs in CT)."""
    if not text:
        return None
    t = str(text).strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=state_mod.CT)
    return dt


def load_progress(path: Path | None = None) -> dict:
    """{task_id: entry} from the bridge file; {} when absent or
    unreadable — no bridge data is a normal state (it degrades
    liveness to the heartbeat-only judgment)."""
    try:
        data = json.loads((path or PROGRESS).read_text(
            encoding="utf-8"))
    except Exception:
        return {}
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(tasks, dict):
        return {}
    out = {}
    for tid, entry in tasks.items():
        key = normalize_task_id(tid)
        if key and isinstance(entry, dict):
            out[key] = entry
    return out


def record_entry(tasks: dict, task_id: str, status: str,
                 last_progress_at: str, step_count,
                 checked_at: datetime, started_at=None) -> dict:
    """Upsert one bridge entry (pure — unit-testable).

    `started_at` is the browser task's own start (its muse.db
    created_at). A task's start never moves: the earliest value
    seen wins, and a record carrying no start preserves the stored
    one — so a refresh that omits it can never push the hard
    ceiling's clock forward."""
    key = normalize_task_id(task_id)
    if not key:
        raise ValueError("empty task id")
    lp = parse_ts(last_progress_at)
    if lp is None:
        raise ValueError(f"unparseable last-progress: "
                         f"{last_progress_at!r}")
    entry = {"status": str(status),
             "last_progress_at": lp.isoformat(),
             "checked_at": checked_at.isoformat()}
    if step_count is not None:
        entry["step_count"] = int(step_count)
    starts = [d for d in (parse_ts(started_at),
                          parse_ts((tasks.get(key) or {})
                                   .get("started_at")))
              if d is not None]
    if starts:
        entry["started_at"] = min(starts).isoformat()
    tasks[key] = entry
    return tasks


def cmd_record(args) -> int:
    tasks = load_progress()
    try:
        record_entry(tasks, args.task, args.status,
                     args.last_progress, args.step_count,
                     datetime.now(state_mod.CT),
                     started_at=getattr(args, "started_at", None))
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 2
    PROGRESS.parent.mkdir(exist_ok=True)
    PROGRESS.write_text(json.dumps({"tasks": tasks}, indent=1),
                        encoding="utf-8")
    print(json.dumps({"ok": True,
                      "recorded": normalize_task_id(args.task),
                      "tasks_on_file": len(tasks)}))
    return 0


def cmd_show(args) -> int:
    print(json.dumps({"tasks": load_progress()}, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="browser_progress.py")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("record")
    p.add_argument("--task", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--last-progress", required=True)
    p.add_argument("--step-count", type=int, default=None)
    p.add_argument("--started-at", default=None,
                   help="the browser task's start (its muse.db "
                        "created_at) — feeds the hard ceiling in "
                        "supervisor.py; optional, and a record "
                        "without it preserves the stored start")
    sub.add_parser("show")
    args = ap.parse_args()
    return {"record": cmd_record, "show": cmd_show}[
        args.cmd or "show"](args)


if __name__ == "__main__":
    sys.exit(main())
