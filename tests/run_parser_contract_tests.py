#!/usr/bin/env python3
"""Trap tests for the prose-log parser contract (the user, Nov 5, 2026).

The #381/#49 bug class: the parser used to mine outcome words anywhere
in an item's text, so a SKIPPED reason containing "verified" counted
as VERIFIED, and shorthand lines like "SEGMENT STATE — gate-passed —
#49 PASS" minted items whose company was a verdict word. The contract
(state.py's PARSER CONTRACT, README.md): outcomes bind ONLY from the
canonical entry grammar — the entry head's closed vocabulary, or a
segment's head clause right after the identity's delimiter — and
everything else is inert.

Every case here is adversarial on purpose: companies named like
outcome words, poisoned reasons, cross-references, corrections,
shorthand lines, Guardian tallies, bold markers, URLs. The fixture is
a synthetic log in a temp file; the live log is never touched.

Run: python3 tests/run_parser_contract_tests.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))

import state as state_mod  # noqa: E402

FAILURES = []


def check(name: str, ok: bool, detail: str = ""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        FAILURES.append(name)


FIXTURE = """# Outreach log (parser-contract trap fixture)

## 2026-11-04 — LinkedIn Recommended applications batch — 2026-11-04: STARTED

- [9:00 AM CST, Wed Nov 4, 2026] STOCKED — #700 Verified, Data Scientist. SOURCE TAG: LINKEDIN.
- [9:05 AM CST, Wed Nov 4, 2026] SUBMITTED (page-confirmed) — #700 Verified, Data Scientist (Greenhouse). Confirmation: page confirmed.
- [9:10 AM CST, Wed Nov 4, 2026] STOCKED — #701 Submitted LLC, Machine Learning Engineer. SOURCE TAG: JOBRIGHT.
- [9:15 AM CST, Wed Nov 4, 2026] SUBMITTED (page-confirmed) — #701 Submitted LLC, Machine Learning Engineer (Ashby). Confirmation: page confirmed.
- [9:20 AM CST, Wed Nov 4, 2026] STOCKED — #702 Acme, Submitted Systems Data Scientist — Remote US. SOURCE TAG: LINKEDIN.
- [9:25 AM CST, Wed Nov 4, 2026] SKIPPED — BELOW CITY-EQUIVALENT PAY (attainable $150,000 is below the bar; note the earlier application here was verified and stands SUBMITTED + EMAIL-VERIFIED in another window) — #703 Poisonco, Data Scientist. (Recorded by spine program.)
- [9:30 AM CST, Wed Nov 4, 2026] STOCKED — #704 Poisonco, Data Scientist. SOURCE TAG: LINKEDIN.
- [9:35 AM CST, Wed Nov 4, 2026] SEGMENT NOTE — #704 Poisonco, Data Scientist is a duplicate of #705, which was SUBMITTED and EMAIL-VERIFIED yesterday; do not re-apply.
- [9:40 AM CST, Wed Nov 4, 2026] SEGMENT STATE — gate-passed — #705 PASS
- [9:45 AM CST, Wed Nov 4, 2026] SEGMENT STATE — #706 Realco, Data Scientist — SUBMITTED (page-confirmed)
- [9:50 AM CST, Wed Nov 4, 2026] STOCKED — #707 Hintco, Data Scientist. SOURCE TAG: LINKEDIN.
- [9:55 AM CST, Wed Nov 4, 2026] SEGMENT STATE — gate-passed — #707 (Hintco; figure 250000)
- [10:00 AM CST, Wed Nov 4, 2026] STOCKED — #708 Smith, Inc., Data Scientist. SOURCE TAG: LINKEDIN.
- [10:05 AM CST, Wed Nov 4, 2026] SUBMITTED (page-confirmed) — #708 Smith, Inc., Data Scientist (Workday). Confirmation: page confirmed.
- [10:10 AM CST, Wed Nov 4, 2026] SUBMITTED (page-confirmed) — #709 Dualco, Data Scientist (Greenhouse). Confirmation: page confirmed.
- [10:15 AM CST, Wed Nov 4, 2026] SUBMITTED (page-confirmed) — #710 Catchup Co, Data Scientist (Ashby). Confirmation: page confirmed.
- [10:20 AM CST, Wed Nov 4, 2026] STOCKED — #711 Boldco, Data Scientist. SOURCE TAG: LINKEDIN.
- [10:25 AM CST, Wed Nov 4, 2026] SEGMENT CLOSE — #711 Boldco remains **SUBMITTED** in the tracker and **EMAIL-VERIFIED** per the portal screenshot; bold words in prose bind nothing.
- [10:30 AM CST, Wed Nov 4, 2026] STOCKED — #712 Urlco, Data Scientist — apply https://jobs.example.com/submitted/apply?state=submitted. SOURCE TAG: LINKEDIN.
- [10:35 AM CST, Wed Nov 4, 2026] DISCOVERY PASS — screened the feed: #713 PASS — Pass Health fits the screen; #714 SKIP — Skipco does not.
- [10:40 AM CST, Wed Nov 4, 2026] SUBMITTED (page-confirmed) — #713 Pass Health, Data Scientist (Greenhouse). Confirmation: page confirmed.
- [10:45 AM CST, Wed Nov 4, 2026] SKIPPED — GATE (size: 40 LinkedIn People members, under-100 hard pass) — #715 Guardco, Data Scientist. (Recorded by spine program.)
Guardian [2026-11-04 3:00 PM CT] (window Nov 4): OK — 39 submitted this window; #716 Otherco EMAIL-VERIFIED per the latest scan.
- Guardian [2026-11-04 3:30 PM CT] (window Nov 4): OK — tally unchanged; #716 Otherco — EMAIL-VERIFIED, still counted.
- [11:00 AM CST, Wed Nov 4, 2026] STOCKED — #717 Corrco, Data Scientist. SOURCE TAG: LINKEDIN.
- [11:05 AM CST, Wed Nov 4, 2026] CORRECTION — #717 Corrco, Data Scientist: for the record, the portal shows this application as SUBMITTED and EMAIL-VERIFIED; noting it here for completeness.
- [11:10 AM CST, Wed Nov 4, 2026] STAGED FOR TAP SESSION — #718 Supco, Data Scientist, Greenhouse form, step: resume upload on the portal form.
- [11:15 AM CST, Wed Nov 4, 2026] CORRECTION — #718 Supco, Data Scientist: the tap-session entry above ("NOT SUBMITTED") was WRONG and is superseded. the user submitted it herself during the takeover; the page confirmed "Thank you for applying" — PAGE-CONFIRMED, counts as VERIFIED under the page-confirmation rule.
- [11:20 AM CST, Wed Nov 4, 2026] TAP SESSION OUTCOMES (main chat): (1) #719 Notsub, Data Scientist — NOT SUBMITTED (the user said skip it, she will not apply); (2) #720 Yessub, Data Scientist — SUBMITTED BY WU HERSELF, page-confirmed on the portal.

