#!/usr/bin/env python3
"""Stock-program tests — the standardized stocking handoff (the user,
Nov 5, 2026). All writes go to a temp log.

Coverage:
  (a) a clean PASS item (Jobright, with verified resume) is recorded,
      VERIFIED by re-parse: identity, source (the Jobright tag beats
      the segment-state LinkedIn hint), gate, stocked event, resume.
  (b) a mid-size company (300 total — the old 100–500 alert band)
      lands as a plain PASS with NO alert and an empty
      alert_companies: size alerts removed (the user, Nov 12, 2026).
  (c) size hard pass -> SKIPPED entry, verified, no bench line.
  (d) India-majority hard pass -> SKIPPED + blocked_companies.
  (e) pay below the city equivalent -> SKIPPED with the canonical
      below-pay text, verified.
  (f) dedupe: same company+role as an existing item, and same URL.
  (g) validation refusals quote what was received.
  (h) the handoff check bites: a mangled write lands in "unverified"
      with the discrepancy named, never in "recorded".
  (i) the format text states the form and the verification contract.
  (j) RE-STOCK POOL (the user, Nov 5, 2026): an item skipped ONLY under the
      old city-equivalent pay bar whose figure now meets the universal
      bar is NOT a duplicate — it stocks fresh with restock_of set;
      a still-below-bar figure stays a duplicate; a gate skip stays a
      duplicate at any figure.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "checks"))
import events as events_mod  # noqa: E402
import gate_fallback as gate_fallback_mod  # noqa: E402
import log_writer  # noqa: E402
import state as state_mod  # noqa: E402
import stock  # noqa: E402

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name
          + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


FIXTURE = """# Outreach log (test fixture)

### Blocked companies — THE DEAD-NO-GO ZONE (test fixture)

- Blockedco

## 2026-11-05 — LinkedIn Recommended applications batch — 2026-11-05

