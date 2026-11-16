"""bench_check.py — the bench-low restock verdict (the user, Nov 4, 2026:
"Add in code: bench low, trigger restock. Only do this in code.").

The CODE decides when the ready bench is too low; the driver-mode
watcher carries the verdict out (its Step 6): on RESTOCK_NEEDED it
triggers a guardian pass, and the guardian's own Step 0 verdict
(recovery_check.py) governs the launch — a fresh recovery stocks AND
applies. If a batch-family run is already in flight, it is the restock
in progress and the guardian launches nothing.

Verdicts:
  RESTOCK_NEEDED  bench at/below rules.yaml bench.low_watermark AND
                  below the window's remaining need; window open,
                  target unmet, friction clear. (exit 3)
  BENCH_OK        bench above the watermark, or already covers the
                  remaining need.
  COMPLETE        window target reached — no restock needed.
  CLOSED          window closed — no restock; closeout governs.
  FRICTION_STOP   full-stop friction flag set (scope "all") — all
                  work halted; never restock over it.
  RESTOCK_NEEDED_JOBRIGHT
                  LinkedIn-lane friction (scope "linkedin", the user,
                  Nov 7, 2026) with the Jobright bench below the
                  watermark and the need unmet — restock from
                  JOBRIGHT only; the watcher treats it exactly like
                  RESTOCK_NEEDED (exit 3). Since Nov 12, 2026 the
                  bench that counts in this mode is the EXTERNAL
                  bench (Jobright + Indeed — Indeed added on the
                  exact Jobright rules); the verdict name is
                  unchanged.

Usage: python3 bench_check.py [--date YYYY-MM-DD]
Prints ONE JSON verdict line. Exit 3 on RESTOCK_NEEDED, else 0.
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


def verdict_for(status: dict, rules: dict, now: datetime) -> dict:
    """Pure verdict from a spine status dict — unit-testable."""
    w = status["window"]
    targets = status["targets"]
    verified = status["verified_total"]
    bench = status["bench"]
    watermark = int((rules.get("bench") or {}).get("low_watermark", 5))
    remaining = max(0, targets["total"] - verified)
    base = {"window": w["date"], "verified": verified,
            "target": targets["total"], "remaining_need": remaining,
            "bench_count": len(bench),
            "bench": [b["id"] for b in bench],
            "low_watermark": watermark}
    # Friction split (the user, Nov 7, 2026): scope "all" (or a scope-less
    # status dict, the pre-change shape) is a full stop. Scope
    # "linkedin" falls through with jobright_only set: the bench that
    # counts is the Jobright bench, and a low bench asks for a
    # Jobright restock instead of stopping.
    jobright_only = status.get("friction_scope") == "linkedin"
    if status["friction"] and not jobright_only:
        return {**base, "verdict": "FRICTION_STOP",
                "detail": "friction flag set — all work halted; "
                          "never restock over friction"}
    if jobright_only:
        # The bench that counts is the external bench: Jobright +
        # Indeed (Indeed added Nov 12, 2026 on the Jobright rules) +
        # LinkedIn alerts (added Nov 12, 2026 — the alert lane is its
        # own lane and stays servable under LinkedIn-lane friction).
        bench = [b for b in bench
                 if (b.get("source") or "").upper()
                 in ("JOBRIGHT", "INDEED", "LINKEDIN_ALERT")]
        base = {**base, "bench_count": len(bench),
                "bench": [b["id"] for b in bench],
                "jobright_only": True}
    if now >= datetime.fromisoformat(w["closes"]):
        return {**base, "verdict": "CLOSED",
                "detail": "window closed — no restock; closeout governs"}
    if remaining == 0:
        return {**base, "verdict": "COMPLETE",
                "detail": "window target reached"}
    if jobright_only and len(bench) <= watermark and len(bench) < remaining:
        return {**base, "verdict": "RESTOCK_NEEDED_JOBRIGHT",
                "detail": "LinkedIn lane stopped by friction; external "
                          "bench (Jobright + Indeed + LinkedIn alerts) "
                          "at/below the low "
                          "watermark while the "
                          "target is unmet — trigger a guardian pass; "
                          "workers restock from the external sources "
                          "only — JOBRIGHT + INDEED + LINKEDIN_ALERT (the user, "
                          "Nov 7, 2026; Indeed + LinkedIn alerts added "
                          "Nov 12, 2026)"}
    if len(bench) <= watermark and len(bench) < remaining:
        return {**base, "verdict": "RESTOCK_NEEDED",
                "detail": "bench at/below the low watermark while the "
                          "target is unmet — trigger a guardian pass; "
                          "its Step 0 verdict governs the launch (a "
                          "fresh recovery stocks AND applies; a run "
                          "already in flight is the restock in "
                          "progress)"}
    return {**base, "verdict": "BENCH_OK",
            "detail": "bench above the low watermark or already "
                      "covers the remaining need"}


def main() -> int:
    ap = argparse.ArgumentParser(prog="bench_check.py")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    sp = Spine()
    out = verdict_for(sp.status(args.date), sp.rules,
                      datetime.now(state_mod.CT))
    print(json.dumps(out))
    return 3 if out["verdict"] in ("RESTOCK_NEEDED",
                                   "RESTOCK_NEEDED_JOBRIGHT") else 0


if __name__ == "__main__":
    sys.exit(main())