## 2026-11-05 — LinkedIn Recommended applications batch — 2026-11-05: STARTED

- [9:00 AM CST, Thu Nov 5, 2026] SUBMITTED (page-confirmed) — #709 Dualco, Data Scientist (Greenhouse). Confirmation: a second, later entry for the same item.
- [9:05 AM CST, Thu Nov 5, 2026] EMAIL-VERIFIED — #710 Catchup Co, Data Scientist: confirmation email arrived overnight.
- [9:10 AM CST, Thu Nov 5, 2026] STOCKED — #721 Verified Health, Data Scientist. SOURCE TAG: LINKEDIN.
- [9:15 AM CST, Thu Nov 5, 2026] SKIPPED — ROLE (not technical; the posting was verified as analytics-only and a SUBMITTED application exists elsewhere) — #721 Verified Health, Data Scientist. (Recorded by spine program.)
- [9:20 AM CST, Thu Nov 5, 2026] STOCKED — #730 Proseco, Data Scientist. SOURCE TAG: LINKEDIN.
- [9:25 AM CST, Thu Nov 5, 2026] SKIPPED — GATE (size: 40 LinkedIn People members, under-100 hard pass) — #730 Proseco, Data Scientist. (Recorded by spine program.)
- [9:30 AM CST, Thu Nov 5, 2026] STOCKED — #731 Plainco, Data Scientist. SOURCE TAG: LINKEDIN.
- [9:35 AM CST, Thu Nov 5, 2026] Some freeform agent note: #731 Plainco, Data Scientist was skipped because the gate failed and it was submitted elsewhere.
- [9:40 AM CST, Thu Nov 5, 2026] STOCKED — #732 Dropco, Data Scientist, Leo Terminal — Redmond, WA — apply: https://www.indeed.com/viewjob?jk=abc123. SOURCE TAG: INDEED. (Recorded by stock program.)
- [9:45 AM CST, Thu Nov 5, 2026] SKIPPED — DUPLICATE company — already applied (duplication screen, before the gate) — dropped — #732 Dropco, Data Scientist. (Recorded by stock program.)
- [9:50 AM CST, Thu Nov 5, 2026] WORKER NOTE (test-worker) — JOBRIGHT-ONLY MODE. Launch verified 0/60. Indeed pass — 1 candidate: Dropco Data Scientist, Leo Terminal, Redmond top $184K — passed code screens but below the $200K city bar, not stocked (already dropped as duplicate #732 today). Discovery passes recorded via the program. After the round, the program returned a WORK ORDER for #731 Plainco (its tailored resume had been prepped by a sibling run) — CLAIMED and FLEW it: submitted page-confirmed on Greenhouse at 4:16 PM CST, tailored resume confirmed attached, recorded via the program (handoff verified:true). Final verified 9/60. Staged []; captcha []; limbo [].
"""


def kinds(st, iid):
    it = st.items.get(iid)
    return [e[2] for e in it.events] if it else []


def main() -> int:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(FIXTURE)
        path = fh.name
    st = state_mod.parse_log(path)
    w4 = {i.id for i in st.window_status("2026-11-04")["verified"]}
    w5 = {i.id for i in st.window_status("2026-11-05")["verified"]}

    it = st.items[700]
    check("company literally named 'Verified' parses by position",
          it.company == "Verified" and it.role == "Data Scientist"
          and it.state == "submitted" and 700 in w4,
          f"(company {it.company!r}, state {it.state})")
    it = st.items[701]
    check("company named 'Submitted LLC' is an identity, not an outcome",
          it.company == "Submitted LLC" and it.state == "submitted"
          and 701 in w4,
          f"(company {it.company!r}, state {it.state})")
    it = st.items[702]
    check("role containing 'Submitted' does not submit the item",
          it.state == "stocked" and "submitted" not in kinds(st, 702)
          and "Submitted" in it.role,
          f"(role {it.role!r}, state {it.state})")
    it = st.items[703]
    check("SKIPPED reason full of outcome words stays skipped (#381)",
          it.state == "skipped" and "submitted" not in kinds(st, 703)
          and 703 not in w4,
          f"(state {it.state}, events {kinds(st, 703)})")
    check("cross-reference to another item's outcome binds nothing",
          705 not in st.items and "submitted" not in kinds(st, 704)
          and st.items[704].state == "stocked",
          f"(#705 items: {705 in st.items}, #704 events {kinds(st, 704)})")
    check("shorthand segment line with a verdict word creates nothing",
          705 not in st.items,
          f"(#705 in items: {705 in st.items})")
    check("shorthand segment line with a real-looking name creates nothing",
          706 not in st.items,
          f"(#706 in items: {706 in st.items})")
    it = st.items[707]
    check("segment hint attaches ONLY to a canonically created item",
          it.gate == "pass" and kinds(st, 707) == ["stocked"],
          f"(gate {it.gate!r}, events {kinds(st, 707)})")
    it = st.items[708]
    check("company with a comma suffix ('Smith, Inc.') splits correctly",
          it.company == "Smith, Inc." and it.role == "Data Scientist"
          and it.state == "submitted" and 708 in w4,
          f"(company {it.company!r}, role {it.role!r})")
    check("same item SUBMITTED in two sections counts once, in the first",
          709 in w4 and 709 not in w5,
          f"(w4 {709 in w4}, w5 {709 in w5})")
    check("EMAIL-VERIFIED in a later section verifies in submission window",
          710 in w4 and 710 not in w5,
          f"(w4 {710 in w4}, w5 {710 in w5})")
    it = st.items[711]
    check("bold outcome words in summary prose are inert",
          it.state == "stocked" and "submitted" not in kinds(st, 711),
          f"(state {it.state}, events {kinds(st, 711)})")
    it = st.items[712]
    check("URL containing 'submitted' is inert",
          it.state == "stocked" and "submitted" not in kinds(st, 712),
          f"(state {it.state}, events {kinds(st, 712)})")
    it = st.items[713]
    check("screening verdict word never becomes the company (#49)",
          it.company == "Pass Health" and it.state == "submitted"
          and 713 in w4,
          f"(company {it.company!r}, state {it.state})")
    check("screening SKIP segment binds no outcome",
          "skipped" not in kinds(st, 714)
          and "submitted" not in kinds(st, 714)
          and st.items.get(714) is not None
          and st.items[714].company != "SKIP",
          f"(#714 events {kinds(st, 714)})")
    it = st.items[715]
    check("Guardian tally line never merges into the preceding entry",
          it.state == "skipped" and "submitted" not in kinds(st, 715)
          and 716 not in st.items,
          f"(#715 state {it.state}, #716 in items: {716 in st.items})")
    it = st.items[717]
    check("CORRECTION containing outcome words (no supersede) is inert",
          it.state == "stocked" and "submitted" not in kinds(st, 717),
          f"(state {it.state}, events {kinds(st, 717)})")
    it = st.items[718]
    check("CORRECTION supersede exception binds its own subject (#198)",
          it.state == "submitted" and 718 in w4,
          f"(state {it.state}, events {kinds(st, 718)})")
    check("NOT SUBMITTED segment binds nothing; its sibling binds",
          "submitted" not in kinds(st, 719)
          and "submitted" in kinds(st, 720),
          f"(#719 {kinds(st, 719)}, #720 {kinds(st, 720)})")
    it = st.items[721]
    check("company named 'Verified Health' + poisoned skip reason: skipped",
          it.company == "Verified Health" and it.state == "skipped"
          and 721 not in w5,
          f"(company {it.company!r}, state {it.state})")
    # Duplicate-guard semantics (the user, Nov 7, 2026): the prose side of
    # the guard binds an outcome ONLY from the canonical outcome-head
    # grammar — the same binding state_check uses to call a prose
    # outcome real. A canonical SKIPPED entry binds; freeform prose
    # mentioning the same words binds nothing, so it can never make
    # the guard refuse a genuine first record.
    it = st.items[730]
    check("canonical SKIPPED entry binds a skipped prose event",
          "skipped" in kinds(st, 730) and it.state == "skipped",
          f"(events {kinds(st, 730)})")
    check("freeform prose binds no outcome (guard stays silent)",
          kinds(st, 731) == ["stocked"]
          and st.items[731].state == "stocked",
          f"(#731 events {kinds(st, 731)})")

    # The #685 phantom (Nov 13, 2026): an item DROPPED by the
    # duplication screen (canonical STOCKED + SKIPPED from the stock
    # program) was counted verified because a later WORKER NOTE
    # mentioned it in passing, then described a sibling's submission
    # without repeating the sibling's #id — the dropped item's
    # segment ran into the sibling's flight prose and its second
    # clause began with "submitted". Worker notes are summaries and
    # bind nothing; the dropped item stays skipped.
    check("worker note binds nothing: screen-dropped item stays "
          "skipped (#685 phantom)",
          kinds(st, 732) == ["stocked", "skipped"]
          and st.items[732].state == "skipped",
          f"(#732 events {kinds(st, 732)})")
    check("worker note binds nothing for the sibling it describes "
          "either (outcomes are canonical entries)",
          "submitted" not in kinds(st, 731),
          f"(#731 events {kinds(st, 731)})")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL PARSER CONTRACT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
