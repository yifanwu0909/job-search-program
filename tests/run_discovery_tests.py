#!/usr/bin/env python3
"""Discovery-management tests (the user, Nov 13, 2026 — sources in
code; Nov 16, 2026 — the career-ops scan is a THIRD worker source,
added alongside Jobright and Indeed at the user's direction: "Use
career ops as additional resources to stock the bench").

ISOLATED BY CONSTRUCTION: the discovery state file and the stock
log live in fresh temp dirs; nothing here reads or writes the live
program state. The plan is built from the LIVE rules.yaml on
purpose — these checks pin the user's source rules (JOBRIGHT +
INDEED + CAREEROPS + LINKEDIN_ALERT, the four-search matrices, the
sites' own filters, the scan steps, the past-24-hours window, the
alert lane's manager) to the config the code actually reads, so a
config edit that breaks a rule fails loudly.

Covered: plan shape for all four sources; pass recording (search
matrices for Jobright/Indeed, steps_done for the scan); the
one-pass-per-source-per-run refusal (the user's one-pass rule
enforced in code); matrix/step coverage refusal (missing or extra
entries); the alert source refusing worker-pass recording;
bad-count refusal; code-computed coverage; and the DUPLICATE
screen proofs for the scan source (the user, Nov 16, 2026: "Still
verify for duplicate"): a CAREEROPS candidate whose company is in
the all-time applied record is dropped by the duplication screen,
and a CAREEROPS candidate carrying the same ATS posting id as an
earlier JOBRIGHT find is caught cross-platform.

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
import stock  # noqa: E402

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
    check("p: plan covers exactly the four sources",
          set(plans) == {"JOBRIGHT", "INDEED", "CAREEROPS",
                         "LINKEDIN_ALERT"})
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
    check("p: both browser worker sources are one pass per run, "
          "screening only, employer-site applications",
          all(plans[s]["passes_per_run"] == 1
              and plans[s]["screening_only"] is True
              and "employer/ATS" in plans[s]["apply_route"]
              for s in ("JOBRIGHT", "INDEED")))
    co = plans["CAREEROPS"]
    check("p: CareerOps plan is the ATS scan from the install root",
          co["kind"] == "worker_pass"
          and co["method"] == "career_ops_scan"
          and co["install_root"].endswith("career-ops")
          and "portals.yml" in co["portals_config"])
    check("p: scan steps are scan-ats-full then scan, both --since 1 "
          "(the past-24-hours window, never widened)",
          [s["scanner"] for s in co["scan_steps"]] ==
          ["scan-ats-full", "scan"]
          and all("--since 1" in s["command"]
                  for s in co["scan_steps"]))
    check("p: scan titles are the job-search titles (plain 'Data "
          "Scientist' is not a scan title)",
          co["titles"] == ["Senior Data Scientist",
                           "Machine Learning Engineer"],
          str(co["titles"]))
    check("p: CareerOps pass is one per run, full-time, employer/ATS "
          "applications",
          co["passes_per_run"] == 1
          and co["job_type"] == "full_time"
          and "employer/ATS" in co["apply_route"]
          and co["max_posting_age_hours"] == 24)
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

    steps = [s["scanner"] for s in co["scan_steps"]]
    co_packet = {"source": "CAREEROPS", "run_id": "run-A",
                 "steps_done": steps, "cards_seen": 49,
                 "candidates": [{"company": "Example Co",
                                 "title": "Senior Data Scientist",
                                 "url": "https://example.com/1"},
                                {"company": "Other Co",
                                 "title": "Machine Learning Engineer",
                                 "url": "https://example.com/2"}]}
    co_row = disc.record_pass(state, co_packet, rules)
    check("r: a full-steps CareerOps pass records (candidates "
          "counted from the list)",
          co_row["source"] == "CAREEROPS"
          and co_row["cards_seen"] == 49
          and co_row["candidates"] == 2)
    try:
        disc.record_pass(state, co_packet, rules)
        check("r: second CareerOps pass for same run REFUSED "
              "(one-pass rule in code)", False)
    except ValueError:
        check("r: second CareerOps pass for same run REFUSED "
              "(one-pass rule in code)", True)
    try:
        disc.record_pass(state, {**co_packet, "run_id": "run-B",
                                 "steps_done": steps[:1]}, rules)
        check("r: incomplete scan-step set refused", False)
    except ValueError:
        check("r: incomplete scan-step set refused", True)
    try:
        disc.record_pass(state, {**co_packet, "run_id": "run-B",
                                 "steps_done": steps + ["scan-x"]},
                         rules)
        check("r: extra scan step outside the plan refused", False)
    except ValueError:
        check("r: extra scan step outside the plan refused", True)
    try:
        disc.record_pass(state, {**co_packet, "run_id": "run-B",
                                 "candidates": [{"company": "NoUrl Co",
                                                 "title": "Senior Data "
                                                          "Scientist"}]},
                         rules)
        check("r: scan candidate without a posting url refused",
              False)
    except ValueError:
        check("r: scan candidate without a posting url refused", True)

    disc.record_pass(state, {**co_packet, "run_id": "run-B",
                             "cards_seen": 10, "candidates": 1}, rules)
    cov = disc.coverage(state, day=co_row["day"])
    check("s: CareerOps coverage is code-computed across runs",
          cov["sources"]["CAREEROPS"] ==
          {"passes": 2, "cards_seen": 59, "candidates": 3,
           "last_run_id": "run-B"})

    # --- DUPLICATE SCREEN PROOFS for the CAREEROPS source (the
    # user, Nov 16, 2026: "Still verify for duplicate"). The screens
    # are stock.py's, run against a synthetic log whose applied
    # record holds Fixture Corp.
    fixture = """# Outreach log (test fixture)

