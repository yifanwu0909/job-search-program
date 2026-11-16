"""recovery_check.py — the recovery-launch verdict (the user, Nov 4, 2026:
"build everything on code").

The CODE decides whether the batch needs a (re)launch; the guardian only
carries out the verdict. The one fact the code cannot see is whether a
batch-family run is in flight right now (cron state) — the guardian
checks that itself and launches only when this verdict says NEEDS_LAUNCH
and nothing is in flight.

Verdicts:
  NEEDS_LAUNCH    window open, target unmet, friction clear — launch a
                  fresh recovery if nothing is in flight. Carries the
                  counts, the ready bench, and the next order's status
                  (work_order / pacing_hold / empty→discovery first).
  COMPLETE        window target reached — nothing to launch.
  CLOSED          window closed — no launch; closeout belongs to
                  `spine.py closeout`.
  FRICTION_STOP   a full-stop friction flag is set (scope "all") —
                  all work halted until the flag is cleared; never
                  launch over it. A LinkedIn-scoped flag (the user, Nov 7,
                  2026) does NOT stop recovery: NEEDS_LAUNCH then
                  carries jobright_only: true and the launch is a
                  Jobright-mode worker.

Usage: python3 recovery_check.py [--date YYYY-MM-DD]
Prints ONE JSON verdict line. Exit 0 always; the verdict is the payload.
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
from pipeline import Spine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(prog="recovery_check.py")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    sp = Spine()
    status = sp.status(args.date)
    w = status["window"]
    targets = status["targets"]
    verified = status["verified_total"]
    now = datetime.now(state_mod.CT)
    closes = datetime.fromisoformat(w["closes"])
    base = {"window": w["date"], "verified": verified,
            "targets": {**{k: targets[k] for k in ("linkedin", "jobright", "total")},
                        # CareerOps passthrough (the user, Nov 16,
                        # 2026): a status dict from before the source
                        # was added has no careerops target — default
                        # 0, never KeyError.
                        "careerops": targets.get("careerops", 0)},
            "verified_by_source": status["verified_counts"],
            "bench": [b["id"] for b in status["bench"]],
            "claimed_unfinished": [c["id"] for c in status["claimed_unfinished"]],
            "staged": [s["id"] for s in status["staged"]],
            "captcha": [c["id"] for c in status["captcha"]],
            "limbo": [l["id"] for l in status["limbo"]],
            "friction_scope": status.get("friction_scope")}

    # Friction split (the user, Nov 7, 2026): only a full-stop flag (scope
    # "all", or a scope-less status — the pre-change shape) halts
    # recovery. LinkedIn-scoped friction falls through: the launch
    # below is a Jobright-mode worker.
    jobright_only = status.get("friction_scope") == "linkedin"
    if status["friction"] and not jobright_only:
        print(json.dumps({**base, "verdict": "FRICTION_STOP",
                          "detail": "friction flag set — all work halted "
                                    "until cleared; never launch"}))
        return 0
    if now >= closes:
        print(json.dumps({**base, "verdict": "CLOSED",
                          "detail": "window closed — no launch; run "
                                    "spine.py closeout for the accounting"}))
        return 0
    if verified >= targets["total"]:
        print(json.dumps({**base, "verdict": "COMPLETE",
                          "detail": "window target reached"}))
        return 0
    nxt = sp.next_order(args.date)
    print(json.dumps({**base, "verdict": "NEEDS_LAUNCH",
                      "jobright_only": jobright_only,
                      "next_order_status": nxt.get("status"),
                      "detail": ("LinkedIn lane stopped by friction — "
                                 "launch a Jobright-mode recovery if no "
                                 "batch-family run is in flight (the user, "
                                 "Nov 7, 2026). Bench empty means the "
                                 "recovery stocks via external discovery "
                                 "(Jobright + Indeed + the CareerOps scan) "
                                 "first."
                                 if jobright_only else
                                 "window open, target unmet — launch a fresh "
                                 "recovery if no batch-family run is in "
                                 "flight (the guardian checks cron state; "
                                 "this code cannot see it). Bench empty "
                                 "means the recovery stocks via discovery "
                                 "first.")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
