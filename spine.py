#!/usr/bin/env python3
"""spine.py — CLI for the application program (v1, shadow mode).

Usage:
  spine.py status [--date YYYY-MM-DD] [--json]
  spine.py next [--date YYYY-MM-DD]
  spine.py record result.json [--log PATH]
  spine.py verify <item-id|#item-id|Company Name>
  spine.py clear-friction --note "..." [--log PATH]
  spine.py events [--since ISO-TS] [--events PATH]
  spine.py state-check [--date YYYY-MM-DD] [--events PATH]
  spine.py piles [--json]   (rebuild + print the open captcha and
                             manual-packet piles across ALL windows;
                             the track file is state/open_piles.json)
  spine.py gate --total N --india N --source SRC
  spine.py gate-packet format
  spine.py gate-packet record packet.json
      (the forward-movement gate check as a clean packet, the user,
      Nov 12, 2026 — see gate_intake.py: the run returns the counts
      it read off the gate source's page as a dictionary; the
      program validates, maps Revelio South Asia → India, decides,
      and records the verdict)
  spine.py gate-packet not-found result.json
      (the CODE STEP between Revelio and LinkedIn, the user, Nov 13,
      2026 — see gate_fallback.py: the run hands in a not-found
      Revelio result {company, run?}; code tracks the company as
      fallback-owed and prints the ORDER for the LinkedIn check.
      A LinkedIn fallback packet or drop records only against an
      open order)
  spine.py inbox format
  spine.py inbox watch-intake candidates.json
  spine.py inbox watch-record results.json
  spine.py inbox daily-scope
  spine.py inbox daily-record results.json
  spine.py inbox daily-finish summary.json
  spine.py inbox check-claim --person NAME --message-ts ISO
  spine.py inbox invite-intake candidates.json
  spine.py inbox invite-record results.json
  spine.py inbox jobalert-intake candidates.json
  spine.py inbox jobalert-record results.json
      (LinkedIn JOB ALERTS as a discovery source, the user, Nov 12, 2026
      — see inbox.py: the daily alert emails from the pinned
      jobalerts-noreply@linkedin.com, identified by SENDER ONLY —
      the subject is never consulted; the packet carries the
      extracted job links, the See-all-jobs URL, and the code's
      fixed runner instructions)
      (connection-invitation emails in code, the user, Nov 12, 2026 —
      see inbox.py: pinned sender messages-noreply@linkedin.com,
      the shared processed pool, and Accept-link extraction)
      (the LinkedIn inbox jobs' scope in code, the user, Nov 12, 2026 —
      see inbox.py: the email watch's past-hour window, Gmail-ID
      dedupe and non-message triage, the daily check's 24-hour
      cutoff + stand-down list, and the claims-ledger writes are
      all enforced by the program, never judged in a run)
  spine.py invite status [--date YYYY-MM-DD] [--json]
  spine.py invite record packet.json
  spine.py invite counter --phase start|end --value N [--date YYYY-MM-DD]
  spine.py invite backfill packet.json
      (connection invitations in code, the user, Nov 10, 2026 — see
      invitations.py: the program is the count of record for the
      daily outreach run, exactly as it is for applications)

SHADOW MODE: `status`, `next`, and `verify` are read-only against the live
log. `record` appends to whatever --log points at — during shadow mode only
ever point it at a COPY (program/tests/), never the live outreach log.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "checks"))

import events as events_mod  # noqa: E402
import gate_fallback as gate_fallback_mod  # noqa: E402
import gate_intake as gate_intake_mod  # noqa: E402
import inbox as inbox_mod  # noqa: E402
import invitations as invitations_mod  # noqa: E402
import outreach_targets as outreach_targets_mod  # noqa: E402
import discovery as discovery_mod  # noqa: E402
import state as state_mod  # noqa: E402
import verify as verify_mod  # noqa: E402
from pipeline import Spine  # noqa: E402


def _fmt_items(items) -> str:
    return ", ".join(f"#{i['id']} {i['company']}" for i in items) or "—"


def cmd_status(sp: Spine, args) -> int:
    try:
        s = sp.status(args.date)
    except ValueError as exc:
        if args.date is None:
            # Fresh install / empty log: no window has ever been
            # written. That is a state to report, not a crash.
            print(f"No batch windows yet — {exc}. Nothing has been "
                  "recorded; the first window section is written "
                  "when the first batch runs.")
            return 0
        raise
    if args.json:
        print(json.dumps(s, indent=2, default=str))
        return 0
    w = s["window"]
    counts = s["verified_counts"]
    li = counts.get("LINKEDIN", 0)
    jr = counts.get("JOBRIGHT", 0)
    ind = counts.get("INDEED", 0)
    la = counts.get("LINKEDIN_ALERT", 0)
    t = s["targets"]
    print(f"Window {w['date']}  (opens {w['opens']}, closes {w['closes']})")
    print(f"Log: {s['log_path']} — {s['log_lines']} lines")
    print(f"VERIFIED {s['verified_total']} of {t['total']} — "
          f"LinkedIn {li}/{t['linkedin']}, Jobright {jr}/{t['jobright']}, "
          f"Indeed {ind}/{t.get('indeed', 0)}, "
          f"LinkedIn alerts {la}/{t.get('linkedin_alert', 0)}")
    for src, items in s["verified_by_source"].items():
        print(f"  {src} ({len(items)}): {_fmt_items(items)}")
    print(f"Limbo ({len(s['limbo'])}): {_fmt_items(s['limbo'])}")
    print(f"Staged for tap session ({len(s['staged'])}): "
          f"{_fmt_items(s['staged'])}")
    print(f"Awaiting captcha ({len(s['captcha'])}): "
          f"{_fmt_items(s['captcha'])}")
    print(f"Manual packets — the user to submit ({len(s['manual_packets'])}): "
          f"{_fmt_items(s['manual_packets'])}")
    if s.get("presentation"):
        print(s["presentation"])
    print(f"Bench ready ({len(s['bench'])}): {_fmt_items(s['bench'])}")
    print(f"Claimed, unfinished ({len(s['claimed_unfinished'])}): "
          f"{_fmt_items(s['claimed_unfinished'])}")
    print(f"Company slots used this window: "
          f"{', '.join(s['company_slots_used']) or '—'}")
    print(f"Blocked list in log: {s['blocked_total_in_log']} "
          f"(expected {s['blocked_expected']}) — "
          f"{'OK' if s['blocked_check_ok'] else 'MISMATCH'}")
    print(f"Friction flag: {'SET — ' + str(s['friction']) if s['friction'] else 'none'}")
    if s["friction"]:
        print(f"Friction scope: {s.get('friction_scope')} — "
              + ("LinkedIn lane stopped; Jobright + Indeed + the "
                 "LinkedIn-alert lane continue "
                 "(the user, Nov 7, 2026; Indeed + alerts added Nov 12, 2026)"
                 if s.get("friction_scope") == "linkedin"
                 else "all lanes stopped"))
    return 0


def cmd_next(sp: Spine, args) -> int:
    order = sp.next_order(args.date)
    print(json.dumps(order, indent=2, default=str))
    return 0


def cmd_record(sp: Spine, args) -> int:
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    check = sp.record_with_check(result, log_path=args.log)
    entry = check["entry"]
    print("WROTE:", entry)
    # THE HANDOFF CHECK (the user, Nov 5, 2026): the program echoes the
    # outcome as understood and proves both records landed as handed
    # over; the instruction rides in the output itself.
    print("HANDOFF CHECK (verified must be true — if false, the write "
          "did NOT land as handed over: log a SPINE FAILURE, fall back "
          "to prose for this item, and report it):", json.dumps(
              {k: check[k] for k in ("understood", "landed_as",
                                     "verified", "problems")},
              default=str))
    s = sp.status(args.date)
    print(f"Verified total now: {s['verified_total']} "
          f"(LinkedIn {s['verified_counts'].get('LINKEDIN', 0)}, "
          f"Jobright {s['verified_counts'].get('JOBRIGHT', 0)}, "
          f"Indeed {s['verified_counts'].get('INDEED', 0)}, "
          f"LinkedIn alerts "
          f"{s['verified_counts'].get('LINKEDIN_ALERT', 0)})")
    # KEEP-GOING LOOP (the user, Nov 4, 2026: "if anything stick, keep going down
    # the list" — built into code): every recorded outcome hands back the
    # NEXT work order in this same output, so a run never decides whether
    # to continue and never idles on a stuck item — a staged/captcha item
    # is parked by the record itself, and the program immediately serves
    # the next item. The loop ends only when the program says so
    # (complete / closed / empty) or friction stops everything.
    if result.get("outcome") == "friction":
        _scope = sp.friction_scope()
        if _scope == "linkedin":
            print("LINKEDIN LANE STOPPED: friction recorded on a "
                  "LinkedIn-sourced item — no LinkedIn work until the "
                  "flag is cleared. EXTERNAL SOURCES CONTINUE — "
                  "Jobright + Indeed, plus the LinkedIn-alert lane "
                  "(the user, Nov 7, 2026; Indeed + alerts added "
                  "Nov 12, 2026): the next order below is "
                  "external-sources-only.")
            nxt = sp.next_order(args.date)
            print("KEEP GOING (EXTERNAL SOURCES ONLY — JOBRIGHT + "
                  "INDEED + LINKEDIN ALERTS) — next from the program:",
                  json.dumps(nxt, indent=1, default=str))
        else:
            print("STOPPED: friction recorded — no next order. "
                  "All work halts until the friction flag is cleared.")
    else:
        nxt = sp.next_order(args.date)
        print("KEEP GOING — next from the program:",
              json.dumps(nxt, indent=1, default=str))
    return 0


def cmd_piles(sp: Spine, args) -> int:
    """Rebuild the track file and print EVERY open pile across all
    windows: the captcha takeovers and the manual packets still
    waiting on the user herself (the user, Nov 6, 2026)."""
    payload = sp._write_piles_file()
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0
    print(f"Track file: {sp.piles_file} (rebuilt "
          f"{payload['updated_at']})")
    print(f"Awaiting captcha — ALL windows "
          f"({payload['captcha_open_count']}):")
    for e in payload["captcha"]:
        print(f"  #{e['item_id']} {e['company']} — {e['role']} "
              f"(window {e['window']}, since {e['since']})")
    print(f"Manual packets — the user to submit — ALL windows "
          f"({payload['manual_open_count']}):")
    for e in payload["manual_packets"]:
        print(f"  #{e['item_id']} {e['company']} — {e['role']} "
              f"(window {e['window']}, since {e['since']})")
    return 0


def cmd_verify(sp: Spine, args) -> int:
    st = sp.load_state()
    target = args.item
    item = None
    if target.lstrip("#").isdigit():
        item = st.items.get(int(target.lstrip("#")))
    else:
        for it in st.items.values():
            if it.company.lower() == target.lower():
                item = it
                break
    if item is None:
        print(json.dumps({"found": False, "error": f"item not in log: {target}"}))
        return 1
    sub = item.submitted_event
    since = (sub[1].date() if sub and sub[1] else datetime.now(state_mod.CT).date())
    result = verify_mod.check_confirmation(item.company, since, role=item.role)
    result["item_id"] = item.id
    result["company"] = item.company
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_gate(sp: Spine, args) -> int:
    """The company-gate DECISION as code (Nov 4, 2026): the counts come
    from Revelio Labs — the ONLY vetting source (the user, Nov 12, 2026, no
    exception); the thresholds are applied here, from rules.yaml,
    never eyeballed."""
    cfg = sp.rules.get("gate") or {}
    # REVELIO-ONLY VETTING (the user, Nov 12, 2026 — no exception): the raw
    # decision path refuses counts from any other source too.
    if (args.source or "").strip().lower() not in ("revelio labs",
                                                    "revelio"):
        print(json.dumps({"error": "vetting is Revelio-only, no "
                          "exception (the user, Nov 12, 2026); got source "
                          f"{args.source!r}"}))
        return 2
    total, india = args.total, args.india
    pct = (100.0 * india / total) if total else 0.0
    if total < cfg.get("hard_pass_total_below", 100):
        verdict, block = "HARD_PASS_SIZE", False
    elif pct > cfg.get("india_block_pct", 50):
        verdict, block = "HARD_PASS_INDIA_BLOCK", True
    elif total <= cfg.get("alert_band_max", 500):
        verdict, block = "PASS_ALERT", False
    else:
        verdict, block = "PASS", False
    print(json.dumps({"verdict": verdict, "block_company": block,
                      "total": total, "india": india,
                      "india_pct": round(pct, 2), "source": args.source}))
    return 0


def _fallback_state_for(log_path):
    """The gate-fallback state file for a log: the live log uses
    gate_fallback's own default (program/state/gate_fallback.json);
    any other log (tests, copies) derives one beside itself, so a
    test can never write the live state — the same rule stock.py
    applies to its data files."""
    lp = Path(log_path)
    if lp == gate_intake_mod.LOG_PATH:
        return None
    return lp.parent / "gate_fallback.state.json"


def cmd_gate_packet(sp: Spine, args) -> int:
    """The forward-movement gate check as a clean packet (the user,
    Nov 12, 2026 — the same format → record pattern as stock.py and
    invite record): the run returns the counts it read off the gate
    source's page (Revelio Labs — the only vetting source) as a dictionary; gate_intake
    validates it, maps South Asia → India for Revelio in code,
    applies the existing gate decision, records the verdict line,
    and prints the verdict as JSON. A refused packet writes nothing
    and exits 2."""
    if args.gate_packet_cmd == "format":
        print(gate_intake_mod.FORMAT_TEXT)
        return 0
    if args.gate_packet_cmd == "not-found":
        # THE CODE STEP (the user, Nov 13, 2026): a not-found Revelio
        # result is handed to code; code tracks the company as
        # fallback-owed and prints the ORDER for the LinkedIn
        # check. The worker never goes to LinkedIn on its own.
        try:
            payload = json.loads(Path(args.packet).read_text(
                encoding="utf-8"))
            opened = gate_fallback_mod.open_pending(
                payload.get("company") or "",
                run_label=payload.get("run") or "",
                state_path=_fallback_state_for(sp.log_path))
        except (ValueError, OSError) as exc:
            print(json.dumps({"owed": False, "refused": str(exc)}))
            return 2
        print(json.dumps({"owed": True,
                          "company": opened["company"],
                          "already_pending":
                              opened["already_pending"],
                          "order": opened["order"]}, indent=1))
        return 0
    try:
        packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
        result = gate_intake_mod.record_packet(
            packet, log_path=Path(sp.log_path),
            fallback_state_path=_fallback_state_for(sp.log_path))
    except (ValueError, OSError) as exc:
        print(json.dumps({"recorded": False, "refused": str(exc)}))
        return 2
    print("WROTE:", result["log_line"])
    print(json.dumps({k: result[k] for k in (
        "recorded", "verified", "item_id", "company", "source",
        "total", "india", "india_pct", "india_basis", "verdict",
        "block_company", "alert", "landed_gate")}, indent=1))
    return 0 if result["verified"] else 1


def _inbox_paths(sp: Spine) -> dict:
    """Path set for the inbox commands: the live log uses the live
    claims ledger + program state; ANY other --log (tests, copies)
    derives both beside itself, so a test can never write the live
    claims or watch state — the same rule stock.py applies to its
    data files."""
    log_path = Path(sp.log_path)
    if log_path == inbox_mod.LOG_PATH:
        return {"log_path": log_path,
                "claims_path": inbox_mod.CLAIMS_PATH,
                "state_path": inbox_mod.STATE_PATH}
    return {"log_path": log_path,
            "claims_path": log_path.parent / "inbox-action-claims.md",
            "state_path": log_path.parent / "inbox-state.json"}


def cmd_inbox(sp: Spine, args) -> int:
    """The LinkedIn inbox jobs' scope as clean packets (the user, Nov 12,
    2026 — see inbox.py): watch-intake enforces the past-hour
    window / dedupe / triage for the email watch; daily-scope
    computes the daily check's 24-hour cutoff + stand-down list;
    the record steps write the claims-ledger line, the processed
    state, and the log skeleton; check-claim answers CLAIMED /
    CLEAR. A malformed batch writes nothing and exits 2."""
    paths = _inbox_paths(sp)
    try:
        if args.inbox_cmd == "format":
            print(inbox_mod.FORMAT_TEXT)
            return 0
        if args.inbox_cmd == "watch-intake":
            out = inbox_mod.watch_intake(
                json.loads(Path(args.file).read_text(encoding="utf-8")),
                state_path=paths["state_path"])
            print(json.dumps(out, indent=1))
            return 0
        if args.inbox_cmd == "watch-record":
            out = inbox_mod.watch_record(
                json.loads(Path(args.file).read_text(encoding="utf-8")),
                log_path=paths["log_path"],
                claims_path=paths["claims_path"],
                state_path=paths["state_path"])
            print(json.dumps(out, indent=1))
            return 0
        if args.inbox_cmd == "daily-scope":
            out = inbox_mod.daily_scope(
                claims_path=paths["claims_path"],
                state_path=paths["state_path"])
            print(json.dumps(out, indent=1))
            return 0
        if args.inbox_cmd == "daily-record":
            out = inbox_mod.daily_record(
                json.loads(Path(args.file).read_text(encoding="utf-8")),
                log_path=paths["log_path"],
                claims_path=paths["claims_path"],
                state_path=paths["state_path"])
            print(json.dumps(out, indent=1))
            return 0
        if args.inbox_cmd == "daily-finish":
            out = inbox_mod.daily_finish(
                json.loads(Path(args.file).read_text(encoding="utf-8")),
                log_path=paths["log_path"],
                fallback_state_path=_fallback_state_for(
                    paths["log_path"]))
            print(json.dumps(out, indent=1))
            return 0
        if args.inbox_cmd == "check-claim":
            out = inbox_mod.check_claim(args.person, args.message_ts,
                                        args.claim_key or "",
                                        paths["claims_path"])
            print(json.dumps(out, indent=1))
            return 0
        if args.inbox_cmd == "invite-intake":
            out = inbox_mod.invite_intake(
                json.loads(Path(args.file).read_text(encoding="utf-8")),
                state_path=paths["state_path"])
            print(json.dumps(out, indent=1))
            return 0
        if args.inbox_cmd == "invite-record":
            out = inbox_mod.invite_record(
                json.loads(Path(args.file).read_text(encoding="utf-8")),
                log_path=paths["log_path"],
                state_path=paths["state_path"])
            print(json.dumps(out, indent=1))
            return 0
        if args.inbox_cmd == "jobalert-intake":
            out = inbox_mod.jobalert_intake(
                json.loads(Path(args.file).read_text(encoding="utf-8")),
                state_path=paths["state_path"])
            print(json.dumps(out, indent=1))
            return 0
        if args.inbox_cmd == "jobalert-record":
            out = inbox_mod.jobalert_record(
                json.loads(Path(args.file).read_text(encoding="utf-8")),
                state_path=paths["state_path"])
            print(json.dumps(out, indent=1))
            return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "refused": str(exc)}))
        return 2
    return 0


def cmd_pay(sp: Spine, args) -> int:
    """The pay DECISION as code. PAY RULE v2 (the user, Nov 5, 2026): with
    --basis, the BAR is picked here from rules.yaml pay_filter —
    city → the universal $200,000 bar; remote_national → $120,000
    (Houston basis, unchanged); remote_zone → the researched city
    equivalent passed as --equivalent (unchanged). Legacy calls
    (--equivalent + --attainable, no --basis) keep the direct
    comparison so in-flight job instructions keep working."""
    cfg = sp.rules.get("pay_filter") or {}
    basis = getattr(args, "basis", None)
    if basis == "city":
        bar = float(cfg.get("universal_bar", 200000))
    elif basis == "remote_national":
        bar = float(cfg.get("remote_national_bar",
                            cfg.get("base_houston_annual", 120000)))
    elif basis == "remote_zone":
        if args.equivalent is None:
            print(json.dumps({"error": "remote_zone basis needs "
                                        "--equivalent (the researched "
                                        "city equivalent)"}))
            return 1
        bar = float(args.equivalent)
    elif args.equivalent is not None:
        basis, bar = "legacy_equivalent", float(args.equivalent)
    else:
        print(json.dumps({"error": "pay needs --basis or --equivalent"}))
        return 1
    ok = args.attainable >= bar
    print(json.dumps({
        "verdict": "PASS" if ok else "SKIP_BELOW_CITY_EQUIVALENT",
        "basis": basis, "bar": bar, "equivalent": bar,
        "attainable": args.attainable, "city": args.city or ""}))
    return 0


def cmd_closeout(sp: Spine, args) -> int:
    """BATCH CLOSED accounting, generated by code (Nov 4, 2026). For a
    closed window: report the marker present, or return the exact
    accounting text for the guardian to append verbatim — the numbers
    are computed here, never re-derived by an agent."""
    st = sp.load_state()
    w = st.window_for(args.date)
    now = datetime.now(state_mod.CT)
    if now < w.close_dt:
        print(json.dumps({"status": "not_closed", "window": w.date,
                          "closes": w.close_dt.isoformat()}))
        return 0
    nxt_line = min((o.section_line for o in st.windows
                    if o.section_line > w.section_line),
                   default=len(st.lines) + 1)
    marker = None
    for ln in st.lines[w.section_line - 1:nxt_line - 1]:
        # A real marker is an entry HEADED "BATCH CLOSED" inside the
        # window's own section (legacy shape: "- BATCH CLOSED [time] —
        # awaiting morning report"; generated shape: "BATCH CLOSED —
        # window <date>: FINAL ACCOUNTING ..."). Loose mentions in
        # guardian lines ("no BATCH CLOSED marker") never count.
        stripped = ln.strip().lstrip("-").strip()
        if stripped.startswith("BATCH CLOSED"):
            marker = ln.strip()
            break
    if marker:
        print(json.dumps({"status": "present", "window": w.date,
                          "marker": marker[:200]}))
        return 0
    s = sp.status(w.date)
    t = s["targets"]
    vc = s["verified_counts"]
    fmt = lambda items: (", ".join(f"#{i['id']} {i['company']}"
                                   for i in items) or "none")
    text = (f"BATCH CLOSED — window {w.date}: FINAL ACCOUNTING (generated "
            f"by spine program): {s['verified_total']} VERIFIED of "
            f"{t['total']} target (LinkedIn {vc.get('LINKEDIN', 0)}/"
            f"{t['linkedin']}, Jobright {vc.get('JOBRIGHT', 0)}/"
            f"{t['jobright']}, Indeed {vc.get('INDEED', 0)}/"
            f"{t.get('indeed', 0)}, LinkedIn alerts "
            f"{vc.get('LINKEDIN_ALERT', 0)}/"
            f"{t.get('linkedin_alert', 0)}). Staged for tap session: "
            f"{fmt(s['staged'])}. "
            f"Awaiting captcha: {fmt(s['captcha'])}. "
            f"Limbo: {fmt(s['limbo'])}. "
            f"Claimed-unfinished: {fmt(s['claimed_unfinished'])}. "
            f"Bench unworked: {fmt(s['bench'])}. "
            f"Awaiting morning report.")
    print(json.dumps({"status": "missing", "window": w.date,
                      "text": text}, indent=1))
    return 0


def cmd_verify_queue(sp: Spine, args) -> int:
    """Drain the post-submission verification queue (audit fix, Nov 4, 2026:
    record() enqueued every submission and nothing ever read the queue, so
    the +10/+30-minute checks existed only on paper). Early check at +10
    min (early-verify only); deciding check at +30 min — found records
    email_verified (skipped when the item is already email-verified);
    a deciding miss writes a verification_missed event and closes the
    entry. The hourly email scan remains the long-tail watcher either
    way. A miss NEVER triggers resubmission."""
    vcfg = sp.rules.get("verification") or {}
    early_min = vcfg.get("early_check_minutes", 10)
    deciding_min = vcfg.get("deciding_check_minutes", 30)
    now = datetime.now(state_mod.CT)
    queue = []
    if sp.verify_queue_file.exists():
        queue = json.loads(sp.verify_queue_file.read_text(encoding="utf-8"))
    st = sp.load_state()
    actions = []
    changed = False
    for e in queue:
        if e.get("done"):
            continue
        sub_dt = datetime.fromisoformat(e["submitted_at"])
        age = (now - sub_dt).total_seconds() / 60
        stages = {c.get("stage") for c in e.get("checks", [])}
        stage = None
        if age >= deciding_min and "deciding" not in stages:
            stage = "deciding"
        elif age >= early_min and "early" not in stages:
            stage = "early"
        if stage is None:
            continue
        item = st.items.get(int(e["item_id"]))
        res = verify_mod.check_confirmation(
            e["company"], sub_dt.date(), role=(item.role if item else ""))
        e.setdefault("checks", []).append({
            "stage": stage, "at": now.isoformat(),
            "found": bool(res.get("found")),
            "message_id": res.get("message_id")})
        changed = True
        if res.get("found"):
            already = bool(item) and any(
                "email-verified" in (ev[3] or "")
                for ev in item.events_of("submitted"))
            # A generic subject ("We received your application") cannot be
            # tied to THIS role when the user has another application at the same
            # company — that exact case exists (#181 Oracle, whose only
            # receipt belongs to a different role). Defer those to the
            # hourly email scan, which reads bodies in full.
            generic = verify_mod.subject_is_generic(res.get("subject") or "")
            others = [o for o in st.items.values()
                      if o.id != int(e["item_id"])
                      and state_mod.normalize_company(o.company)
                      == state_mod.normalize_company(e["company"])
                      and o.submitted_event]
            if already:
                actions.append({"item_id": e["item_id"],
                                "action": "already_verified",
                                "stage": stage})
                e["done"] = True
            elif generic and others:
                actions.append({"item_id": e["item_id"],
                                "action": "deferred_to_scan",
                                "stage": stage,
                                "note": "generic subject + another "
                                        "application at this company"})
                e["done"] = True
                e["deferred"] = True
            else:
                sp.record({"item_id": e["item_id"],
                           "outcome": "email_verified",
                           "message_id": res.get("message_id") or "",
                           "sender": res.get("from") or "",
                           "subject": res.get("subject") or ""},
                          log_path=args.log)
                actions.append({"item_id": e["item_id"],
                                "action": "email_verified", "stage": stage})
                e["done"] = True
        elif stage == "deciding":
            events_mod.append_event(sp.events_path, "verification_missed",
                                    item=int(e["item_id"]))
            e["done"] = True
            e["missed"] = True
            actions.append({"item_id": e["item_id"],
                            "action": "verification_missed"})
    if changed:
        sp.verify_queue_file.write_text(json.dumps(queue, indent=2),
                                        encoding="utf-8")
    print(json.dumps({"checked": len(actions), "actions": actions}, indent=1))
    return 0


def _invite_target(sp: Spine) -> int:
    cfg = sp.rules.get("invitations") or {}
    try:
        return int(cfg.get("daily_target",
                           invitations_mod.DEFAULT_DAILY_TARGET))
    except (TypeError, ValueError):
        return invitations_mod.DEFAULT_DAILY_TARGET


def cmd_invite_status(sp: Spine, args) -> int:
    s = invitations_mod.compute_status(
        sp.events_path, date=args.date, target=_invite_target(sp))
    if args.json:
        print(json.dumps(s, indent=2, default=str))
        return 0
    c = s["counter"]
    print(f"Invitations — {s['date']}: sent {s['sent_on_date']} of "
          f"{s['target']} target; remaining today "
          f"{s['remaining_today']}; all-time {s['all_time']} "
          f"(program count — ground truth)")
    if c["start"] is None and c["end"] is None:
        print("  Sent-People counter: no snapshots recorded for this date")
    else:
        print(f"  Sent-People counter: start {c['start']}, end "
              f"{c['end']}, delta {c['counter_delta']}, recorded "
              f"{c['recorded_that_day']}, discrepancy "
              f"{c['discrepancy']} "
              f"({'RECONCILED' if c['reconciled'] else 'NOT reconciled'}"
              f"{'' if c['reconciled'] is not None else ' — snapshot pair incomplete'})")
        if c["drift_from_prior_end"] is not None:
            print(f"  Drift vs prior day's end counter "
                  f"({c['prior_end']}): {c['drift_from_prior_end']:+d}")
    return 0


def cmd_invite_record(sp: Spine, args) -> int:
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    res = invitations_mod.record_invites(sp.events_path, packet)
    for ev in res["recorded"]:
        print("WROTE:", json.dumps(ev, ensure_ascii=False))
    for ref in res["refused"]:
        print("REFUSED:", ref["error"])
    day = (res["recorded"][-1]["day"] if res["recorded"] else args.date)
    s = invitations_mod.compute_status(
        sp.events_path, date=day, target=_invite_target(sp))
    print(f"Invitations on {s['date']}: {s['sent_on_date']} of "
          f"{s['target']}; remaining {s['remaining_today']}; all-time "
          f"{s['all_time']}")
    return 0 if not res["refused"] else 2


def cmd_invite_targets(sp: Spine, args) -> int:
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    cfg = (sp.rules.get("invitations") or {}).get("hiring_contacts") or {}
    blocked = state_mod.LogState(sp.log_path).blocked_companies
    try:
        out = outreach_targets_mod.validate_targets(packet, cfg, blocked)
    except ValueError as e:
        print(str(e))
        return 2
    for row in out["accepted"]:
        print("ACCEPTED:", json.dumps(row, ensure_ascii=False))
    for row in out["rejected"]:
        print("REJECTED:", json.dumps(row, ensure_ascii=False))
    print(f"Targets decided by code: {len(out['accepted'])} accepted, "
          f"{len(out['rejected'])} rejected; per-role cap from config: "
          f"{out['max_per_role']} (null = no cap)")
    return 0


def _discovery_state_path(sp: Spine) -> Path:
    # Live runs keep discovery state in the program state dir; any
    # non-default setup (a test or a log copy) keeps it beside its own
    # event book, so a test can never touch the live state.
    import pipeline as pipeline_mod
    if Path(sp.events_path) != pipeline_mod.BASE / "events.jsonl":
        return Path(sp.events_path).parent / "discovery.json"
    return sp.state_dir / "discovery.json"


def cmd_discovery_plan(sp: Spine, args) -> int:
    try:
        plans = discovery_mod.build_plan(sp.rules, source=args.source)
    except ValueError as e:
        print(str(e))
        return 2
    print(json.dumps(plans, indent=1, ensure_ascii=False))
    return 0


def cmd_discovery_record(sp: Spine, args) -> int:
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    try:
        row = discovery_mod.record_pass(
            _discovery_state_path(sp), packet, sp.rules)
    except ValueError as e:
        print(str(e))
        return 2
    print("WROTE:", json.dumps(row, ensure_ascii=False))
    cov = discovery_mod.coverage(_discovery_state_path(sp), day=row["day"])
    print(json.dumps(cov, indent=1))
    return 0


def cmd_discovery_status(sp: Spine, args) -> int:
    cov = discovery_mod.coverage(_discovery_state_path(sp), day=args.date)
    if args.json:
        print(json.dumps(cov, indent=1))
        return 0
    print(f"Discovery coverage — {cov['date']}:")
    for source, s in cov["sources"].items():
        print(f"  {source}: {s['passes']} pass(es), "
              f"{s['cards_seen']} cards seen, {s['candidates']} "
              f"candidates, last run {s['last_run_id']}")
    print("  Note: LINKEDIN_ALERT worker passes are always 0 here — "
          "that source is managed by the daily inbox job-alert flow "
          "(inbox.py), whose own state records its passes.")
    return 0


def cmd_invite_counter(sp: Spine, args) -> int:
    ev = invitations_mod.record_counter(
        sp.events_path, args.phase, args.value, day=args.date)
    print("WROTE:", json.dumps(ev, ensure_ascii=False))
    s = invitations_mod.compute_status(
        sp.events_path, date=ev["day"], target=_invite_target(sp))
    c = s["counter"]
    print(f"Counter {ev['day']}: start {c['start']}, end {c['end']}, "
          f"delta {c['counter_delta']}, recorded "
          f"{c['recorded_that_day']}, discrepancy {c['discrepancy']}, "
          f"drift vs prior end {c['drift_from_prior_end']}")
    return 0


def cmd_invite_backfill(sp: Spine, args) -> int:
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    res = invitations_mod.record_backfill(
        sp.events_path, packet.get("days") or [],
        packet.get("counters") or [])
    print(f"Backfilled {len(res['appended'])} day(s); skipped "
          f"{len(res['skipped'])}; counters appended "
          f"{len(res['counters_appended'])}, skipped "
          f"{len(res['counters_skipped'])}")
    for row in res["skipped"] + res["counters_skipped"]:
        print("  SKIPPED:", json.dumps(row, ensure_ascii=False))
    s = invitations_mod.compute_status(
        sp.events_path, target=_invite_target(sp))
    print(f"All-time after backfill: {s['all_time']}")
    return 0


def cmd_clear_friction(sp: Spine, args) -> int:
    print("WROTE:", sp.clear_friction(args.note, log_path=args.log))
    return 0


def cmd_events(sp: Spine, args) -> int:
    for ev in events_mod.read_events(sp.events_path, since=args.since):
        print(json.dumps(ev, ensure_ascii=False))
    return 0


def cmd_state_check(sp: Spine, args) -> int:
    chk = sp.state_check(args.date)
    p, e = chk["prose"], chk["events"]
    print(f"State check — window {chk['window']} "
          f"(prose log vs event stream)")
    print(f"  verified total:  prose {p['verified_total']}   "
          f"events {e['verified_total']}")
    srcs = sorted(set(p["verified_by_source"]) | set(e["verified_by_source"]))
    for src in srcs:
        print(f"  verified {src}: prose "
              f"{len(p['verified_by_source'].get(src, []))}   events "
              f"{len(e['verified_by_source'].get(src, []))}")
    print(f"  staged: prose {len(p['staged'])}   events {len(e['staged'])}")
    print(f"  captcha: prose {len(p['captcha'])}   events {len(e['captcha'])}")
    print(f"  limbo:  prose {len(p['limbo'])}   events {len(e['limbo'])}")
    if chk["divergences"]:
        for d in chk["divergences"]:
            print(f"  DIVERGENCE #{d['item_id']} {d['company']}: "
                  f"prose={d['prose']} events={d['events']}")
    else:
        print("  NO DIVERGENCES")
    print(f"  classification: deep {len(chk['deep_divergences'])} "
          f"(message-worthy only with a counting divergence), "
          f"benign {len(chk['benign_divergences'])} (explained; "
          f"logged only — the user, Nov 5, 2026)")
    for d in chk["deep_divergences"]:
        print(f"  DEEP #{d['item_id']} {d['company']}: {d['reason']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="spine.py")
    ap.add_argument("--log", default=None,
                    help="outreach log path (default: the live log from rules.yaml)")
    ap.add_argument("--events", default=None,
                    help="events.jsonl path (default: program/events.jsonl for "
                         "the live log; derived beside any other log)")
    ap.add_argument("--date", default=None,
                    help="window date YYYY-MM-DD (default: latest batch section)")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--log", default=argparse.SUPPRESS)
    common.add_argument("--events", default=argparse.SUPPRESS)
    common.add_argument("--date", default=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_status = sub.add_parser("status", parents=[common])
    p_status.add_argument("--json", action="store_true")
    sub.add_parser("next", parents=[common])
    p_record = sub.add_parser("record", parents=[common])
    p_record.add_argument("result", help="path to a result JSON file")
    p_verify = sub.add_parser("verify", parents=[common])
    p_verify.add_argument("item", help="item id (164 / #164) or exact company name")
    sub.add_parser("verify-queue", parents=[common])
    p_gate = sub.add_parser("gate", parents=[common])
    p_gate.add_argument("--total", type=int, required=True)
    p_gate.add_argument("--india", type=int, required=True)
    p_gate.add_argument("--source", default="")
    p_gate_packet = sub.add_parser("gate-packet", parents=[common])
    gp = p_gate_packet.add_subparsers(dest="gate_packet_cmd",
                                      required=True)
    gp.add_parser("format")
    p_gp_record = gp.add_parser("record")
    p_gp_record.add_argument(
        "packet", help="JSON packet: {company, source, total, "
                       "south_asia, south_asia_pct, as_of, page, "
                       "item_id?} — see gate-packet format")
    p_gp_notfound = gp.add_parser("not-found")
    p_gp_notfound.add_argument(
        "packet", help="JSON result: {company, run?} — the "
                       "not-found Revelio result; code tracks the "
                       "company as fallback-owed and prints the "
                       "order for the LinkedIn check")
    p_inbox = sub.add_parser("inbox", parents=[common])
    ib = p_inbox.add_subparsers(dest="inbox_cmd", required=True)
    ib.add_parser("format")
    p_ib_intake = ib.add_parser("watch-intake")
    p_ib_intake.add_argument(
        "file", help="JSON list of candidate notification emails "
                     "{gmail_id, sender, subject, date, snippet?, "
                     "body?} — see inbox format")
    p_ib_wrecord = ib.add_parser("watch-record")
    p_ib_wrecord.add_argument(
        "file", help="JSON list of results {gmail_id, person, "
                     "outcome, message_ts, first_words?, claim_key?}")
    ib.add_parser("daily-scope")
    p_ib_drecord = ib.add_parser("daily-record")
    p_ib_drecord.add_argument(
        "file", help="JSON list of results {person, outcome, "
                     "message_ts, first_words?, claim_key?}")
    p_ib_dfinish = ib.add_parser("daily-finish")
    p_ib_dfinish.add_argument(
        "file", help="JSON summary {conversations: {in_scope, "
                     "replied, no_reply, wu_decision}, invitations: "
                     "{found, accepted, skipped}, alerts: {found, "
                     "screened}, note?} — all three sections "
                     "required; the code writes the run line")
    p_ib_check = ib.add_parser("check-claim")
    p_ib_check.add_argument("--person", required=True)
    p_ib_check.add_argument("--message-ts", default=None)
    p_ib_check.add_argument("--claim-key", default="")
    p_ib_iintake = ib.add_parser("invite-intake")
    p_ib_iintake.add_argument(
        "file", help="JSON list of candidate invitation emails "
                     "{gmail_id, sender, subject, date, snippet?, "
                     "body?, links?, html?} — see inbox format")
    p_ib_irecord = ib.add_parser("invite-record")
    p_ib_irecord.add_argument(
        "file", help="JSON list of results {gmail_id, person, "
                     "outcome: accepted | skipped}")
    p_ib_jintake = ib.add_parser("jobalert-intake")
    p_ib_jintake.add_argument(
        "file", help="JSON list of candidate job-alert emails "
                     "{gmail_id, sender, date, snippet?, body?, "
                     "links?, html?} — identified by sender only; "
                     "see inbox format")
    p_ib_jrecord = ib.add_parser("jobalert-record")
    p_ib_jrecord.add_argument(
        "file", help="JSON list of results {gmail_id, "
                     "outcome: screened | skipped}")
    p_pay = sub.add_parser("pay", parents=[common])
    p_pay.add_argument("--equivalent", type=float, default=None)
    p_pay.add_argument("--attainable", type=float, required=True)
    p_pay.add_argument("--basis", choices=["city", "remote_national",
                                           "remote_zone"], default=None)
    p_pay.add_argument("--city", default="")
    sub.add_parser("closeout", parents=[common])
    p_clear = sub.add_parser("clear-friction", parents=[common])
    p_clear.add_argument("--note", required=True)
    p_events = sub.add_parser("events", parents=[common])
    p_events.add_argument("--since", default=None,
                          help="ISO timestamp watermark; only events after it")
    sub.add_parser("state-check", parents=[common])
    p_piles = sub.add_parser("piles", parents=[common])
    p_piles.add_argument("--json", action="store_true")
    p_invite = sub.add_parser("invite", parents=[common])
    inv = p_invite.add_subparsers(dest="invite_cmd", required=True)
    p_inv_status = inv.add_parser("status")
    p_inv_status.add_argument("--date", default=None)
    p_inv_status.add_argument("--json", action="store_true")
    p_inv_record = inv.add_parser("record")
    p_inv_record.add_argument(
        "packet", help="JSON packet: one send {person, note, "
                       "company?, role?, ts?} or {\"invites\": [...]}")
    p_disc = sub.add_parser("discovery", parents=[common])
    disc = p_disc.add_subparsers(dest="discovery_cmd", required=True)
    p_disc_plan = disc.add_parser("plan")
    p_disc_plan.add_argument("--source", default=None,
                             help="JOBRIGHT, INDEED or LINKEDIN_ALERT "
                                  "(default: all three)")
    p_disc_record = disc.add_parser("record")
    p_disc_record.add_argument(
        "packet", help="JSON pass packet {source, run_id, "
                       "searches_done: [{title, location_scope}], "
                       "cards_seen, candidates}")
    p_disc_status = disc.add_parser("status")
    p_disc_status.add_argument("--date", default=None)
    p_disc_status.add_argument("--json", action="store_true")
    p_inv_targets = inv.add_parser("targets")
    p_inv_targets.add_argument(
        "packet", help="JSON packet of contacto people {\"targets\": "
                       "[{person, title, company, type, link, "
                       "current_employee, role?}]} — code returns "
                       "accepted/rejected per rules.yaml "
                       "invitations.hiring_contacts; invite ONLY the "
                       "accepted")
    p_inv_counter = inv.add_parser("counter")
    p_inv_counter.add_argument("--phase", choices=["start", "end"],
                               required=True)
    p_inv_counter.add_argument("--value", type=int, required=True)
    p_inv_counter.add_argument("--date", default=None)
    p_inv_backfill = inv.add_parser("backfill")
    p_inv_backfill.add_argument(
        "packet", help="JSON packet: {\"days\": [{date, count}], "
                       "\"counters\": [{date, phase, counter}]}")
    args = ap.parse_args()
    sp = Spine(log_path=args.log, events_path=args.events)
    if args.cmd == "inbox":
        return cmd_inbox(sp, args)
    if args.cmd == "discovery":
        return {"plan": cmd_discovery_plan,
                "record": cmd_discovery_record,
                "status": cmd_discovery_status}[args.discovery_cmd](sp, args)
    if args.cmd == "invite":
        return {"status": cmd_invite_status,
                "record": cmd_invite_record,
                "targets": cmd_invite_targets,
                "counter": cmd_invite_counter,
                "backfill": cmd_invite_backfill}[args.invite_cmd](sp, args)
    return {"status": cmd_status, "next": cmd_next, "record": cmd_record,
            "verify": cmd_verify, "verify-queue": cmd_verify_queue,
            "gate": cmd_gate, "gate-packet": cmd_gate_packet,
            "pay": cmd_pay, "closeout": cmd_closeout,
            "clear-friction": cmd_clear_friction,
            "events": cmd_events, "state-check": cmd_state_check,
            "piles": cmd_piles}[args.cmd](sp, args)


if __name__ == "__main__":
    raise SystemExit(main())