### Blocked companies — THE DEAD-NO-GO ZONE (test fixture)

- Blockedco

## 2026-11-05 — LinkedIn Recommended applications batch — 2026-11-05

- [3:00 PM CST, Mon Oct 26, 2026] STOCKED #100 — Fixture Corp — Data Scientist — source LINKEDIN
- [3:05 PM CST, Mon Oct 26, 2026] SUBMITTED (page-confirmed) — #100 Fixture Corp, Data Scientist (Fixture careers). Confirmation: portal page. SOURCE TAG: LINKEDIN. (Recorded by spine program.)
"""
    log = tmp / "log.md"
    log.write_text(fixture, encoding="utf-8")

    out = stock.record({"items": [
        {"company": "Fixture Corp", "role": "Senior Data Scientist",
         "source": "CAREEROPS",
         "url": "https://job-boards.greenhouse.io/fixturecorp/jobs/1",
         "gate": {"screen_only": True}}]}, log_path=log)
    rec = out["recorded"][0] if out["recorded"] else {}
    check("d1 CAREEROPS candidate at an already-applied company is "
          "dropped by the DUPLICATE screen",
          rec.get("gate") == "DROPPED_DUPLICATE_COMPANY"
          and rec.get("state") == "skipped_duplicate"
          and rec.get("verified") is True, str(out))

    def full_item(company, role, source, url):
        return {"company": company, "role": role, "source": source,
                "url": url,
                "gate": {"total": 3000, "india": 100,
                         "source": "Revelio Labs"},
                "pay": {"figure": 250000, "basis": "city",
                        "city": "Chicago, IL", "source": "bestplaces"}}

    out = stock.record({"items": [
        full_item("Crossplat Co", "Senior Data Scientist", "JOBRIGHT",
                  "https://job-boards.greenhouse.io/crossplatco/jobs/"
                  "555001?gh_jid=555001")]}, log_path=log)
    cross_id = out["recorded"][0]["id"] if out["recorded"] else None
    check("d2 setup: the original Jobright find stocks",
          bool(out["recorded"])
          and out["recorded"][0]["state"] == "bench", str(out))
    out = stock.record({"items": [
        full_item("Crossplat Co", "Machine Learning Engineer",
                  "CAREEROPS",
                  "https://boards.greenhouse.io/crossplatco/jobs/"
                  "555001")]}, log_path=log)
    check("d2 CAREEROPS candidate with the same ATS posting id as "
          "an earlier JOBRIGHT find is a cross-platform duplicate "
          "(different title, different board host)",
          len(out["duplicates"]) == 1
          and out["duplicates"][0]["existing_id"] == cross_id
          and out["duplicates"][0]["source"] == "CAREEROPS"
          and not out["recorded"], str(out))

    print(f"\n{'ALL PASS' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}"
          f" ({len(FAILS)} failed)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
