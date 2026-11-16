#!/usr/bin/env python3
"""Events-layer tests. All writes go to tests/ copies only; the live prose
log and the live program/events.jsonl are never written.

Run: python3 tests/run_events_tests.py
  (d) v1 acceptance, made durable (audit fix, Nov 4, 2026): the original
      asserted a frozen mid-day snapshot of the LIVE log ("18 of 60"),
      which the live log outgrew within hours — a test that must fail
      every day teaches nothing. It now asserts the structural
      invariants that must hold at ANY point: the day's verified sets
      only grow (the frozen ACCEPT sets stay subsets), the disposition
      lists are pairwise disjoint, and the blocked-company check passes.
  (a) A fake submission recorded on the log COPY appends exactly ONE prose
      entry AND exactly ONE `submitted` event (to the scratch events file),
      and the event line is the minimal shape: exactly
      {ts, type, item, src, win} — no actor, no payload, no company.
  (b) backfill_events.py seeds tests/events_test.jsonl from the live parse;
      `state-check` on the (live prose, seeded events) pair shows zero
      divergences for the seeded items.
  (c) `events --since <watermark>` returns only events after the watermark.
  (e) Captcha separation end-to-end, on the COPY: recording a `captcha`
      outcome appends exactly one AWAITING CAPTCHA TAKEOVER prose entry and
      exactly one `captcha` event (minimal shape, NO why — captcha is not a
      why code anymore); the fold and `status` both show the item under
      Awaiting captcha, not staged. On the live window, the day's two
      captcha items (#173 Motional, #177 Peerspace) resolved this morning
      and count as verified — they must NOT appear in the captcha list.
  Plus the v1 round-trip suite (tests/run_tests.py) as a regression check.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))

import events as events_mod  # noqa: E402
import state as state_mod  # noqa: E402
from pipeline import Spine, classify_divergences  # noqa: E402

LIVE = Path.home() / ("workspace/goals/linkedin-ai-recruiter-outreach-weekly/"
                      "hidden_files/outreach-log.md")
COPY = BASE / "tests" / "log_copy.md"
SCRATCH = BASE / "tests" / "events_scratch.jsonl"
SEEDED = BASE / "tests" / "events_test.jsonl"
FAILURES = []

ACCEPT_LI = {186, 188, 195, 198, 199, 203, 208, 210}
ACCEPT_JR = {164, 165, 166, 167, 168, 172, 173, 175, 176, 177}
ACCEPT_STAGED = {169, 179, 180, 181, 197, 204, 205, 211, 212, 214}


def check(name: str, ok: bool, detail: str = ""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        FAILURES.append(name)


def ids(items) -> set[int]:
    return {i["id"] for i in items}


def main() -> int:
    state_dir = BASE / "state"
    vq = state_dir / "verify_queue.json"
    vq_backup = vq.read_text(encoding="utf-8") if vq.exists() else None
    _live_flag = state_dir / "FRICTION.flag"
    _live_flag_backup = (_live_flag.read_text(encoding="utf-8")
                         if _live_flag.exists() else None)
    try:
        # ------------------------------------------------ (d) v1 acceptance
        s = Spine().status("2026-11-04")
        li_now = ids(s["verified_by_source"].get("LINKEDIN", []))
        jr_now = ids(s["verified_by_source"].get("JOBRIGHT", []))
        check("(d) live status invariants: frozen ACCEPT sets stay subsets "
              "of the verified sets (history only grows)",
              ACCEPT_LI <= li_now and ACCEPT_JR <= jr_now
              and s["verified_total"] == len(li_now) + len(jr_now)
              + len(s["verified_by_source"].get("UNKNOWN", [])),
              f"(total {s['verified_total']}, LI {len(li_now)}, "
              f"JR {len(jr_now)}, log lines {s['log_lines']})")
        check("(d) disposition lists are pairwise disjoint; "
              "blocked-company check ok",
              not (ids(s["staged"]) & ids(s["captcha"]))
              and not (ids(s["staged"]) & (li_now | jr_now))
              and not (ids(s["captcha"]) & (li_now | jr_now))
              and not (ids(s["limbo"]) & (li_now | jr_now))
              and s["blocked_check_ok"],
              f"(staged {sorted(ids(s['staged']))}, "
              f"captcha {sorted(ids(s['captcha']))}, "
              f"limbo {len(s['limbo'])})")
        check("(d) captcha list separate: resolved #173/#177 not in it, "
              "no overlap with staged",
              173 not in ids(s["captcha"]) and 177 not in ids(s["captcha"])
              and not (ids(s["captcha"]) & ACCEPT_STAGED),
              f"(captcha: {sorted(ids(s['captcha']))})")

        # --------------------------------------- v1 regression (subprocess)
        r = subprocess.run([sys.executable, str(BASE / "tests" / "run_tests.py")],
                           capture_output=True, text=True)
        check("v1 round-trip suite still passes", r.returncode == 0,
              "(see tests/run_tests.py output if not)")
        if r.returncode != 0:
            print(r.stdout[-3000:], r.stderr[-2000:])

        # ------------------------------------- (a) record writes BOTH logs
        shutil.copy(LIVE, COPY)
        if SCRATCH.exists():
            SCRATCH.unlink()
        lines_before = len(COPY.read_text(encoding="utf-8").splitlines())
        sp_copy = Spine(log_path=str(COPY), events_path=str(SCRATCH))
        sp_copy.record({"item_id": 182, "outcome": "submitted",
                        "portal": "Ashby (TEST)",
                        "confirmation": "TEST events round-trip only"},
                       log_path=str(COPY))
        lines_after = len(COPY.read_text(encoding="utf-8").splitlines())
        check("(a) exactly one prose entry appended",
              lines_after == lines_before + 1,
              f"({lines_before} -> {lines_after})")
        evs = events_mod.read_events(SCRATCH)
        check("(a) exactly one `submitted` event appended",
              len(evs) == 1 and evs[0]["type"] == "submitted"
              and evs[0]["item"] == 182,
              f"({len(evs)} events)")
        check("(a) submitted line is exactly {ts,type,item,src,win}",
              len(evs) == 1
              and set(evs[0]) == {"ts", "type", "item", "src", "win"}
              and evs[0]["src"] == "JOBRIGHT"
              # win = the window of the item's latest logged activity
              # (_win_for's documented rule). #182 is a Nov 4-window
              # item; before the Nov 5, 2026 parser-contract fix it
              # carried a spurious submitted event in the Nov 5 section
              # (a Guardian tally line merged into another item's
              # entry), which made this expectation read Nov 5.
              and evs[0]["win"] == "2026-11-04",
              f"({evs[0] if evs else 'no events'})")

        # ------------------------------- (b) seeded pair has no divergence
        r = subprocess.run([sys.executable,
                            str(BASE / "tests" / "backfill_events.py")],
                           capture_output=True, text=True)
        check("(b) backfill ran", r.returncode == 0, r.stdout.strip())
        if r.returncode != 0:
            print(r.stderr[-2000:])
        chk = Spine(events_path=str(SEEDED)).state_check("2026-11-04")
        check("(b) state-check: zero divergences",
              chk["divergences"] == [],
              f"(prose verified {chk['prose']['verified_total']}, "
              f"events verified {chk['events']['verified_total']}, "
              f"divergences {chk['divergences']})")
        check("(b) folded verified set == prose verified set",
              set().union(*[set(v) for v in
                            chk["events"]["verified_by_source"].values()])
              == set().union(*[set(v) for v in
                               chk["prose"]["verified_by_source"].values()]))
        check("(b) state-check compares captcha lists too",
              chk["prose"]["captcha"] == chk["events"]["captcha"],
              f"(prose {chk['prose']['captcha']}, "
              f"events {chk['events']['captcha']})")

        # --------------------------- schema sweep: minimal shape only
        seeded_lines = events_mod.read_events(SEEDED)
        check("schema: seeded lines carry ONLY the allowed keys",
              all(set(e) <= events_mod.ALLOWED_KEYS for e in seeded_lines)
              and all(set(e) == {"ts", "type", "item", "src", "win"}
                      for e in seeded_lines if e["type"] == "submitted"),
              f"({len(seeded_lines)} seeded lines)")
        check("schema: `why` appears only on skipped/staged lines",
              all(("why" not in e) or e["type"] in events_mod.WHY_TYPES
                  for e in seeded_lines)
              and all(e.get("why") in events_mod.WHY_CODES
                      for e in seeded_lines if e["type"] == "staged"),
              "(staged seed lines carry compact why codes)")
        staged_whys = {e.get("why") for e in seeded_lines
                       if e["type"] == "staged"}
        check("schema: seeded staged whys are all valid codes",
              staged_whys <= set(events_mod.WHY_CODES),
              f"(staged why codes: {sorted(staged_whys)})")
        check("schema: why mapper is specific on known blockers "
              "(unit-level; durable form of the old seeded-data check)",
              events_mod.why_code(
                  "approval card presented at the resume upload step")
              == "card"
              and events_mod.why_code(
                  "email verification code step awaiting the user") == "code"
              and events_mod.why_code(
                  "photo id upload required at this step") == "id_doc",
              "(card / code / id_doc map from their blocker text)")

        # --------------------------------------- (c) watermark read (--since)
        seeded = events_mod.read_events(SEEDED)
        stamps = sorted({e["ts"] for e in seeded})
        wm = stamps[len(stamps) // 2]
        wm_dt = events_mod._parse_ts(wm)
        expected = [e for e in seeded
                    if events_mod._parse_ts(e["ts"]) > wm_dt]
        got = events_mod.read_events(SEEDED, since=wm)
        check("(c) read_events --since returns only later events",
              len(got) == len(expected)
              and all(events_mod._parse_ts(e["ts"]) > wm_dt for e in got),
              f"(watermark {wm}; {len(got)} of {len(seeded)} events)")
        r = subprocess.run([sys.executable, str(BASE / "spine.py"),
                            "--events", str(SEEDED), "events",
                            "--since", wm],
                           capture_output=True, text=True)
        cli_lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        check("(c) CLI `events --since` agrees",
              r.returncode == 0 and len(cli_lines) == len(expected),
              f"({len(cli_lines)} lines)")

        # --------------------- (e) captcha separation, end-to-end on COPY
        check("(e) `captcha` is an event type and NOT a why code",
              "captcha" in events_mod.EVENT_TYPES
              and "captcha" not in events_mod.WHY_CODES)
        lines_before = len(COPY.read_text(encoding="utf-8").splitlines())
        vt_before = sp_copy.status("2026-11-04")["verified_total"]
        entry = sp_copy.record(
            {"item_id": 151, "outcome": "captcha",
             "step": "hCaptcha challenge at the submit step (TEST)"},
            log_path=str(COPY))
        lines_after = len(COPY.read_text(encoding="utf-8").splitlines())
        check("(e) captcha record appends exactly one prose entry "
              "(AWAITING CAPTCHA TAKEOVER shape)",
              lines_after == lines_before + 1
              and "AWAITING CAPTCHA TAKEOVER" in entry,
              f"({lines_before} -> {lines_after})")
        evs = events_mod.read_events(SCRATCH)
        cap = [e for e in evs if e["type"] == "captcha"]
        check("(e) exactly one `captcha` event, minimal shape, NO why",
              len(cap) == 1 and cap[0]["item"] == 151
              and "why" not in cap[0]
              and set(cap[0]) <= events_mod.ALLOWED_KEYS
              and {"ts", "type", "item", "win"} <= set(cap[0]),
              f"({cap})")
        folded = state_mod.fold_events(evs)
        check("(e) fold: item is captcha, not staged",
              151 in folded["captcha"] and 151 not in folded["staged"])
        s_copy = sp_copy.status("2026-11-04")
        check("(e) status: item under Awaiting captcha, not staged; "
              "verified total unchanged",
              151 in ids(s_copy["captcha"])
              and 151 not in ids(s_copy["staged"])
              and s_copy["verified_total"] == vt_before,
              f"(captcha: {sorted(ids(s_copy['captcha']))})")
        try:
            events_mod.append_event(SCRATCH, "captcha", item=999, why="card")
            refused = False
        except ValueError:
            refused = True
        check("(e) append_event refuses a `why` on a captcha event", refused)

        # --------------- (f) divergence classification (the user, Nov 5, 2026)
        # The watcher messages the user only when a counting divergence
        # includes a DEEP item; benign mismatches are explained by the
        # records themselves. Cases mirror the live Nov 5, 2026 set
        # (Navan/Stripe catch-ups, Socure pre-go-live, TRM carried
        # park, Super.com carried limbo) plus the deep patterns.
        divs = [
            {"item_id": 198, "company": "Navan",
             "prose": "verified", "events": "(absent)"},
            {"item_id": 187, "company": "Socure",
             "prose": "verified", "events": "(absent)"},
            {"item_id": 182, "company": "TRM Labs",
             "prose": "captcha", "events": "(absent)"},
            {"item_id": 267, "company": "Super.com",
             "prose": "limbo", "events": "(absent)"},
            {"item_id": 267, "company": "Super.com",
             "prose": "limbo-event present",
             "events": "limbo-event absent"},
            {"item_id": 999, "company": "Phantom Co",
             "prose": "verified", "events": "(absent)"},
            {"item_id": 998, "company": "Ghost Co",
             "prose": "(absent)", "events": "verified"},
            {"item_id": 997, "company": "Unlogged Co",
             "prose": "(absent)", "events": "staged"},
            {"item_id": 996, "company": "Nowhere Co",
             "prose": "staged-event present",
             "events": "staged-event absent"},
        ]
        deep, benign = classify_divergences(
            divs, {198: "verified"}, {187, 182, 267})
        deep_ids = {d["item_id"] for d in deep}
        benign_ids = {d["item_id"] for d in benign}
        check("(f) catch-up verified (event book holds it, earlier "
              "window) is benign", 198 in benign_ids)
        check("(f) pre-go-live verified with a prior prose trail is "
              "benign", 187 in benign_ids)
        check("(f) carried park re-noted as captcha is benign",
              182 in benign_ids)
        check("(f) carried limbo + its presence line are benign",
              267 in benign_ids and 267 not in deep_ids)
        check("(f) phantom verified (no events, no trail) is DEEP",
              999 in deep_ids)
        check("(f) events ahead of the log (verified) is DEEP",
              998 in deep_ids)
        check("(f) events ahead of the log (staged) is DEEP",
              997 in deep_ids)
        check("(f) presence mismatch on a phantom item is DEEP",
              996 in deep_ids)
        check("(f) every divergence is classified exactly once",
              len(deep) + len(benign) == len(divs),
              f"(deep {len(deep)}, benign {len(benign)}, "
              f"total {len(divs)})")
        chk_pair = Spine(events_path=str(SEEDED)).state_check("2026-11-04")
        check("(f) state_check exposes the classification; the seeded "
              "pair has no deep divergence",
              chk_pair["deep_divergence"] is False
              and chk_pair["deep_divergences"] == []
              and len(chk_pair["deep_divergences"])
              + len(chk_pair["benign_divergences"])
              == len(chk_pair["divergences"]))

        # --------------------- (g) THE HANDOFF CHECK on record (Nov 5,
        # 2026): record_with_check echoes the outcome as understood and
        # proves both records landed — including exposing a DERIVED why.
        shutil.copy(LIVE, COPY)
        if SCRATCH.exists():
            SCRATCH.unlink()
        sp_hc = Spine(log_path=str(COPY), events_path=str(SCRATCH))
        hc = sp_hc.record_with_check(
            {"item_id": 182, "outcome": "submitted", "portal": "Ashby (TEST)",
             "confirmation": "TEST handoff check"}, log_path=str(COPY))
        check("(g) submitted record verifies: prose in log + event landed",
              hc["verified"] is True
              and hc["landed_as"]["prose_entry_in_log"] is True
              and hc["landed_as"]["event"]["type"] == "submitted"
              and hc["understood"]["fields"]["portal"] == "Ashby (TEST)",
              str(hc))
        hc2 = sp_hc.record_with_check(
            {"item_id": 182, "outcome": "staged",
             "step": "resume upload approval card",
             "blocker": "platform approval card presented",
             "blocker_kind": "approval_card"},
            log_path=str(COPY))
        check("(g) a derived why is ECHOED, never silent",
              hc2["verified"] is True
              and hc2["landed_as"]["event"]["type"] == "staged"
              and hc2["landed_as"]["event"]["why"]
              in events_mod.WHY_CODES,
              str(hc2["landed_as"]))
        hc3 = sp_hc.record_with_check(
            {"item_id": 182, "outcome": "post_submit_pending",
             "note": "validation code demanded after submit (TEST)"},
            log_path=str(COPY))
        check("(g) prose-only outcome verifies on the prose landing alone",
              hc3["verified"] is True
              and hc3["landed_as"]["event"] is None,
              str(hc3))

        # --------------------- (h) MANUAL PACKET + THE OPEN-PILES
        # TRACK FILE (the user, Nov 6, 2026): captcha and manual-packet
        # items waiting on the user herself are listed by CODE, across ALL
        # windows, in a file rebuilt on every recorded outcome.
        import json as _json
        shutil.copy(LIVE, COPY)
        if SCRATCH.exists():
            SCRATCH.unlink()
        piles_path = SCRATCH.parent / "open_piles.json"
        if piles_path.exists():
            piles_path.unlink()
        sp_p = Spine(log_path=str(COPY), events_path=str(SCRATCH))
        events_mod.append_event(
            SCRATCH, "captcha", item=159, src="JOBRIGHT",
            win="2026-11-04", ts="2026-11-05T02:46:45-06:00")
        piles0 = sp_p.open_piles()
        check("(h) a captcha from an OLD window is on the pile "
              "(cross-window tracking)",
              [e["item_id"] for e in piles0["captcha"]] == [159]
              and piles0["captcha"][0]["company"] == "GitHub"
              and piles0["manual_packets"] == [],
              str(piles0))
        hc_p1 = sp_p.record_with_check(
            {"item_id": 182, "outcome": "captcha",
             "step": "hCaptcha challenge modal (TEST)"},
            log_path=str(COPY))
        payload = _json.loads(piles_path.read_text(encoding="utf-8")) \
            if piles_path.exists() else {}
        check("(h) recording a captcha rebuilds the track file and "
              "the item joins the captcha pile",
              hc_p1["verified"] is True and hc_p1["piles_file"] == "rebuilt"
              and payload.get("captcha_open_count") == 2
              and {e["item_id"] for e in payload["captcha"]} == {159, 182},
              str(payload)[:300])
        hc_p2 = sp_p.record_with_check(
            {"item_id": 182, "outcome": "manual_packet", "portal": "Ashby",
             "step": "captcha blocks this browser by IP (TEST)",
             "note": "Packet: apply link + tailored resume + values (TEST)."},
            log_path=str(COPY))
        piles2 = sp_p.open_piles()
        fold2 = state_mod.fold_events(events_mod.read_events(SCRATCH))
        check("(h) manual_packet lands as a packet event, supersedes "
              "the captcha on BOTH sides, and moves the item to the "
              "manual pile",
              hc_p2["verified"] is True
              and hc_p2["landed_as"]["event"]["type"] == "packet"
              and 182 in fold2["packet"] and 182 not in fold2["captcha"]
              and [e["item_id"] for e in piles2["manual_packets"]] == [182]
              and 182 not in {e["item_id"] for e in piles2["captcha"]}
              and state_mod.parse_log(str(COPY)).items[182].state == "packet",
              str(hc_p2["landed_as"]))
        st_p = sp_p.status()
        check("(h) window status lists the packet on its own line",
              182 in [i["id"] for i in st_p["manual_packets"]],
              str(st_p["manual_packets"]))
        ev_packet = [e for e in events_mod.read_events(SCRATCH)
                     if e.get("type") == "packet"]
        check("(h) the packet event is the minimal shape (no why, "
              "no payload)",
              len(ev_packet) == 1
              and set(ev_packet[0]) == {"ts", "type", "item", "src", "win"},
              str(ev_packet))
        n_evs_before = len(events_mod.read_events(SCRATCH))
        refused = False
        try:
            sp_p.record({"item_id": 182, "outcome": "manual_packet",
                         "portal": "Ashby"}, log_path=str(COPY))
        except ValueError:
            refused = True
        check("(h) a manual_packet with no step is REFUSED, "
              "nothing written",
              refused and len(events_mod.read_events(SCRATCH))
              == n_evs_before)
        sp_p.record_with_check(
            {"item_id": 182, "outcome": "submitted", "portal": "Ashby",
             "confirmation": "the user submitted the packet herself (TEST)"},
            log_path=str(COPY))
        payload3 = _json.loads(piles_path.read_text(encoding="utf-8"))
        check("(h) the user's reported submission clears the packet; the "
              "old-window captcha still waits",
              payload3["manual_open_count"] == 0
              and payload3["captcha_open_count"] == 1
              and payload3["captcha"][0]["item_id"] == 159,
              str(payload3)[:300])
        why_refused = False
        try:
            events_mod.append_event(SCRATCH, "packet", item=1,
                                    src="LINKEDIN", why="card")
        except ValueError:
            why_refused = True
        check("(h) a packet event carrying a why is refused",
              why_refused)
    finally:
        # RESTORE, never delete (Nov 7, 2026 — same fix as
        # run_tests.py: this block used to unlink the LIVE friction
        # flag, silently undoing a real stop on every suite run).
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

    print("\n" + ("ALL EVENTS TESTS PASSED" if not FAILURES
                  else f"FAILURES: {FAILURES}"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
