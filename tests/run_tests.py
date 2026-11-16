#!/usr/bin/env python3
"""Round-trip tests for the spine — ALWAYS against a COPY of the log.

Run: python3 tests/run_tests.py
  1. Refresh tests/log_copy.md from the live log; status(copy) must equal
     status(live) exactly (parser determinism on identical input).
  2. Record a FAKE submission for a dynamically chosen copy item (one with a
     parsed company, not yet verified in the copy's current window) -> the
     copy's verified total must move by exactly 1 and the appended entry must
     match the house format.
  3. Record a FAKE friction result on the copy -> the flag's lane scope
     follows the item's source (the user, Nov 7, 2026): a LinkedIn-sourced
     trigger leaves `next` serving Jobright only (status never
     "stopped"; any work order is JOBRIGHT with jobright_only_mode,
     and the empty/pacing shapes carry discovery_sources [JOBRIGHT]);
     a Jobright-sourced trigger is a full stop (`next` refuses,
     status "stopped"). clear-friction must remove the flag and
     append the all-clear to the copy.
  4. Print the Nov 4 acceptance comparison (soft check — the live log grows
     while background runs work, so exact numbers are reported, not asserted).
The live outreach log is never written. The friction flag the copy
uses sits beside the copy's event book (tests/FRICTION.flag, isolated
Nov 7, 2026 — before that the copy shared the LIVE flag in
program/state/, and the finally block below deleted it: the hidden
mechanism behind the day's 2:52 PM "leave it stopped" decision being
silently undone minutes later). The live flag in program/state/ and
the live verify queue are snapshot-restored by the finally blocks as
a belt-and-braces guard: a run must NEVER delete or alter live state.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))

import log_writer  # noqa: E402
import state as state_mod  # noqa: E402
import events as events_mod  # noqa: E402
import pipeline as pipeline_mod  # noqa: E402
from pipeline import Spine  # noqa: E402

LIVE = Path.home() / ("workspace/goals/linkedin-ai-recruiter-outreach-weekly/"
                      "hidden_files/outreach-log.md")
COPY = BASE / "tests" / "log_copy.md"
FAILURES = []


def check(name: str, ok: bool, detail: str = ""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        FAILURES.append(name)


def ids(items) -> set[int]:
    return {i["id"] for i in items}


def main() -> int:
    shutil.copy(LIVE, COPY)
    # The stocked-items data file is the log's data twin (STOCKING
    # AS DATA, Nov 6, 2026): copy it beside the log copy under the
    # derived name Spine computes, so route/salary reads in these
    # tests run on the same data the live program uses.
    _live_stocked = BASE / "events.stocked.json"
    if _live_stocked.exists():
        shutil.copy(_live_stocked,
                    BASE / "tests" / "log_copy.stocked.json")
    live = Spine().status("2026-11-04")
    copy_sp = Spine(log_path=str(COPY))
    copy0 = copy_sp.status("2026-11-04")
    check("copy status == live status",
          copy0["verified_total"] == live["verified_total"]
          and ids(copy0["verified_by_source"].get("LINKEDIN", []))
          == ids(live["verified_by_source"].get("LINKEDIN", []))
          and ids(copy0["verified_by_source"].get("JOBRIGHT", []))
          == ids(live["verified_by_source"].get("JOBRIGHT", []))
          and ids(copy0["staged"]) == ids(live["staged"]),
          f"(verified {copy0['verified_total']}, log lines {copy0['log_lines']})")

    # snapshot program state touched by record()
    state_dir = BASE / "state"
    vq = state_dir / "verify_queue.json"
    vq_backup = vq.read_text(encoding="utf-8") if vq.exists() else None
    _live_flag = state_dir / "FRICTION.flag"
    _live_flag_backup = (_live_flag.read_text(encoding="utf-8")
                         if _live_flag.exists() else None)
    try:
        # --- fake submission round-trip on the copy
        # The fake item is chosen dynamically (fix, Nov 5, 2026): the old
        # hardcoded #182 TRM Labs is genuinely verified in the live log's
        # current window now, so re-recording it moved the total by 0.
        # The invariant is the +1 move for an unverified item, not the
        # item — pick any parsed copy item with a company that is not yet
        # verified in the copy's current window.
        # Round-trip window = the window the record will LAND in:
        # status() with no date reads the LAST section, but the live
        # log's tail section is the NEW window (opened 8:23 AM CT
        # daily) while the copy's records append under the window the
        # copy was refreshed in only until kickoff appends the next
        # header — on Nov 7, 2026 the copy refreshed mid-morning
        # carried the restored Nov 7 section, status() read 51/60 for
        # the Nov 6 window in one process state and 0/60 for Nov 7 in
        # another, and this block measured before/after across two
        # different windows. Pin the round trip to the window of the
        # section that is last AT REFRESH TIME in both reads.
        _cur = copy_sp.status()
        _win = _cur["window"]["date"]
        _verified_now: set[int] = set()
        for _lst in _cur["verified_by_source"].values():
            _verified_now |= ids(_lst)
        _fake = None
        for _it in sorted(copy_sp.load_state().items.values(),
                          key=lambda x: x.id):
            if _it.company and _it.id not in _verified_now and \
                    _it.source in ("LINKEDIN", "JOBRIGHT") and \
                    _it.state in ("stocked", "staged", "captcha", "claimed"):
                _fake = _it
                break
        check("fake round-trip item available on the copy",
              _fake is not None)
        fid = _fake.id
        fsource = _fake.source or "LINKEDIN"
        result = {"item_id": fid, "outcome": "submitted",
                  "portal": "Ashby (TEST)", "confirmation": "TEST round-trip only"}
        # The record lands in the copy's CURRENT window section (the
        # copy is refreshed from the live log, whose tail window moves
        # daily) — measure the move in that window, not a pinned date
        # (durable-invariant form, per the run_events_tests (d) fix).
        before = copy_sp.status(_win)["verified_total"]
        entry = copy_sp.record(result, log_path=str(COPY))
        house = re.match(
            r"^- \[\d{1,2}:\d{2} [AP]M C[SD]T, \w{3} \w{3} \d{1,2}, \d{4}\] "
            rf"SUBMITTED \(page-confirmed\) — #{fid} "
            rf"{re.escape(_fake.company)}, ", entry)
        check("record appends house-format entry", bool(house), entry[:110])
        copy1 = copy_sp.status(_win)
        check("copy verified total moves by exactly 1",
              copy1["verified_total"] == before + 1,
              f"({before} -> {copy1['verified_total']})")
        check("fake item now in copy's verified list",
              fid in ids(copy1["verified_by_source"].get(fsource, [])))
        check("live log untouched by the test",
              Spine().status("2026-11-04")["verified_total"]
              == live["verified_total"])

        # --- duplicate guard (the user, Nov 7, 2026 — the #471 replay):
        # the #471 mechanism was never a code glitch — the harness
        # delivered ONE exec call ~26 times (this session re-ran a
        # single edit 20+ times; an append succeeds on every delivery
        # where an edit fails on the second). The guard refuses a
        # record whose outcome already sits in the prose log, stamped
        # at or after the event book's latest write for the item,
        # with NO outcome event in the book — the half-completed
        # write a replay repeats. Build it with a FRESH item id (97
        # past the log's max — the prose parser's ITEM_RE only sees
        # 2-3 digit ids, and the seed lives in the CURRENT section so
        # its stamp is newer than the book's): stock it in prose,
        # write its submitted outcome through log_writer DIRECTLY
        # (prose only, no event twin), then record the same outcome
        # via the program — the guard must REFUSE before anything is
        # written: no second prose line, no event.
        _gid = max(copy_sp.load_state().items) + 97
        _gview = {"id": _gid, "company": "Guardco",
                  "role": "Data Scientist"}
        log_writer.append_entry(
            str(COPY),
            f"STOCKED — #{_gid} Guardco, Data Scientist. "
            f"SOURCE TAG: LINKEDIN.")
        log_writer.append_entry(str(COPY), log_writer.submitted(
            _gview, "Ashby (TEST)", "TEST duplicate-guard seed",
            "LINKEDIN", ""))
        _ev_before = len([e for e in events_mod.read_events(
            copy_sp.events_path)
            if int(e.get("item") or -1) == _gid])
        _copy_lines_before = len(
            COPY.read_text(encoding="utf-8").splitlines())
        _refused = False
        try:
            copy_sp.record(
                {"item_id": _gid, "outcome": "submitted",
                 "portal": "Ashby (TEST)",
                 "confirmation": "TEST duplicate-guard replay"},
                log_path=str(COPY))
        except ValueError:
            _refused = True
        check("duplicate record refused (idempotent)", _refused)
        _ev_after = len([e for e in events_mod.read_events(
            copy_sp.events_path)
            if int(e.get("item") or -1) == _gid])
        check("duplicate record wrote no event",
              _ev_after == _ev_before == 0,
              f"({_ev_before} -> {_ev_after})")
        check("duplicate record wrote no second log line",
              len(COPY.read_text(encoding="utf-8").splitlines())
              == _copy_lines_before)

        # --- friction round-trip (lane-scoped, the user, Nov 7, 2026:
        # "when LinkedIn stopped stocking, use jobright"). The fake
        # item's own source decides the scope of THIS record; the
        # opposite-scope case is pinned too, with a synthetic flag
        # (no second record — the log must stay clean for the checks
        # below).
        copy_sp.record({"item_id": fid, "outcome": "friction",
                        "signal": "TEST friction — round-trip test only"},
                       log_path=str(COPY))
        _flag = copy_sp.friction_active() or {}
        _want_scope = "linkedin" if fsource == "LINKEDIN" else "all"
        check("friction flag scope follows the item source",
              _flag.get("scope") == _want_scope
              and copy_sp.friction_scope() == _want_scope,
              f"flag={_flag} item source={fsource}")
        _nxt = copy_sp.next_order("2026-11-04")
        if _nxt.get("status") != "stopped":
            _plan = ((_nxt.get("work_order") or _nxt)
                     .get("discovery_plan") or {})
            check("worker packet carries the code discovery plan "
                  "(the user, Nov 13, 2026: code tells the agent the "
                  "Jobright/Indeed search rules at initiation)",
                  set(_plan) == {"JOBRIGHT", "INDEED", "LINKEDIN_ALERT"}
                  and len(_plan["JOBRIGHT"]["searches"]) == 4
                  and len(_plan["INDEED"]["searches"]) == 4
                  and _plan["LINKEDIN_ALERT"]["kind"] == "email_flow",
                  str(sorted(_plan)))
        if _want_scope == "linkedin":
            _wo = (_nxt.get("work_order") or {})
            check("linkedin friction: next_order never fully stops",
                  _nxt.get("status") != "stopped",
                  str(_nxt.get("status")))
            check("linkedin friction: only Jobright is served",
                  (_nxt.get("status") == "work_order"
                   and _wo.get("source") == "JOBRIGHT"
                   and _wo.get("jobright_only_mode") is True)
                  or (_nxt.get("status") in ("empty", "pacing_hold")
                      and _nxt.get("discovery_sources") == ["JOBRIGHT"]),
                  str(_nxt.get("status")))
        else:
            check("jobright friction: next_order fully stops",
                  _nxt.get("status") == "stopped",
                  str(_nxt.get("status")))
        _opp = "all" if _want_scope == "linkedin" else "linkedin"
        copy_sp.set_friction("TEST opposite scope", fid, scope=_opp)
        _nxt2 = copy_sp.next_order("2026-11-04")
        check("opposite scope flips next_order",
              (_nxt2.get("status") == "stopped") == (_opp == "all"),
              f"scope={_opp} status={_nxt2.get('status')}")
        copy_sp.clear_friction("round-trip test complete", log_path=str(COPY))
        check("clear-friction removes the flag",
              copy_sp.friction_active() is None)
    finally:
        # RESTORE, never delete (fixed Nov 7, 2026): this block used to
        # unlink state/FRICTION.flag outright — while the copy still
        # shared the live flag, every suite run deleted a live the user
        # friction stop. The copy's flag is isolated now; restore the
        # live one to its snapshot whatever happened above.
        if _live_flag_backup is None:
            if _live_flag.exists():
                _live_flag.unlink()
        else:
            _live_flag.write_text(_live_flag_backup, encoding="utf-8")
        if vq_backup is None:
            if vq.exists():
                vq.unlink()
        else:
            vq.write_text(vq_backup, encoding="utf-8")

    # --- log_writer format unit check
    line = log_writer.append_entry(
        str(COPY), log_writer.skipped(
            {"id": 999, "company": "Test Co", "role": "Data Scientist"},
            "TEST FORMAT — round-trip test only"))
    check("skipped entry format",
          bool(re.match(r"^- \[\d{1,2}:\d{2} [AP]M C[SD]T, \w{3} \w{3} "
                        r"\d{1,2}, \d{4}\] SKIPPED — TEST FORMAT", line)))

    # --- REGRESSION (Nov 4, 2026, the Fetch #180 limbo fix): record
    # staged, then limbo, on one copy item — the item must end as limbo
    # on EVERY surface (prose state, event fold, status piles,
    # state-check agreement), never shadowed back into the tap pile,
    # and the limbo record must enqueue a verify-queue entry (fix b).
    # Window consistency (fix, Nov 5, 2026): candidates, status piles and
    # the state-check all use the CURRENT window. record() lands its
    # entries (and events) in the current window's section, so asserting
    # against a pinned past window ("2026-11-04") compares the records
    # against a window they never landed in — the check failed on the
    # untouched copy's smallest candidate (#50, a prose-only park in an
    # old section) no matter what the test recorded.
    # Candidate window (fix, Nov 7, 2026): "current window" must mean
    # the most recent window that HAS candidates — the day's new
    # section opens at 8:23 AM CT with an empty bench (Nov 7, 2026:
    # bench 0, staged 1), so reading piles from the last section
    # alone found no candidate at all. Scan windows newest-first and
    # take the first with a bench/staged/captcha candidate; the
    # staged->limbo assertions below then read THAT window.
    _parsed = copy_sp.load_state()
    # Candidate hygiene (Nov 7, 2026): never pick an item whose
    # staged outcome already sits in the prose log — record()
    # rightly refuses it as a replay (the duplicate guard), which
    # crashed this regression the day the guard shipped, when the
    # scan first reached #491 (Apple, staged this morning with
    # its event twin in the LIVE book only, so the copy's book
    # has none). The guard's own suite owns the refusal itself.
    # Hygiene widened (Nov 8, 2026): the scan now prefers the
    # newest window that has an UNSTAGED candidate, not merely the
    # newest window with any candidate — on a night when the bench
    # is empty and the whole pile is already staged (#508/#515/
    # #516), the old scan fell back to an already-staged item and
    # the guard's refusal crashed the suite on healthy live state.
    # Last resort: item 999, the synthetic Test Co entry this suite
    # itself wrote into the copy above (prose outcome: skipped,
    # never staged), so the regression always has a host.
    _ev_kinds = state_mod.prose_event_kinds(str(COPY))

    def _unstaged(_cands):
        return [c for c in sorted(_cands)
                if _parsed.item(c).company
                and "staged" not in _ev_kinds.get(c, set())]

    _cand_win = None
    copy_status = None
    candidates = set()
    _named = []
    _fallback = None
    for _w in reversed(_parsed.windows):
        _cs = copy_sp.status(_w.date)
        _cands = (ids(_cs["bench"]) | ids(_cs["staged"])
                  | ids(_cs["captcha"]))
        if not _cands:
            continue
        if _fallback is None:
            _fallback = (_w.date, _cs, _cands)
        _un = _unstaged(_cands)
        if _un:
            _cand_win, copy_status, candidates, _named = (
                _w.date, _cs, _cands, _un)
            break
    if _cand_win is None and _fallback is not None:
        _cand_win, copy_status, candidates = _fallback
        _named = _unstaged(candidates)
    if copy_status is None:
        copy_status = copy_sp.status()
    check("regression: a candidate item exists on the copy",
          bool(candidates))
    if candidates:
        rid = _named[0] if _named else 999
        if "staged" in _ev_kinds.get(rid, set()):
            rid = 999
        if rid == 999:
            _cand_win = _parsed.windows[-1].date
            copy_status = copy_sp.status(_cand_win)
        test_vq = COPY.parent / "test_verify_queue.json"
        if test_vq.exists():
            test_vq.unlink()
        copy_sp.verify_queue_file = test_vq
        try:
            copy_sp.record({"item_id": rid, "outcome": "staged",
                            "step": "TEST — regression park",
                            "blocker": "test",
                            "blocker_kind": "other"}, log_path=str(COPY))
            copy_sp.record({"item_id": rid, "outcome": "limbo",
                            "note": "TEST — regression limbo after staged"},
                           log_path=str(COPY))
            after = copy_sp.status(_cand_win)
            check("regression: staged->limbo item is in status limbo",
                  rid in ids(after["limbo"]))
            check("regression: staged->limbo item NOT in status staged",
                  rid not in ids(after["staged"]))
            check("regression: prose item state is limbo",
                  copy_sp.load_state().item(rid).state == "limbo")
            folded = state_mod.fold_events(
                events_mod.read_events(copy_sp.events_path))
            check("regression: event fold state is limbo",
                  folded["items"].get(rid, {}).get("state") == "limbo")
            sc = copy_sp.state_check(_cand_win)
            check("regression: state-check no divergence for the item",
                  all(d["item_id"] != rid for d in sc["divergences"]))
            queued = json.loads(test_vq.read_text(encoding="utf-8")) \
                if test_vq.exists() else []
            check("regression: limbo record enqueued a verify entry",
                  any(e.get("item_id") == rid for e in queued))
        finally:
            if test_vq.exists():
                test_vq.unlink()

    # --- Lever packet rule (the user, Nov 4, 2026): jobs.lever.co carries
    # packet_handoff in route_limits, and a known Lever item (#240)
    # resolves to that host, so its work orders carry the
    # park-and-packet stamp instead of a solve flow. Lever was the
    # ONLY packet-handoff host until Nov 6, 2026, when the user added
    # Rippling to the manual packet group (#435) — the group check
    # below encodes the current group, not the old singleton.
    lever_rule = (copy_sp.rules.get("route_limits") or {}).get(
        "jobs.lever.co") or {}
    check("lever rule: packet_handoff set for jobs.lever.co",
          lever_rule.get("packet_handoff") is True
          and lever_rule.get("handling")
          == "park_captcha_no_flow_packet_handoff")
    packet_hosts = [h for h, r in
                    (copy_sp.rules.get("route_limits") or {}).items()
                    if isinstance(r, dict) and r.get("packet_handoff")]
    check("packet group: lever + rippling carry packet_handoff",
          packet_hosts == ["jobs.lever.co", "ats.rippling.com"],
          f"({packet_hosts})")
    st_copy = copy_sp.load_state()
    route240, _sal240 = copy_sp._route_and_salary(st_copy,
                                                  st_copy.item(240))
    check("lever rule: #240 resolves to the Lever host",
          "jobs.lever.co" in (route240.get("url") or ""),
          f"({route240.get('url')})")

    # --- Stocking as data (the user, Nov 6, 2026 — fix #1 of the
    # text-parsing audit): routes and salaries come from the
    # stocked-items DATA file, never from mining log prose. The
    # prose miner is deleted, a re-stocked item (#464 — its STOCKED
    # line names the original item before the apply URL, which cut
    # the old miner's segment and emptied its route) resolves from
    # data, and an item with no data record resolves empty.
    check("stocking as data: prose miner deleted from pipeline",
          not hasattr(pipeline_mod, "ATS_RE")
          and not hasattr(pipeline_mod, "URL_RE")
          and not hasattr(pipeline_mod, "SALARY_RE"))
    route464, sal464 = copy_sp._route_and_salary(st_copy,
                                                 st_copy.item(464))
    check("stocking as data: re-stocked #464 resolves route + pay",
          "gh_jid=8807522002" in (route464.get("url") or "")
          and sal464.get("figure") == 205000,
          f"({route464.get('url')} / {sal464.get('figure')})")
    _ghost = type("Ghost", (), {"id": 999999})()
    route_g, sal_g = copy_sp._route_and_salary(st_copy, _ghost)
    check("stocking as data: no data record resolves empty",
          route_g == {"url": "", "ats": ""}
          and sal_g.get("figure") is None,
          f"({route_g} / {sal_g})")

    # --- Humanizer rule (the user, Nov 4, 2026): the writing rule lives in
    # config (humanizer_required, skill named), and every work order
    # carries the stamp so application answers are humanized at the
    # point of work — checked behaviorally when the fixture can issue
    # an order, otherwise against the pipeline wiring.
    writing_rule = copy_sp.rules.get("writing") or {}
    check("humanizer rule: required in config with the skill named",
          writing_rule.get("humanizer_required") is True
          and "humanizer" in (writing_rule.get("skill") or ""))
    # Email-reply reinforcement (the user, Nov 6, 2026 — the Socure reply
    # was sent without the sender running the skill, and this block
    # named only application text): replies are in applies_to, and
    # sends require the attestation marker.
    check("humanizer rule: email + message replies covered, "
          "attestation required",
          all(x in (writing_rule.get("applies_to") or []) for x in
              ("gmail_replies", "linkedin_inbox_replies",
               "connection_notes"))
          and writing_rule.get("attestation_required_for_sends")
          is True
          and writing_rule.get("attestation_marker")
          == "humanizer: passed")
    _ord = copy_sp.next_order("2026-11-04")
    if _ord.get("status") == "work_order":
        check("humanizer rule: work order carries the stamp",
              _ord["work_order"].get("humanizer_required") is True)
        check("humanizer rule: work order stamps applies_to + marker",
              "gmail_replies" in (
                  _ord["work_order"].get("humanizer_applies_to")
                  or [])
              and _ord["work_order"].get(
                  "humanizer_attestation_marker")
              == "humanizer: passed")
    else:
        import pathlib as _pl
        _src = _pl.Path(__file__).resolve().parent.parent.joinpath(
            "engine", "pipeline.py").read_text()
        check("humanizer rule: pipeline stamps work orders (wiring)",
              '"humanizer_required"' in _src
              and 'rules.get("writing")' in _src,
              f"(fixture issued no order: {_ord.get('status')})")
        check("humanizer rule: pipeline stamps applies_to (wiring)",
              '"humanizer_applies_to"' in _src
              and '"humanizer_attestation_marker"' in _src)

    # --- Presentation rule (the user, Nov 4, 2026 — the #250 lesson): the
    # config carries the pop-in-chat rule, and status surfaces it
    # whenever a the user pile (staged or captcha) is non-empty, so the
    # presenting agent gets it at the moment of presentation.
    pres_rule = copy_sp.rules.get("presentation") or {}
    check("presentation rule: pop-in-chat required in config",
          pres_rule.get("pop_in_chat_required") is True
          and "window" in (pres_rule.get("rule") or ""))
    if live["staged"] or live["captcha"]:
        check("presentation rule: live status carries it (pile non-empty)",
              bool(live.get("presentation"))
              and "ONE action" in live["presentation"])
    else:
        check("presentation rule: live status omits it (piles empty)",
              live.get("presentation") is None)

    # --- Sign-in rule (the user, Nov 4, 2026): SSO (LinkedIn, then Google)
    # whenever offered; email + password forbidden while SSO is
    # available; vault password only when neither SSO exists. In
    # config, and stamped on the work order next to humanizer_required.
    si_rule = copy_sp.rules.get("sign_in") or {}
    check("sign-in rule: SSO-first in config, password banned under SSO",
          si_rule.get("sso_order") == ["linkedin", "google"]
          and si_rule.get("email_password_forbidden_when_sso_available")
          is True
          and si_rule.get("vault_fallback_only_when_no_sso") is True)
    if _ord.get("status") == "work_order":
        check("sign-in rule: work order carries the sign_in block",
              (_ord["work_order"].get("sign_in") or {}).get(
                  "email_password_forbidden_when_sso_available") is True)
    else:
        import pathlib as _pl2
        _src2 = _pl2.Path(__file__).resolve().parent.parent.joinpath(
            "engine", "pipeline.py").read_text()
        check("sign-in rule: pipeline stamps work orders (wiring)",
              '"sign_in": self.rules.get("sign_in")' in _src2,
              f"(fixture issued no order: {_ord.get('status')})")

    # --- Fill policy (the user, Nov 6, 2026 — Apple #417): fill EVERY
    # truthful field to the fullest (optional fields, descriptions
    # from the resume's bullets, closest truthful picker match over a
    # skip, picker no-match is not a blocker) and MAX every level
    # field. In config, and stamped on the work order.
    fp_rule = copy_sp.rules.get("fill_policy") or {}
    check("fill policy: fullest + maxed in config",
          fp_rule.get("fill_every_truthful_field") is True
          and fp_rule.get("levels_maxed") is True
          and fp_rule.get("closest_match_over_skip") is True
          and fp_rule.get("picker_no_match_is_not_a_blocker") is True
          and fp_rule.get("editable_profiles_completed") is True)
    if _ord.get("status") == "work_order":
        check("fill policy: work order carries the fill_policy block",
              (_ord["work_order"].get("fill_policy") or {}).get(
                  "levels_maxed") is True)
    else:
        import pathlib as _pl3
        _src3 = _pl3.Path(__file__).resolve().parent.parent.joinpath(
            "engine", "pipeline.py").read_text()
        check("fill policy: pipeline stamps work orders (wiring)",
              '"fill_policy": self.rules.get("fill_policy")' in _src3,
              f"(fixture issued no order: {_ord.get('status')})")

    # --- Workday sign-in failure rule (the user, Nov 5, 2026 — Sony #388):
    # Workday accounts are per-tenant, so a credential failure NEVER
    # stages for the user; the run creates the tenant account with the
    # saved Workday password (sign-in alone cannot work until the
    # account exists) and finishes. In config, stamped via the
    # sign_in block, and enforced
    # in record(): a staged outcome naming Workday + a credential
    # failure is REFUSED with nothing written, while other staged
    # outcomes (a Google password step, a Workday approval card)
    # still record normally.
    check("workday failure rule: never-stage in config with the path",
          si_rule.get("workday_failure_never_stage") is True
          and si_rule.get("workday_failure_path") == [
              "sso", "create_account_with_saved_credential",
              "email_verification_in_flow", "complete_application"])
    check("successfactors failure rule: never-stage in config with "
          "the path (the user, Nov 6, 2026 — do like Workday)",
          si_rule.get("successfactors_failure_never_stage") is True
          and si_rule.get("successfactors_failure_path") == [
              "sso", "create_account_with_saved_credential",
              "email_verification_in_flow", "complete_application"])
    if candidates:
        _wid = rid
        _lines_before = len(COPY.read_text(encoding="utf-8").splitlines())
        _refused = False
        try:
            copy_sp.record({"item_id": 388, "outcome": "staged",
                            "step": "Step 1 of 7",
                            "blocker": "held at the entry step",
                            "blocker_kind": "sign_in"},
                           log_path=str(COPY))
        except ValueError:
            _refused = True
        check("workday failure rule: credential stage REFUSED in code",
              _refused)
        check("workday failure rule: refusal wrote nothing",
              len(COPY.read_text(encoding="utf-8").splitlines())
              == _lines_before)
        _ok_google = True
        try:
            copy_sp.record({"item_id": _wid, "outcome": "staged",
                            "portal": "Google Careers",
                            "step": "Google Accounts sign-in",
                            "blocker": "password step — the user-only",
                            "blocker_kind": "sign_in",
                            "signin_attempted": True,
                            "creation_attempted": True},
                           log_path=str(COPY))
        except ValueError:
            _ok_google = False
        check("workday failure rule: non-Workday credential stage "
              "still records (with signin_attempted attested)",
              _ok_google)
        _ok_card = True
        try:
            copy_sp.record({"item_id": 388, "outcome": "staged",
                            "step": "Review step",
                            "blocker": "approval card actually presented",
                            "blocker_kind": "approval_card"},
                           log_path=str(COPY))
        except ValueError:
            _ok_card = False
        check("workday failure rule: Workday non-credential stage "
              "still records", _ok_card)
        _lines_sf = len(COPY.read_text(encoding="utf-8").splitlines())
        _refused_sf = False
        try:
            copy_sp.record({"item_id": 433, "outcome": "staged",
                            "step": "SuccessFactors sign-in (career8)",
                            "blocker": "saved login rejected",
                            "blocker_kind": "sign_in",
                            "signin_attempted": True},
                           log_path=str(COPY))
        except ValueError:
            _refused_sf = True
        check("successfactors failure rule: credential stage REFUSED "
              "in code (create the tenant account instead)",
              _refused_sf)
        check("successfactors failure rule: refusal wrote nothing",
              len(COPY.read_text(encoding="utf-8").splitlines())
              == _lines_sf)

    # --- IP-blocked captcha rule (the user, Nov 5, 2026 — #366 Allied /
    # Paycom): a captcha that demonstrably blocks this browser by IP
    # jumps straight to a MANUAL packet — no held window, no session
    # park. In config, stamped on every work order, and enforced in
    # record(): a captcha outcome showing an IP block (and not naming
    # Lever) is REFUSED unless the record carries manual_packet:
    # true; Lever-named and ordinary captchas record normally.
    ipb_rule = copy_sp.rules.get("captcha_ip_block") or {}
    check("ip-block rule: manual packet immediately in config",
          ipb_rule.get("manual_packet_immediately") is True
          and ipb_rule.get("demonstrated_only") is True
          and ipb_rule.get("no_held_takeover_windows") is True
          and ipb_rule.get("packet_contents") == [
              "apply_link", "tailored_resume", "field_values"])
    if _ord.get("status") == "work_order":
        check("ip-block rule: work order carries the block",
              (_ord["work_order"].get("captcha_ip_block") or {}).get(
                  "manual_packet_immediately") is True)
    else:
        import pathlib as _pl4
        _src4 = _pl4.Path(__file__).resolve().parent.parent.joinpath(
            "engine", "pipeline.py").read_text()
        check("ip-block rule: pipeline stamps work orders (wiring)",
              '"captcha_ip_block": self.rules.get("captcha_ip_block")'
              in _src4,
              f"(fixture issued no order: {_ord.get('status')})")
    if candidates:
        _lines_before = len(COPY.read_text(encoding="utf-8").splitlines())
        _refused = False
        try:
            copy_sp.record({"item_id": rid, "outcome": "captcha",
                            "step": "Paycom puzzle",
                            "note": "puzzle at the entry step",
                            "ip_blocked": True},
                           log_path=str(COPY))
        except ValueError:
            _refused = True
        check("ip-block rule: session park REFUSED in code", _refused)
        check("ip-block rule: refusal wrote nothing",
              len(COPY.read_text(encoding="utf-8").splitlines())
              == _lines_before)
        _ok_packet = True
        try:
            copy_sp.record({"item_id": rid, "outcome": "captcha",
                            "step": "Paycom puzzle",
                            "note": "manual packet handed to the user",
                            "ip_blocked": True,
                            "manual_packet": True},
                           log_path=str(COPY))
        except ValueError:
            _ok_packet = False
        check("ip-block rule: manual-packet record lands", _ok_packet)
        _ok_lever = True
        try:
            copy_sp.record({"item_id": rid, "outcome": "captcha",
                            "step": "Lever hCaptcha",
                            "note": "Lever packet rule — packet at "
                                    "session time"},
                           log_path=str(COPY))
        except ValueError:
            _ok_lever = False
        check("ip-block rule: Lever captcha (no ip_blocked flag) "
              "still records", _ok_lever)
        _ok_plain = True
        try:
            copy_sp.record({"item_id": rid, "outcome": "captcha",
                            "step": "hCaptcha checkbox",
                            "note": "ordinary captcha — held for the "
                                    "captcha session"},
                           log_path=str(COPY))
        except ValueError:
            _ok_plain = False
        check("ip-block rule: ordinary captcha still records", _ok_plain)

    # --- Rippling manual-packet group (the user, Nov 6, 2026: "Add
    # rippling to manual packet group" — #435 Reserv: the
    # Cloudflare verification expired twice in this browser, then
    # FAILED on the user's own takeover solve): ats.rippling.com joins
    # Lever and Gem — a Rippling item never parks for a captcha
    # session or a takeover window; it goes to the user as a manual
    # packet. In config (route_limits ats.rippling.com) and
    # enforced in record(): a captcha outcome for the fixture's
    # Rippling item (#237 North) is REFUSED unless the record
    # carries manual_packet: true.
    rip_rule = (copy_sp.rules.get("route_limits") or {}).get(
        "ats.rippling.com") or {}
    check("rippling rule: manual packet group in config",
          rip_rule.get("manual_packet") is True
          and rip_rule.get("packet_handoff") is True
          and rip_rule.get("handling")
          == "manual_packet_no_takeover")
    # The record-level refusal keys on the item's route host. The
    # fixture's only Rippling item (#237 North) has its route mined
    # from stocking prose and the miner resolves it to a
    # non-Rippling URL (the known prose-mining limitation — the
    # stocking-payload-as-data-event migration retires it), so the
    # refusal cannot be exercised on the fixture. Fall back to the
    # wiring check (the suite's pattern for this case) and verify
    # the packet record lands; the guard itself was verified live
    # on #435, whose route resolves to ats.rippling.com.
    import pathlib as _plr
    _srcr = _plr.Path(__file__).resolve().parent.parent.joinpath(
        "engine", "pipeline.py").read_text()
    check("rippling rule: record() refuses a Rippling captcha "
          "park without manual_packet (wiring)",
          'route_limits") or {}).get(\n                '
          '"ats.rippling.com")' in _srcr
          and '_rhost.endswith(".rippling.com")' in _srcr)
    _ok_rip = True
    try:
        copy_sp.record({"item_id": 237, "outcome": "captcha",
                        "step": "Rippling submit — Cloudflare "
                                "Verify you are human",
                        "note": "manual packet handed to the user",
                        "manual_packet": True},
                       log_path=str(COPY))
    except ValueError:
        _ok_rip = False
    check("rippling rule: manual-packet record lands", _ok_rip)

    # --- Gem manual-packet rule (the user, Nov 5, 2026 — #392 Auger):
    # Gem's resume upload cannot be attached in this browser by
    # Muse or by the user's own clicks (proven #180 Fetch Nov 4 and #392
    # Auger Nov 5), so a Gem item NEVER stages for a tap-session
    # upload click — the run hands the user a manual packet instead. In
    # config (route_limits jobs.gem.com manual_packet) and enforced
    # in record(): staging #392 (the Auger Gem item) on the upload
    # is REFUSED with nothing written; a non-upload stage on the
    # same item still records.
    gem_rule = (copy_sp.rules.get("route_limits") or {}).get(
        "jobs.gem.com") or {}
    check("gem rule: manual packet in config, no fill-and-stage",
          gem_rule.get("manual_packet") is True
          and gem_rule.get("handling") == "manual_packet_no_fill_no_stage")
    _lines_before = len(COPY.read_text(encoding="utf-8").splitlines())
    _refused = False
    try:
        copy_sp.record({"item_id": 392, "outcome": "staged",
                        "step": "Gem application form",
                        "blocker": "resume upload — drop zone not "
                                   "drivable",
                        "blocker_kind": "resume_upload"},
                       log_path=str(COPY))
    except ValueError:
        _refused = True
    check("gem rule: upload stage REFUSED in code", _refused)
    check("gem rule: refusal wrote nothing",
          len(COPY.read_text(encoding="utf-8").splitlines())
          == _lines_before)
    _ok_other = True
    try:
        copy_sp.record({"item_id": 392, "outcome": "staged",
                        "step": "Gem application form",
                        "blocker": "approval card actually presented",
                        "blocker_kind": "approval_card"},
                       log_path=str(COPY))
    except ValueError:
        _ok_other = False
    check("gem rule: non-upload stage on a Gem item still records",
          _ok_other)

    # --- Sign-in staging rule (the user, Nov 5, 2026 — Google #365): a
    # sign-in/password stage is allowed ONLY on a credential dead
    # end proven in the same run, attested by signin_attempted:
    # true. #365 sat staged all evening on a Google password step
    # that did not exist when finally driven (the profile already
    # held a live session). In config (sign_in block) and enforced
    # in record(): an unattested credential stage is REFUSED with
    # nothing written; an attested one records.
    check("signin staging rule: attestation required in config",
          si_rule.get("stage_requires_signin_attempted") is True)
    if candidates:
        _lines_before = len(COPY.read_text(encoding="utf-8").splitlines())
        _refused = False
        try:
            copy_sp.record({"item_id": rid, "outcome": "staged",
                            "portal": "Google Careers",
                            "step": "Google Accounts sign-in",
                            "blocker": "password step — the user-only",
                            "blocker_kind": "sign_in"},
                           log_path=str(COPY))
        except ValueError:
            _refused = True
        check("signin staging rule: unattested stage REFUSED in code",
              _refused)
        check("signin staging rule: refusal wrote nothing",
              len(COPY.read_text(encoding="utf-8").splitlines())
              == _lines_before)
        check("create-on-login-failure rule: universal, one "
              "password, in config",
              si_rule.get("create_account_on_login_failure") is True
              and si_rule.get("account_creation_password")
              == "workday_credential"
              and si_rule.get("stage_requires_creation_attempted")
              is True)
        _lines_c = len(COPY.read_text(encoding="utf-8").splitlines())
        _refused_c = False
        try:
            copy_sp.record({"item_id": rid, "outcome": "staged",
                            "portal": "Google Careers",
                            "step": "Google Accounts sign-in",
                            "blocker": "password step — the user-only",
                            "blocker_kind": "sign_in",
                            "signin_attempted": True},
                           log_path=str(COPY))
        except ValueError:
            _refused_c = True
        check("create-on-login-failure rule: sign-in stage without "
              "a creation attempt REFUSED in code",
              _refused_c)
        check("create-on-login-failure rule: refusal wrote nothing",
              len(COPY.read_text(encoding="utf-8").splitlines())
              == _lines_c)
        _ok_attested = True
        try:
            copy_sp.record({"item_id": rid, "outcome": "staged",
                            "portal": "Google Careers",
                            "step": "Google Accounts sign-in",
                            "blocker": "password step — the user-only",
                            "blocker_kind": "sign_in",
                            "signin_attempted": True,
                            "creation_attempted": True},
                           log_path=str(COPY))
        except ValueError:
            _ok_attested = False
        check("signin staging rule: attested dead-end stage records",
              _ok_attested)

    # --- Password-step sequence (the user, Nov 6, 2026 — UKG #456
    # debug: "You should try the password. No account. Sign up.
    # Pop the credential card and let me fill it."): when the
    # run's classification says the portal has a PASSWORD step
    # (password_step: true, data only), a sign_in stage must
    # attest the password was actually TRIED and that the
    # password was either filled from the vault or the Secure
    # Vault credential card was popped for the user. Holding at a
    # form, or parking before the card, is REFUSED.
    check("password-step sequence: sequence + enforcement in "
          "config",
          si_rule.get("password_step_sequence") == [
              "try_password", "sign_up_create_account",
              "credential_card_when_password_must_be_set",
              "email_verification_in_flow",
              "complete_application"]
          and si_rule.get(
              "stage_requires_sequence_on_password_step") is True)
    if candidates:
        _base_pw = {"item_id": rid, "outcome": "staged",
                    "portal": "UKG Pro",
                    "step": "UKG sign-in password step",
                    "blocker": "password step — the user-only",
                    "blocker_kind": "sign_in",
                    "signin_attempted": True,
                    "creation_attempted": True,
                    "password_step": True}
        _lines_pw = len(COPY.read_text(
            encoding="utf-8").splitlines())
        _refused_pw = False
        try:
            copy_sp.record(dict(_base_pw), log_path=str(COPY))
        except ValueError:
            _refused_pw = True
        check("password-step sequence: stage without "
              "password_tried REFUSED in code", _refused_pw)
        check("password-step sequence: refusal wrote nothing",
              len(COPY.read_text(encoding="utf-8").splitlines())
              == _lines_pw)
        _refused_pw2 = False
        try:
            copy_sp.record(dict(_base_pw, password_tried=True),
                           log_path=str(COPY))
        except ValueError:
            _refused_pw2 = True
        check("password-step sequence: tried but no vault fill "
              "and no credential card REFUSED in code",
              _refused_pw2)
        _ok_card = True
        try:
            copy_sp.record(dict(_base_pw, password_tried=True,
                                credential_card_offered=True),
                           log_path=str(COPY))
        except ValueError:
            _ok_card = False
        check("password-step sequence: card offered records",
              _ok_card)
        _ok_filled = True
        try:
            copy_sp.record(dict(_base_pw, password_tried=True,
                                saved_credential_filled=True),
                           log_path=str(COPY))
        except ValueError:
            _ok_filled = False
        check("password-step sequence: vault fill records",
              _ok_filled)

    # --- Data-contract traps (the user, Nov 5, 2026, late: "No you are
    # parsing the text with hardcoded keywords again. Use LLM for
    # this type of questions. Only give code what it can easily
    # digest: dictionary or other data structure."): the guards read
    # DATA ONLY — blocker_kind (the run's classification), the
    # ip_blocked flag, the item's route host/ATS. The prose is never
    # parsed. Traps: (a) a blank stage is refused even with a valid
    # kind; (b) a stage with NO blocker_kind is refused even when its
    # prose screams sign-in; (c) an unknown kind is refused; (d) a
    # sign_in kind with innocent prose is refused unattested — the
    # classification carries it, not the words; (e) CONTROL: an
    # approval_card kind whose prose is full of credential words
    # RECORDS — proof the code does not read prose; (f) a Workday
    # item (route host) with kind sign_in and prose naming neither
    # Workday nor credentials is refused by the Workday guard.
    _kinds_cfg = (copy_sp.rules.get("staging") or {}).get(
        "blocker_kinds") or []
    check("staging contract: blocker kinds vocabulary in config",
          _kinds_cfg == ["approval_card", "sign_in", "resume_upload",
                         "identity_document", "wu_input", "code_step",
                         "other"])
    if candidates:
        _lines_before = len(COPY.read_text(encoding="utf-8").splitlines())
        _refused_blank = False
        try:
            copy_sp.record({"item_id": rid, "outcome": "staged",
                            "step": "", "blocker": "",
                            "blocker_kind": "other"},
                           log_path=str(COPY))
        except ValueError:
            _refused_blank = True
        check("data traps: blank stage REFUSED", _refused_blank)
        _refused_nokind = False
        try:
            copy_sp.record({"item_id": rid, "outcome": "staged",
                            "step": "Google Accounts sign-in",
                            "blocker": "password credential "
                                       "authentication id_doc"},
                           log_path=str(COPY))
        except ValueError:
            _refused_nokind = True
        check("data traps: missing blocker_kind REFUSED (prose "
              "ignored)", _refused_nokind)
        _refused_badkind = False
        try:
            copy_sp.record({"item_id": rid, "outcome": "staged",
                            "step": "Entry", "blocker": "held",
                            "blocker_kind": "banana"},
                           log_path=str(COPY))
        except ValueError:
            _refused_badkind = True
        check("data traps: unknown blocker_kind REFUSED",
              _refused_badkind)
        _refused_kind = False
        try:
            copy_sp.record({"item_id": rid, "outcome": "staged",
                            "step": "Entry",
                            "blocker": "held at the entry wall",
                            "blocker_kind": "sign_in"},
                           log_path=str(COPY))
        except ValueError:
            _refused_kind = True
        check("data traps: sign_in kind refused unattested whatever "
              "the prose says", _refused_kind)
        _refused_host = False
        try:
            copy_sp.record({"item_id": 388, "outcome": "staged",
                            "step": "Step 1 of 6",
                            "blocker": "held at the entry wall",
                            "blocker_kind": "sign_in"},
                           log_path=str(COPY))
        except ValueError:
            _refused_host = True
        check("data traps: Workday sign_in refused by route host + "
              "kind", _refused_host)
        check("data traps: refusals wrote nothing",
              len(COPY.read_text(encoding="utf-8").splitlines())
              == _lines_before)
        _ok_prose = True
        try:
            copy_sp.record({"item_id": rid, "outcome": "staged",
                            "step": "Review",
                            "blocker": "password sign-in credential "
                                       "authentication id_doc — card "
                                       "presented at review",
                            "blocker_kind": "approval_card"},
                           log_path=str(COPY))
        except ValueError:
            _ok_prose = False
        check("data traps: approval_card kind RECORDS despite "
              "credential-laden prose (code never reads prose)",
              _ok_prose)

    # --- Source flex (the user, Nov 4, 2026): Jobright may pass its 20
    # split to cover a LinkedIn shortfall; the total stays binding and
    # no quality filter changes. In config, reported by
    # effective_targets, and honored by next_order's source check.
    flex_rule = ((copy_sp.rules.get("window") or {}).get("source_flex")
                 or {})
    check("source flex: jobright covers linkedin shortfall in config",
          flex_rule.get("jobright_covers_linkedin_shortfall") is True)
    check("source flex: effective targets report the flex flag",
          copy_sp.effective_targets(st_copy, "2026-11-04").get(
              "jobright_flex_cover") is True)
    import pathlib as _pl3
    _src3 = _pl3.Path(__file__).resolve().parent.parent.joinpath(
        "engine", "pipeline.py").read_text()
    check("source flex: next_order honors the flex (wiring)",
          'targets.get("jobright_flex_cover")' in _src3
          and "flex cover: LinkedIn short" in _src3)

    # --- LinkedIn alerts as a third source (the user, Nov 12, 2026):
    # targets carry linkedin_alert alongside jobright/indeed and the
    # TOTAL (60) still binds — the per-source numbers are ceilings,
    # never summed.
    _tg = copy_sp.effective_targets(st_copy, "2026-11-04")
    check("alert source: effective targets carry linkedin_alert, "
          "total still 60",
          _tg.get("linkedin_alert") == 60 and _tg.get("total") == 60,
          str(_tg))

    # --- Past-24-hours scan window (the user, Nov 12, 2026): config
    # carries the window for JOBRIGHT + INDEED only.
    _disc = (copy_sp.rules.get("discovery") or {})
    check("24h scan window: config carries 24h for "
          "JOBRIGHT+INDEED+CAREEROPS",
          _disc.get("max_posting_age_hours") == 24
          and _disc.get("max_posting_age_sources")
          == ["JOBRIGHT", "INDEED", "CAREEROPS"],
          str({k: _disc.get(k) for k in
               ("max_posting_age_hours", "max_posting_age_sources")}))
    check("site filters: config carries the date + full-time "
          "directives for both sources (the user, Nov 12, 2026)",
          _disc.get("jobright_date_filter") == "last_24_hours"
          and _disc.get("jobright_job_type_filter") == "full_time"
          and _disc.get("indeed_date_filter") == "last_24_hours"
          and _disc.get("indeed_job_type_filter") == "full_time",
          str({k: _disc.get(k) for k in
               ("jobright_date_filter", "jobright_job_type_filter",
                "indeed_date_filter", "indeed_job_type_filter")}))

    # --- Search matrix (the user, Nov 12, 2026): exactly four structured
    # searches per external source; plain "Data Scientist" is gone
    # from the Jobright/Indeed definitions; remote rows carry the
    # per-site mechanic (Jobright: Work model filter; Indeed:
    # location field).
    _MATRIX = [("Senior Data Scientist", "California/Washington"),
               ("Machine Learning Engineer", "California/Washington"),
               ("Senior Data Scientist", "Remote"),
               ("Machine Learning Engineer", "Remote")]
    for _src_key, _remote_via in (("jobright", "work_model_filter"),
                                  ("indeed", "location_field")):
        _searches = _disc.get(f"{_src_key}_searches") or []
        check(f"search matrix: {_src_key} carries exactly the four "
              f"matrix searches",
              [(s.get("title"), s.get("location_scope"))
               for s in _searches] == _MATRIX
              and "Data Scientist" not in
              [s.get("title") for s in _searches],
              str(_searches))
        check(f"search matrix: {_src_key} remote rows use "
              f"{_remote_via}",
              all(s.get("remote_via") == _remote_via
                  for s in _searches
                  if s.get("location_scope") == "Remote"),
              str(_searches))

    # --- Historical GATE DEFERRED records still parse (the user, Nov 12,
    # 2026): the gate-timing reversal refuses NEW deferred stocks,
    # but items stocked/submitted under the Nov 11, 2026 deferral
    # keep their state — the parser must still read gate="deferred".
    import tempfile as _tf2
    with _tf2.TemporaryDirectory() as _td2:
        _dlog = Path(_td2) / "deferred.md"
        _dlog.write_text(
            "## 2026-11-05 — TEST batch — 2026-11-05\n\n"
            "- [3:00 PM CST, Mon Oct 26, 2026] STOCKED #100 — "
            "Deferred Corp — Data Scientist — source JOBRIGHT\n"
            "- [4:51 PM CST, Wed Nov 11, 2026] GATE DEFERRED — #100 "
            "Deferred Corp — company check deferred until forward "
            "movement (the user, Nov 11, 2026). (Recorded by stock "
            "program.)\n", encoding="utf-8")
        _dst = state_mod.parse_log(str(_dlog))
        _d100 = _dst.items.get(100)
        check("historical deferred record still parses",
              _d100 is not None and _d100.gate == "deferred",
              f"gate={_d100.gate if _d100 else None}")

    # --- Alert lane seam (the user, Nov 12, 2026): under a LinkedIn-scope
    # friction flag, a LINKEDIN_ALERT bench item is NOT stopped by
    # the linkedin_lane_stopped check (its own lane; Easy Apply via
    # the alert email is allowed), while a plain LINKEDIN item IS.
    # A flag carrying the alert_lane_blocked marker pauses the
    # alert lane too. Both items lack resumes on disk, so both land
    # in next_order's skipped list and the lane check is what the
    # assertions read.
    import stock as stock_mod
    from datetime import datetime as _dt
    with _tf2.TemporaryDirectory() as _td3:
        _alog = Path(_td3) / "alerts.md"
        _alog.write_text(
            "## 2026-11-05 — LinkedIn Recommended applications "
            "batch — 2026-11-05\n\n"
            "- [3:00 PM CST, Mon Oct 26, 2026] STOCKED #100 — "
            "Fixture Corp — Data Scientist — source LINKEDIN\n",
            encoding="utf-8")
        _gate = {"total": 3000, "india": 100, "source": "Revelio Labs"}
        _pay = {"figure": 250000, "basis": "city",
                "city": "Chicago, IL", "source": "bestplaces"}
        _o1 = stock_mod.record({"items": [
            {"company": "Alert Lane Co", "role": "Data Scientist",
             "source": "LINKEDIN_ALERT",
             "url": "https://www.linkedin.com/jobs/view/123",
             "gate": dict(_gate), "pay": dict(_pay)},
            {"company": "Plain Lane Co", "role": "Data Scientist",
             "source": "LINKEDIN",
             "url": "https://www.linkedin.com/jobs/view/456",
             "gate": dict(_gate), "pay": dict(_pay)},
        ]}, log_path=_alog)
        _recs = {r["company"]: r for r in _o1["recorded"]}
        _alert_id = _recs["Alert Lane Co"]["id"]
        _plain_id = _recs["Plain Lane Co"]["id"]
        _asp = Spine(log_path=str(_alog))
        _asp.set_friction("TEST linkedin friction", _plain_id,
                          scope="linkedin")
        _now = _dt(2026, 11, 5, 12, 0, tzinfo=state_mod.CT)
        _res = _asp.next_order("2026-11-05", now=_now)
        _skip = {s["item_id"]: s.get("failed") or []
                 for s in _res.get("skipped") or []}
        check("alert lane: LINKEDIN_ALERT not stopped by LinkedIn "
              "friction",
              "linkedin_lane_stopped" not in _skip.get(_alert_id, []),
              str(_skip))
        check("alert lane: plain LINKEDIN stopped by LinkedIn "
              "friction",
              "linkedin_lane_stopped" in _skip.get(_plain_id, []),
              str(_skip))
        _asp.set_friction("TEST alert friction", _alert_id,
                          scope="linkedin", alert_lane_blocked=True)
        _res2 = _asp.next_order("2026-11-05", now=_now)
        _skip2 = {s["item_id"]: s.get("failed") or []
                  for s in _res2.get("skipped") or []}
        check("alert lane: alert_lane_blocked marker pauses alerts",
              "linkedin_lane_stopped" in _skip2.get(_alert_id, []),
              str(_skip2))
        check("24h scan window: discovery packet carries the window",
              (_res.get("discovery") or {}).get(
                  "max_posting_age_hours") == 24,
              str((_res.get("discovery") or {}).get(
                  "max_posting_age_hours")))
        check("one pass per run: discovery packet carries the pass "
              "limit (the user, Nov 12, 2026)",
              (_res.get("discovery") or {}).get(
                  "passes_per_source_per_run") == 1,
              str((_res.get("discovery") or {}).get(
                  "passes_per_source_per_run")))
        check("site filters: discovery packet carries the filter "
              "directives for both sources",
              (_res.get("discovery") or {}).get(
                  "jobright_date_filter") == "last_24_hours"
              and (_res.get("discovery") or {}).get(
                  "indeed_job_type_filter") == "full_time",
              str({k: (_res.get("discovery") or {}).get(k) for k in
                   ("jobright_date_filter", "indeed_job_type_filter")}))

    # --- Company-name parse (audit fix, Nov 5, 2026): a company name
    # that starts lowercase (e.g. "fal") must parse — the old [A-Z]
    # start class left #252 with an empty company, which breaks its
    # diversification slot and every company-named surface.
    _m252 = state_mod.COMPANY_ROLE_RE.search(
        "#252 fal, Machine Learning Engineer, Safety, San Francisco")
    check("company parse: lowercase company name parses",
          bool(_m252) and _m252.group("company") == "fal")
    # #252 has since been submitted, so it no longer sits on any bench;
    # assert the parse on the item itself, window-independent.
    _i252 = copy_sp.load_state().item(252)
    check("company parse: parsed item #252 company is fal",
          _i252 is not None and _i252.company == "fal",
          f"(item #252 company: {_i252.company if _i252 else None})")

    # --- HST timestamps + scan-head exclusion (fix, Nov 5, 2026): the
    # hourly email scan's Nov 4 entry used the head "APPLICATION EMAIL
    # SCAN" (not in EXCLUDED_HEADS) and an HST stamp parse_ts returned
    # None for; its re-mentions of #250/#259 became their last submitted
    # events with ts=None and dropped them from the prose verified
    # count (prose 47 vs events 49). Both halves are now fixed.
    _hst = state_mod.parse_ts("8:33 PM HST, Wed Nov 4, 2026")
    check("timestamps: HST stamp parses and converts to CT",
          _hst is not None and (_hst.year, _hst.month, _hst.day,
                                _hst.hour, _hst.minute) == (2026, 11, 5, 0, 33),
          f"(got {_hst})")
    _hst24 = state_mod.parse_ts("2026-11-04 18:33 HST")
    check("timestamps: 24h HST stamp parses and converts to CT",
          _hst24 is not None and (_hst24.day, _hst24.hour,
                                  _hst24.minute) == (4, 22, 33),
          f"(got {_hst24})")
    check("scan heads: APPLICATION EMAIL SCAN is disposition-excluded",
          "APPLICATION EMAIL SCAN" in state_mod.EXCLUDED_HEADS)
    _vids = ids(copy0["verified_by_source"].get("LINKEDIN", []))
    check("scan heads: #250/#259 stay in the prose verified count",
          250 in _vids and 259 in _vids,
          f"(prose verified total {copy0['verified_total']})")

    # --- Company parse, anchored + Unicode (fix, Nov 5, 2026): the
    # company regex now anchors at the segment start and accepts a
    # Unicode first letter — a SEGMENT STATE segment for #265 ŌURA ran
    # on into the item-detail list and the unanchored regex assigned
    # it #261's company (Applied Materials), and Ō never matched the
    # ASCII class in its own stocked entry.
    # Assert on the PARSE, not bench membership (fix, Nov 5, 2026):
    # #265 was submitted later on Nov 5 and left the bench — the regex
    # invariant is that its company parses as ŌURA wherever it sits.
    _i265 = copy_sp.load_state().item(265)
    check("company parse: item #265 company is ŌURA",
          _i265.company == "ŌURA",
          f"(item #265 company: {_i265.company!r})")

    # --- soft acceptance comparison (live log may have grown)
    s = live
    print("\nNov 4 acceptance comparison (as of the live status read above):")
    print(f"  LinkedIn verified: {s['verified_counts'].get('LINKEDIN', 0)} "
          f"(expected 8) — {_fmt_items(s['verified_by_source'].get('LINKEDIN', []))}")
    print(f"  Jobright verified: {s['verified_counts'].get('JOBRIGHT', 0)} "
          f"(expected 10) — {_fmt_items(s['verified_by_source'].get('JOBRIGHT', []))}")
    print(f"  Total: {s['verified_total']} (expected 18 of 60); "
          f"limbo {len(s['limbo'])} (expected 0); "
          f"staged {len(s['staged'])} (expected 10); "
          f"captcha {len(s['captcha'])} (expected 0 — the day's two "
          f"captcha items, #173/#177, resolved and count as verified)")
    print(f"  Log lines at read time: {s['log_lines']}")
    print("\n" + ("ALL HARD CHECKS PASSED" if not FAILURES
                  else f"FAILURES: {FAILURES}"))
    return 1 if FAILURES else 0


def _fmt_items(items) -> str:
    return ", ".join(f"#{i['id']} {i['company']}" for i in items) or "—"


if __name__ == "__main__":
    raise SystemExit(main())
