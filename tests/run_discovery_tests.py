#!/usr/bin/env python3
"""Discovery-management tests (the user, Nov 13, 2026 — sources in code).

ISOLATED BY CONSTRUCTION: the discovery state file lives in a fresh
temp dir; nothing here reads or writes the live program state. The
plan is built from the LIVE rules.yaml on purpose — these checks pin
the user's source rules (three sources, the four-search matrices, the
sites' own filters, the alert lane's manager) to the config the code
actually reads, so a config edit that breaks a rule fails loudly.

Covered: plan shape for all three sources; pass recording; the
one-pass-per-source-per-run refusal (the user's one-pass rule enforced in
code); matrix coverage refusal (missing or extra searches); the
alert source refusing worker-pass recording; bad-count refusal;
code-computed coverage.

Run: python3 tests/run_discovery_tests.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))

import discovery as disc  # noqa: E402

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name
          + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def main() -> int:
    rules = yaml.safe_load(
        (BASE / "config" / "rules.yaml").read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp(prefix="discovery-tests-"))
    state = tmp / "discovery.json"
    check("setup: temp state is not the live state dir",
          "program/state" not in str(state))

    plans = disc.build_plan(rules)
    check("p: plan covers exactly the three sources",
          set(plans) == {"JOBRIGHT", "INDEED", "LINKEDIN_ALERT"})
    check("p: Jobright plan carries the 4-search matrix and both "
          "site filters",
          len(plans["JOBRIGHT"]["searches"]) == 4
          and plans["JOBRIGHT"]["filters"] ==
          {"date_posted": "last_24_hours", "job_type": "full_time"})
    check("p: Indeed plan carries the 4-search matrix and both "
          "site filters",
          len(plans["INDEED"]["searches"]) == 4
          and plans["INDEED"]["filters"] ==
          {"date_posted": "last_24_hours", "job_type": "full_time"})
    check("p: Jobright remote rows ride the Work-model filter, "
          "Indeed remote rows the location field",
          plans["JOBRIGHT"]["searches"][2]["remote_via"] ==
          "work_model_filter"
          and plans["INDEED"]["searches"][2]["remote_via"] ==
          "location_field")
    check("p: both worker sources are one pass per run, screening "
          "only, employer-site applications",
          all(plans[s]["passes_per_run"] == 1
              and plans[s]["screening_only"] is True
              and "employer/ATS" in plans[s]["apply_route"]
              for s in ("JOBRIGHT", "INDEED")))
    check("p: alert plan is an email flow managed by the inbox "
          "job-alert flow, max 5 pages",
          plans["LINKEDIN_ALERT"]["kind"] == "email_flow"
          and "inbox.py" in plans["LINKEDIN_ALERT"]["managed_by"]
          and plans["LINKEDIN_ALERT"]["max_pages"] == 5)
    try:
        disc.build_plan(rules, source="MONSTER")
        check("p: unknown source refused", False)
    except ValueError:
        check("p: unknown source refused", True)

    matrix = [{"title": s["title"],
               "location_scope": s["location_scope"]}
              for s in plans["JOBRIGHT"]["searches"]]
    packet = {"source": "JOBRIGHT", "run_id": "run-A",
              "searches_done": matrix, "cards_seen": 49,
              "candidates": 3}
    row = disc.record_pass(state, packet, rules)
    check("r: a full-matrix Jobright pass records",
          row["source"] == "JOBRIGHT" and row["cards_seen"] == 49)
    try:
        disc.record_pass(state, packet, rules)
        check("r: second pass for same run+source REFUSED "
              "(one-pass rule in code)", False)
    except ValueError:
        check("r: second pass for same run+source REFUSED "
              "(one-pass rule in code)", True)
    try:
        disc.record_pass(state, {**packet, "run_id": "run-B",
                                 "searches_done": matrix[:3]}, rules)
        check("r: incomplete matrix refused", False)
    except ValueError:
        check("r: incomplete matrix refused", True)
    try:
        disc.record_pass(state, {**packet, "run_id": "run-B",
                                 "searches_done": matrix + [
                                     {"title": "Data Scientist",
                                      "location_scope": "Remote"}]},
                         rules)
        check("r: extra search outside the matrix refused", False)
    except ValueError:
        check("r: extra search outside the matrix refused", True)
    try:
        disc.record_pass(state, {"source": "LINKEDIN_ALERT",
                                 "run_id": "run-B", "searches_done": [],
                                 "cards_seen": 0, "candidates": 0},
                         rules)
        check("r: alert source refuses worker-pass recording", False)
    except ValueError:
        check("r: alert source refuses worker-pass recording", True)
    try:
        disc.record_pass(state, {**packet, "run_id": "run-B",
                                 "cards_seen": -1}, rules)
        check("r: negative card count refused", False)
    except ValueError:
        check("r: negative card count refused", True)

    disc.record_pass(state, {**packet, "run_id": "run-B",
                             "cards_seen": 10, "candidates": 1}, rules)
    cov = disc.coverage(state, day=row["day"])
    check("s: coverage is code-computed across runs",
          cov["sources"]["JOBRIGHT"] ==
          {"passes": 2, "cards_seen": 59, "candidates": 4,
           "last_run_id": "run-B"}
          and cov["sources"]["INDEED"]["passes"] == 0)

    print(f"\n{'ALL PASS' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}"
          f" ({len(FAILS)} failed)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