- [3:00 PM CST, Mon Oct 26, 2026] STOCKED #100 — Fixture Corp — Data Scientist — source LINKEDIN
- [3:05 PM CST, Mon Oct 26, 2026] SUBMITTED (page-confirmed) — #100 Fixture Corp, Data Scientist (Fixture careers). Confirmation: portal page. SOURCE TAG: LINKEDIN. (Recorded by spine program.)
"""


def item(company, role, source="LINKEDIN", total=3000, india=100,
         figure=250000, basis="city", equivalent=None, **kw):
    pay = {"figure": figure, "basis": basis,
           "city": "Chicago, IL", "source": "bestplaces"}
    if equivalent is not None:
        pay["equivalent"] = equivalent
    base = {"company": company, "role": role, "source": source,
            "url": f"https://example.com/{company.lower().replace(' ', '-')}",
            "gate": {"total": total, "india": india,
                     "source": "Revelio Labs"},
            "pay": pay}
    base.update(kw)
    return base


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "log.md"
        log.write_text(FIXTURE, encoding="utf-8")
        fb = Path(td) / "gate_fallback.json"

        out = stock.record({"items": [
            item("Newco", "Data Scientist", source="JOBRIGHT",
                 resume_file="newco-data-scientist-abc.pdf",
                 resume_verified=True),
        ]}, log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        check("a1 pass item recorded + verified",
              rec.get("verified") is True and rec.get("state") == "bench",
              str(out))
        check("a2 numbering starts after the log max",
              rec.get("id") == 101, str(rec.get("id")))
        landed = rec.get("landed_as") or {}
        check("a3 landed identity/source/gate/resume",
              landed.get("company") == "Newco"
              and landed.get("role") == "Data Scientist"
              and landed.get("source") == "JOBRIGHT"
              and landed.get("gate") == "pass", str(landed))
        st = state_mod.parse_log(str(log))
        check("a4 resume mined by the parser",
              st.items[101].resume_file == "newco-data-scientist-abc.pdf",
              st.items[101].resume_file)

        # STOCKING AS DATA (the user, Nov 6, 2026 — fix #1): the verified
        # item's payload lands in the stocked-items data file and a
        # minimal stocked event lands in the event book, so no
        # reader ever mines the prose for route or salary.
        sfile = Path(td) / "log.stocked.json"
        sdata = json.loads(sfile.read_text(encoding="utf-8")) \
            if sfile.exists() else {}
        srec = sdata.get("101") or {}
        check("a5 stocking written as data (url/pay/gate)",
              srec.get("url") == "https://example.com/newco"
              and (srec.get("pay") or {}).get("figure") == 250000
              and (srec.get("gate") or {}).get("verdict") == "PASS"
              and srec.get("disposition") == "bench",
              str(srec))
        efile = Path(td) / "log.events.jsonl"
        elines = [json.loads(l) for l in
                  efile.read_text(encoding="utf-8").splitlines()
                  if l.strip()] if efile.exists() else []
        check("a6 stocked event is minimal + contract-clean",
              len(elines) == 1 and elines[0].get("type") == "stocked"
              and elines[0].get("item") == 101
              and elines[0].get("src") == "JOBRIGHT"
              and set(elines[0]) <= events_mod.ALLOWED_KEYS,
              str(elines))

        out = stock.record({"items": [
            item("Alertco", "Machine Learning Engineer", total=300,
                 india=20)]}, log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        check("b1 mid-size company lands as plain PASS (no alert band)",
              rec.get("gate") == "PASS"
              and (rec.get("landed_as") or {}).get("gate") == "pass",
              str(out))
        check("b2 no alert company returned (size alerts removed)",
              out["alert_companies"] == [],
              str(out["alert_companies"]))

        out = stock.record({"items": [
            item("Tinyco", "Data Scientist", total=50, india=5)]},
            log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        check("c1 size hard pass skipped + verified",
              rec.get("state") == "skipped_gate"
              and rec.get("verified") is True, str(out))
        check("c2 no bench line for a hard pass",
              "gate-passed — #103" not in log.read_text(encoding="utf-8"))

        out = stock.record({"items": [
            item("Indiaco", "Data Scientist", total=2000, india=1200)]},
            log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        check("d1 India hard pass skipped + company blocked",
              rec.get("state") == "skipped_gate"
              and out["blocked_companies"] == ["Indiaco"], str(out))
        st = state_mod.parse_log(str(log))
        check("d2 the block landed in the log's Blocked companies "
              "section BY CODE (not run prose)",
              "indiaco" in st.blocked_companies,
              str(st.blocked_companies))

        out = stock.record({"items": [
            item("Lowpay", "Data Scientist", figure=90000)]},
            log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        text = log.read_text(encoding="utf-8")
        check("e1 below the universal bar: skipped, bar named",
              rec.get("state") == "skipped_pay"
              and "SKIPPED — BELOW CITY-EQUIVALENT PAY (universal "
              "bar = $200,000 (the user, Nov 5, 2026); posting top/market "
              "$90,000 in Chicago, IL per bestplaces)" in text,
              str(out))
        out = stock.record({"items": [
            item("Sfco", "Data Scientist", figure=210000)]},
            log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        check("e2 $210k city job passes now (old SF bar was $225,654)",
              rec.get("state") == "bench" and rec.get("pay_ok") is True,
              str(out))
        out = stock.record({"items": [
            item("Remotlow", "Data Scientist", figure=110000,
                 basis="remote_national"),
            item("Zonelow", "Data Scientist", figure=150000,
                 basis="remote_zone", equivalent=172000)]},
            log_path=log)
        states = {r["company"]: r["state"] for r in out["recorded"]}
        text = log.read_text(encoding="utf-8")
        check("e3 remote unchanged: national bar $120k, zone keeps "
              "its equivalent",
              states.get("Remotlow") == "skipped_pay"
              and states.get("Zonelow") == "skipped_pay"
              and "remote national bar = $120,000" in text
              and "120k Houston = $172,000 in Chicago, IL per "
              "bestplaces; posting top/market $150,000" in text,
              str(out))

        # NOTE (Nov 13, 2026): the role-match item uses Newco (a
        # stocked, never-applied company) — Fixture Corp now hits
        # the DUPLICATION SCREEN first (it has a verified
        # application, #100) and is recorded as a screen drop;
        # that path is case (m2) below.
        out = stock.record({"items": [
            item("Newco", "Data Scientist",
                 url="https://elsewhere.example.com/x"),
            item("Urlco", "Data Scientist",
                 url="https://example.com/newco"),
        ]}, log_path=log)
        check("f1 duplicates refused (role match + URL match)",
              len(out["duplicates"]) == 2
              and out["duplicates"][0]["existing_id"] == 101
              and not out["recorded"], str(out))

        # CROSS-PLATFORM DUPLICATES (the user, Nov 13, 2026 — the three
        # sources duplicate each other by nature): the same posting
        # found on another platform is caught by its employer/ATS id
        # even under a different title, and by abbreviation-expanded
        # role equality; a different company sharing an id is NOT
        # merged (company guard).
        out = stock.record({"items": [
            item("Crossco", "Senior Data Scientist", source="JOBRIGHT",
                 url="https://job-boards.greenhouse.io/crossco/jobs/"
                     "777001?gh_jid=777001")]}, log_path=log)
        cross_id = out["recorded"][0]["id"] if out["recorded"] else None
        check("f2 cross-platform original stocks",
              out["recorded"] and out["recorded"][0]["state"] == "bench",
              str(out))
        out = stock.record({"items": [
            item("Crossco", "Machine Learning Engineer",
                 source="INDEED",
                 url="https://job-boards.greenhouse.io/crossco/jobs/"
                     "777001")]}, log_path=log)
        check("f2 same ATS posting id on another platform = "
              "duplicate, even with a different title",
              len(out["duplicates"]) == 1
              and out["duplicates"][0]["existing_id"] == cross_id
              and out["duplicates"][0]["source"] == "INDEED"
              and not out["recorded"], str(out))
        out = stock.record({"items": [
            item("Crossco", "Sr. Data Scientist", source="INDEED",
                 url="https://www.indeed.com/viewjob?jk=zzz999")]},
            log_path=log)
        check("f2 abbreviation twin title (Sr. = Senior) on another "
              "platform = duplicate",
              len(out["duplicates"]) == 1
              and out["duplicates"][0]["existing_id"] == cross_id,
              str(out))
        out = stock.record({"items": [
            item("Otherco", "Machine Learning Engineer",
                 source="INDEED",
                 url="https://boards.greenhouse.io/otherco/jobs/"
                     "777001?gh_jid=777001")]}, log_path=log)
        check("f2 same ATS id at a DIFFERENT company is not merged",
              len(out["recorded"]) == 1 and not out["duplicates"],
              str(out))
        import posting_identity as _pi
        check("f2 posting_identity units: expanded role keys equal, "
              "ids extracted from URLs and req text",
              _pi.role_key("Acme", "Sr. ML Engineer")
              == _pi.role_key("Acme", "Senior Machine Learning Engineer")
              and "777001" in _pi.extract_ids(
                  "https://job-boards.greenhouse.io/x/jobs/777001")
              and "448729" in _pi.extract_ids("req R448729"))

        out = stock.record({"items": [
            item("Badco", "Data Scientist", source="LINKED"),
            item("Badgate", "Data Scientist", total=100, india=200),
            item("Badresume", "Data Scientist",
                 resume_file="x.pdf", resume_verified=False),
        ]}, log_path=log)
        msgs = " | ".join(e["error"] for e in out["errors"])
        check("g1 refusals quote what was received",
              len(out["errors"]) == 3 and "'LINKED'" in msgs
              and "exceeds total" in msgs
              and "resume_verified" in msgs, msgs)

        orig_append = log_writer.append_entry

        def mangling(path, text, when=None):
            if text.startswith("STOCKED — #") and "Mangleco" in text:
                text = text.replace("Mangleco, ", ", ")
            return orig_append(path, text, when)

        log_writer.append_entry = mangling
        try:
            out = stock.record({"items": [
                item("Mangleco", "Data Scientist")]}, log_path=log)
        finally:
            log_writer.append_entry = orig_append
        check("h1 mangled write is unverified, never recorded",
              not out["recorded"] and len(out["unverified"]) == 1
              and bool(out["unverified"][0].get("problems"))
              and (out["unverified"][0].get("landed_as") or {})
              .get("role") != "Data Scientist",
              str(out))

        check("i1 format states the form + verification contract",
              all(s in stock.FORMAT_TEXT for s in
                  ("company", "gate", "pay", "landed_as", "verified")),
              "")

        # (j) re-stock pool: append old-bar skip fixtures in the exact
        # shapes the pre-v2 writer produced.
        old = (
            "- [3:10 PM CST, Fri Oct 30, 2026] STOCKED — #90 Oldbar "
            "Co, Data Scientist — San Francisco, CA — apply: "
            "https://example.com/oldbar. SOURCE TAG: LINKEDIN. "
            "(Recorded by stock program.)\n"
            "- [3:11 PM CST, Fri Oct 30, 2026] GATE PASS — #90 Oldbar "
            "Co — LinkedIn People: #90 Oldbar Co 3,000 / 100 (3.3%) "
            "→ verdict PASS. (Recorded by stock program.)\n"
            "- [3:12 PM CST, Fri Oct 30, 2026] SKIPPED — BELOW "
            "CITY-EQUIVALENT PAY (120k Houston = $223,275 in San "
            "Francisco, CA per bestplaces; posting top/market "
            "$205,000) — #90 Oldbar Co, Data Scientist. (Recorded by "
            "stock program.)\n"
            "- [3:13 PM CST, Fri Oct 30, 2026] STOCKED — #91 Stillbar "
            "Co, Data Scientist — San Francisco, CA — apply: "
            "https://example.com/stillbar. SOURCE TAG: LINKEDIN. "
            "(Recorded by stock program.)\n"
            "- [3:14 PM CST, Fri Oct 30, 2026] GATE PASS — #91 "
            "Stillbar Co — LinkedIn People: #91 Stillbar Co 3,000 / "
            "100 (3.3%) → verdict PASS. (Recorded by stock program.)\n"
            "- [3:15 PM CST, Fri Oct 30, 2026] SKIPPED — BELOW "
            "CITY-EQUIVALENT PAY (120k Houston = $223,275 in San "
            "Francisco, CA per bestplaces; posting top/market "
            "$195,000) — #91 Stillbar Co, Data Scientist. (Recorded "
            "by stock program.)\n"
            "- [3:16 PM CST, Fri Oct 30, 2026] STOCKED — #92 Gatefail "
            "Co, Data Scientist — apply: https://example.com/gatefail"
            ". SOURCE TAG: LINKEDIN. (Recorded by stock program.)\n"
            "- [3:17 PM CST, Fri Oct 30, 2026] SKIPPED — GATE "
            "HARD_PASS_INDIA_BLOCK (2,000 total / 1,200 India "
            "(60.0%) per LinkedIn People; company blocked) — #92 "
            "Gatefail Co, Data Scientist. (Recorded by stock "
            "program.)\n")
        with log.open("a", encoding="utf-8") as f:
            f.write(old)

        out = stock.record({"items": [
            item("Oldbar Co", "Data Scientist", figure=205000,
                 url="https://example.com/oldbar")]}, log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        check("j1 old-bar pay skip at $205k re-stocks as bench",
              rec.get("state") == "bench"
              and rec.get("restock_of") == 90
              and not out["duplicates"]
              and "RE-STOCK of #90" in log.read_text(encoding="utf-8"),
              str(out))
        out = stock.record({"items": [
            item("Stillbar Co", "Data Scientist", figure=195000,
                 url="https://example.com/stillbar")]}, log_path=log)
        check("j2 still below the bar stays a duplicate",
              len(out["duplicates"]) == 1 and not out["recorded"],
              str(out))
        out = stock.record({"items": [
            item("Gatefail Co", "Data Scientist", figure=250000,
                 url="https://example.com/gatefail")]}, log_path=log)
        check("j3 gate skip stays a duplicate at any figure",
              len(out["duplicates"]) == 1 and not out["recorded"],
              str(out))


        # (k) LINKEDIN_ALERT source + GATE AT IDENTIFICATION
        # (the user, Nov 12, 2026): the alert source stocks like any
        # other; a deferred gate is REFUSED for new stocks under
        # gate.timing on_identification; the gate packet form is
        # validated and mapped (Revelio South Asia -> India) in
        # code; a hard-pass packet skips + blocks.
        out = stock.record({"items": [
            item("Alertsource Co", "Data Scientist",
                 source="LINKEDIN_ALERT")]}, log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        check("k1 LINKEDIN_ALERT item stocks to the bench",
              rec.get("state") == "bench"
              and (rec.get("landed_as") or {}).get("source")
              == "LINKEDIN_ALERT", str(out))

        out = stock.record({"items": [
            item("Deferredco", "Data Scientist",
                 gate={"deferred": True})]}, log_path=log)
        msgs = " | ".join(e["error"] for e in out["errors"])
        check("k2 deferred gate refused under on_identification",
              not out["recorded"] and len(out["errors"]) == 1
              and "AT IDENTIFICATION" in msgs, msgs)

        packet_item = item("Packetco", "Data Scientist")
        packet_item["gate"] = {
            "source": "Revelio Labs", "total": 3000,
            "south_asia": 100, "south_asia_pct": 3.3,
            "as_of": "2026-06",
            "page": "https://www.reveliolabs.com/companies/packetco"}
        out = stock.record({"items": [packet_item]}, log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        check("k3 gate packet form stocks, verdict PASS",
              rec.get("state") == "bench" and rec.get("gate") == "PASS",
              str(out))

        hard_item = item("Hardpacket Co", "Data Scientist")
        hard_item["gate"] = {
            "source": "Revelio Labs", "total": 2000,
            "south_asia": 1200, "south_asia_pct": 60.0,
            "as_of": "2026-06",
            "page": "https://www.reveliolabs.com/companies/hardpacket"}
        out = stock.record({"items": [hard_item]}, log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        check("k4 hard-pass packet: skipped + company blocked",
              rec.get("state") == "skipped_gate"
              and out["blocked_companies"] == ["Hardpacket Co"],
              str(out))
        st = state_mod.parse_log(str(log))
        check("k4b the packet hard-pass block also landed in "
              "the log's Blocked companies section by code",
              "hardpacket co" in st.blocked_companies,
              str(st.blocked_companies))

        bad_item = item("Badpacket Co", "Data Scientist")
        bad_item["gate"] = {
            "source": "Revelio Labs", "total": 2000,
            "south_asia": 1200, "south_asia_pct": 12.0,
            "as_of": "2026-06",
            "page": "https://www.reveliolabs.com/companies/badpacket"}
        out = stock.record({"items": [bad_item]}, log_path=log)
        msgs = " | ".join(e["error"] for e in out["errors"])
        check("k5 inconsistent gate packet refused whole",
              not out["recorded"] and "gate packet refused" in msgs,
              msgs)

        # REVELIO-NOT-FOUND (the user, Nov 12, 2026; LINKEDIN FALLBACK
        # Nov 13, 2026; THE CODE STEP Nov 13, 2026): a company not
        # on Revelio is gated on LinkedIn — but only on CODE'S
        # ORDER. The worker hands the not-found result to code;
        # code tracks the company as fallback-owed and returns
        # the order; the LinkedIn packet or the linkedin_checked
        # drop records only against that open order. Only when
        # LinkedIn also gives no usable counts is the company
        # dropped — skipped in code with the drop reason, never
        # stocked, NOT blocked, and a later posting from the same
        # company is re-checked.
        out = stock.record({"items": [
            item("Ghostco", "Data Scientist",
                 gate={"revelio_not_found": True,
                       "linkedin_checked": True})]},
            log_path=log, fallback_state_path=fb)
        msgs = " | ".join(e["error"] for e in out["errors"])
        check("k6a drop with NO open code order refused — the "
              "LinkedIn check runs only on code's order",
              not out["recorded"] and "no fallback order" in msgs,
              msgs)
        out = stock.record({"items": [
            item("Ghostco", "Data Scientist",
                 gate={"revelio_not_found": True})]},
            log_path=log, fallback_state_path=fb)
        orders = out.get("fallback_orders") or []
        check("k6h bare not-found hand-in: code tracks the "
              "company as fallback-owed and returns the ORDER — "
              "nothing stocked, no error",
              not out["recorded"] and not out["errors"]
              and len(orders) == 1
              and "LinkedIn company People page" in
                  " ".join(orders[0]["order"])
              and gate_fallback_mod.pending_for(
                  "Ghostco", state_path=fb) is not None, str(out))
        out = stock.record({"items": [
            item("Ghostco", "Data Scientist",
                 gate={"revelio_not_found": True,
                       "linkedin_checked": True})]},
            log_path=log, fallback_state_path=fb)
        rec = out["recorded"][0] if out["recorded"] else {}
        log_text = log.read_text(encoding="utf-8")
        check("k6 not on Revelio + LinkedIn checked (on code's "
              "order): dropped, reason logged, company NOT "
              "blocked, order cleared",
              rec.get("state") == "skipped_gate"
              and "company not found on Revelio and the LinkedIn "
                  "fallback check gave no usable counts" in log_text
              and out["blocked_companies"] == []
              and gate_fallback_mod.pending_for(
                  "Ghostco", state_path=fb) is None, str(out))
        out = stock.record({"items": [
            item("Ghosttwo Co", "Data Scientist",
                 gate={"revelio_not_found": True})]},
            log_path=log, fallback_state_path=fb)
        check("k6c a second bare hand-in also returns an order "
              "(idempotent tracking)",
              not out["recorded"] and not out["errors"]
              and len(out.get("fallback_orders") or []) == 1
              and gate_fallback_mod.pending_for(
                  "Ghosttwo Co", state_path=fb) is not None,
              str(out))
        ghost_id = rec.get("id")
        out = stock.record({"items": [
            item("Ghostco", "Data Scientist")]}, log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        check("k6b same company re-checked fresh after a drop",
              rec.get("state") == "bench"
              and rec.get("restock_of") == ghost_id, str(out))

        # A non-Revelio approved-source packet can no longer stock
        # a new item (fallback chain superseded for new work).
        lead_item = item("Leadco", "Data Scientist")
        lead_item["gate"] = {
            "source": "LeadIQ", "total": 3000, "india": 100,
            "india_pct": 3.3, "as_of": "2026-06",
            "page": "https://leadiq.com/c/leadco"}
        out = stock.record({"items": [lead_item]}, log_path=log)
        msgs = " | ".join(e["error"] for e in out["errors"])
        check("k7 non-Revelio packet cannot stock a new item",
              not out["recorded"]
              and "Revelio-first" in msgs, msgs)

        out = stock.record({"items": [
            item("Peopleco", "Data Scientist",
                 gate={"total": 3000, "india": 100,
                       "source": "LinkedIn People"})]}, log_path=log)
        msgs = " | ".join(e["error"] for e in out["errors"])
        check("k8 counts-form gate with a non-Revelio source refused",
              not out["recorded"]
              and "requires a Revelio Labs verdict" in msgs, msgs)

        # Distinct case: listed on Revelio, counts unusable.
        out = stock.record({"items": [
            item("Thinco", "Data Scientist",
                 gate={"revelio_insufficient": True})]}, log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        log_text = log.read_text(encoding="utf-8")
        check("k9 revelio_insufficient: skipped with its own reason, "
              "no block",
              rec.get("state") == "skipped_gate"
              and "Revelio data insufficient" in log_text
              and out["blocked_companies"] == [], str(out))

        # PAST-24-HOURS SCAN WINDOW (the user, Nov 12, 2026): stock.py
        # refuses a Jobright/Indeed stock whose KNOWN age is over
        # 24h; unknown age allowed; LINKEDIN_ALERT exempt.
        out = stock.record({"items": [
            item("Oldco", "Data Scientist", source="JOBRIGHT",
                 posted_age_hours=30)]}, log_path=log)
        msgs = " | ".join(e["error"] for e in out["errors"])
        check("l1 Jobright stock at 30h refused by the 24h window",
              not out["recorded"] and "discovery window" in msgs,
              msgs)
        out = stock.record({"items": [
            item("Olddeed Co", "Data Scientist", source="INDEED",
                 posted_text="2 days ago")]}, log_path=log)
        msgs = " | ".join(e["error"] for e in out["errors"])
        check("l2 Indeed stock '2 days ago' refused",
              not out["recorded"] and "discovery window" in msgs,
              msgs)
        out = stock.record({"items": [
            item("Freshco", "Data Scientist", source="JOBRIGHT",
                 posted_age_hours=5)]}, log_path=log)
        check("l3 Jobright stock at 5h stocks",
              bool(out["recorded"]), str(out["errors"]))
        out = stock.record({"items": [
            item("Alertold Co", "Data Scientist",
                 source="LINKEDIN_ALERT", posted_age_hours=100)]},
            log_path=log)
        check("l4 LINKEDIN_ALERT stock is exempt from the age rule",
              bool(out["recorded"]), str(out["errors"]))
        out = stock.record({"items": [
            item("Noage Co", "Data Scientist", source="INDEED")]},
            log_path=log)
        check("l5 unknown posting age is allowed (scan boundary "
              "is the control)",
              bool(out["recorded"]), str(out["errors"]))

        # (m) SCREENING ORDER (the user, Nov 13, 2026 — burned into
        # code, not agent judgment): (1) blacklist, (2) duplication
        # against the all-time applied record, (3) the Revelio
        # gate with the LinkedIn fallback. Screens 1-2 run in
        # record() itself, off the program's own records.
        out = stock.record({"items": [
            item("Blockedco", "Data Scientist")]}, log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        log_text = log.read_text(encoding="utf-8")
        check("m1 blacklist screen: blocked company dropped in "
              "code, before any gate math",
              rec.get("gate") == "DROPPED_BLOCKED_COMPANY"
              and rec.get("state") == "skipped_blocked"
              and rec.get("verified") is True
              and "BLOCKED company (blacklist" in log_text,
              str(out))

        out = stock.record({"items": [
            item("Fixture Corp", "Machine Learning Engineer",
                 url="https://example.com/fixture-mle")]},
            log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        log_text = log.read_text(encoding="utf-8")
        check("m2 duplication screen: already-applied company "
              "dropped before the gate (new role, new URL)",
              rec.get("gate") == "DROPPED_DUPLICATE_COMPANY"
              and rec.get("state") == "skipped_duplicate"
              and rec.get("verified") is True
              and "DUPLICATE company — already applied" in log_text,
              str(out))

        out = stock.record({"items": [
            item("Fixture Corp", "AI Researcher",
                 url="https://example.com/fixture-oneoff",
                 wu_directed=True)]}, log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        check("m3 wu_directed one-off is exempt from the "
              "duplication screen and stocks to the bench",
              rec.get("state") == "bench"
              and rec.get("verified") is True, str(out))

        # Screen forms: no gate counts, no pay research — the
        # program records the screen drop itself (the alert lane
        # has no pay data at list stage).
        out = stock.record({"items": [
            {"company": "Fixture Corp", "role": "Data Scientist",
             "source": "JOBRIGHT",
             "url": "https://example.com/screen-dup",
             "gate": {"screen_only": True}}]}, log_path=log)
        rec = out["recorded"][0] if out["recorded"] else {}
        check("m4 screen form at an applied company records the "
              "duplication drop with no gate/pay research",
              rec.get("gate") == "DROPPED_DUPLICATE_COMPANY"
              and rec.get("verified") is True, str(out))

        out = stock.record({"items": [
            {"company": "Screenfresh Co", "role": "Data Scientist",
             "source": "JOBRIGHT",
             "url": "https://example.com/screen-fresh",
             "gate": {"screen_only": True}}]}, log_path=log)
        msgs = " | ".join(e["error"] for e in out["errors"])
        check("m5 screen form passing both screens is refused — "
              "vet fully, then stock the full form",
              not out["recorded"]
              and "passed the blacklist and duplication screens"
              in msgs, msgs)

        # LINKEDIN FALLBACK (the user, Nov 13, 2026): a company not on
        # Revelio is gated on LinkedIn — packet form first, and
        # only on code's order: the not-found hand-in opens the
        # pending record, the packet then records against it and
        # clears it.
        stock.record({"items": [
            item("Fallbackco", "Data Scientist",
                 gate={"revelio_not_found": True})]},
            log_path=log, fallback_state_path=fb)
        fb_item = item("Fallbackco", "Data Scientist")
        fb_item["gate"] = {
            "source": "LinkedIn People", "total": 1500,
            "india": 100, "india_pct": 6.7, "as_of": "2026-11",
            "page": "https://www.linkedin.com/company/fallbackco",
            "revelio_not_found": True}
        out = stock.record({"items": [fb_item]}, log_path=log,
                           fallback_state_path=fb)
        rec = out["recorded"][0] if out["recorded"] else {}
        check("m6 LinkedIn fallback packet stocks to the bench "
              "(order cleared on record)",
              rec.get("state") == "bench"
              and rec.get("gate") == "PASS"
              and rec.get("verified") is True
              and gate_fallback_mod.pending_for(
                  "Fallbackco", state_path=fb) is None, str(out))

        fb2_item = item("Fallbacktwo Co", "Data Scientist")
        fb2_item["gate"] = {
            "source": "LinkedIn People", "total": 1500,
            "india": 100, "india_pct": 6.7, "as_of": "2026-11",
            "page": "https://www.linkedin.com/company/fallbacktwo"}
        out = stock.record({"items": [fb2_item]}, log_path=log)
        msgs = " | ".join(e["error"] for e in out["errors"])
        check("m7 LinkedIn packet WITHOUT the not-on-Revelio "
              "marker is refused",
              not out["recorded"]
              and "revelio_not_found" in msgs, msgs)

        stock.record({"items": [
            item("Fallbackthree Co", "Data Scientist",
                 gate={"revelio_not_found": True})]},
            log_path=log, fallback_state_path=fb)
        out = stock.record({"items": [
            item("Fallbackthree Co", "Data Scientist",
                 gate={"total": 1500, "india": 100,
                       "source": "LinkedIn People",
                       "revelio_not_found": True})]},
            log_path=log, fallback_state_path=fb)
        rec = out["recorded"][0] if out["recorded"] else {}
        check("m8 counts-form LinkedIn fallback stocks",
              rec.get("state") == "bench"
              and rec.get("gate") == "PASS", str(out))

        out = stock.record({"items": [
            item("Fallbackfour Co", "Data Scientist",
                 gate={"total": 1500, "india": 100,
                       "source": "LinkedIn People",
                       "revelio_not_found": True})]},
            log_path=log, fallback_state_path=fb)
        msgs = " | ".join(e["error"] for e in out["errors"])
        check("m9 LinkedIn fallback packet with NO open code "
              "order refused (self-directed check)",
              not out["recorded"] and "no fallback order" in msgs,
              msgs)

        # LOCATION DICTIONARY AT STOCKING (the user, Nov 13, 2026):
        # the packet's total is the associated-members number;
        # code derives the South Asia count from the marked
        # location rows and appends the packet itself to the
        # log next to the verdict.
        stock.record({"items": [
            item("Fallbackfive Co", "Data Scientist",
                 gate={"revelio_not_found": True})]},
            log_path=log, fallback_state_path=fb)
        fb5_item = item("Fallbackfive Co", "Data Scientist")
        fb5_item["gate"] = {
            "source": "LinkedIn People", "total": 1000,
            "locations": [
                {"label": "Maharashtra, India", "count": 120,
                 "south_asia": True},
                {"label": "Greater Delhi Area", "count": 80,
                 "south_asia": True},
                {"label": "United States", "count": 700,
                 "south_asia": False}],
            "as_of": "2026-11",
            "page": "https://www.linkedin.com/company/"
                    "fallbackfive",
            "revelio_not_found": True}
        out = stock.record({"items": [fb5_item]}, log_path=log,
                           fallback_state_path=fb)
        rec = out["recorded"][0] if out["recorded"] else {}
        log_text = log.read_text(encoding="utf-8")
        check("m10 location-dictionary packet stocks: code "
              "counted 200/1000 and appended the packet",
              rec.get("state") == "bench"
              and rec.get("gate") == "PASS"
              and rec.get("verified") is True
              and "GATE LOCATION PACKET" in log_text
              and "Greater Delhi Area 80 [South Asia]" in log_text
              and "Greater Delhi Area = 200 of 1,000 (20.0%)"
              in log_text, str(out))

    if FAILS:
        print(f"\n{len(FAILS)} FAILURE(S): {FAILS}")
        return 1
    print("\nALL STOCK TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
