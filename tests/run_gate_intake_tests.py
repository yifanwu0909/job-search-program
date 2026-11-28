#!/usr/bin/env python3
"""Gate-intake tests — the forward-movement company-gate packet
(the user, Nov 12, 2026). All writes go to a temp log.

Coverage:
  (a) a Revelio PASS packet records against the submitted item:
      South Asia mapped to India in code, the verdict line written
      in stock.py's GATE PASS format, landed gate=pass, the item's
      state untouched (still submitted).
  (b) a mid-size company (300 total — the old 100–500 band) records
      a plain PASS, alert flag false, lands gate=pass: size alerts
      removed (the user, Nov 12, 2026).
  (c) size hard pass -> GATE HARD PASS line, landed gate=fail, NO
      skipped outcome on the already-submitted item, no block.
  (d) India-majority via the South Asia count -> HARD_PASS_INDIA_
      BLOCK with block_company true, landed gate=fail.
  (e) the real TCS packet (verified on the live Revelio page,
      Nov 12, 2026) decides HARD_PASS_INDIA_BLOCK with the South
      Asia count as the India figure.
  (f) a non-Revelio packet (LeadIQ) is REFUSED whole — vetting is
      Revelio-first (the user, Nov 12, 2026); the LINKEDIN FALLBACK
      (the user, Nov 13, 2026): a LinkedIn People packet validates and
      records ONLY with "revelio_not_found": true, and is refused
      without the marker — and, under the CODE STEP (the user,
      Nov 13, 2026), records only against an open code order:
      the not-found result is handed to code first, code tracks
      the company as fallback-owed and issues the order, and a
      packet with no matching pending record is refused whole.
  (g) validation refusals write NOTHING: inconsistent percent,
      count over total, unapproved source, unknown field, Revelio
      packet carrying india instead of south_asia, bad page URL,
      non-positive total, item/company mismatch.
  (h) item resolution: an ambiguous company (two submitted items)
      is refused without item_id and records with it; a company
      with no item in the log is refused.
  (i) the format text states the packet fields + the contract.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "checks"))
import gate_fallback as gate_fallback_mod  # noqa: E402
import gate_intake  # noqa: E402
import state as state_mod  # noqa: E402

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name
          + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def _lines(iid: int, company: str) -> str:
    slug = company.lower().replace(" ", "-")
    return (
        f"- [9:00 AM CST, Thu Nov 12, 2026] STOCKED — #{iid} "
        f"{company}, Data Scientist — apply: "
        f"https://example.com/{slug}. SOURCE TAG: JOBRIGHT. "
        f"(Recorded by stock program.)\n"
        f"- [9:01 AM CST, Thu Nov 12, 2026] GATE DEFERRED — #{iid} "
        f"{company} — company check deferred until forward movement "
        f"(the user, Nov 11, 2026). (Recorded by stock program.)\n"
        f"- [9:02 AM CST, Thu Nov 12, 2026] SUBMITTED "
        f"(page-confirmed) — #{iid} {company}, Data Scientist "
        f"(Greenhouse). Confirmation: portal page. SOURCE TAG: "
        f"JOBRIGHT. (Recorded by spine program.)\n")


FIXTURE = ("# Outreach log (test fixture)\n\n"
           "## 2026-11-12 — LinkedIn Recommended applications batch "
           "— 2026-11-12\n\n"
           + _lines(100, "Passco")
           + _lines(101, "Alertco")
           + _lines(102, "Tinyco")
           + _lines(103, "Tata Consultancy Services")
           + _lines(104, "Leadco")
           + _lines(105, "Dupe Co")
           + _lines(106, "Dupe Co"))


def revelio(company, total, sa, pct, **kw):
    pkt = {"company": company, "source": "Revelio Labs",
           "total": total, "south_asia": sa, "south_asia_pct": pct,
           "as_of": "2026-06",
           "page": "https://www.reveliolabs.com/companies/x/employees"}
    pkt.update(kw)
    return pkt


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "log.md"
        log.write_text(FIXTURE, encoding="utf-8")
        fb = Path(td) / "gate_fallback.json"

        out = gate_intake.record_packet(
            revelio("Passco", 3000, 100, 3.3), log_path=log)
        check("a1 Revelio PASS recorded + verified",
              out["recorded"] is True and out["verified"] is True
              and out["verdict"] == "PASS", str(out))
        check("a2 South Asia mapped to the India figure in code",
              out["india"] == 100 and out["india_basis"] == "south_asia",
              str(out))
        st = state_mod.parse_log(str(log))
        check("a3 landed gate=pass, item still submitted",
              st.items[100].gate == "pass"
              and st.items[100].state == "submitted",
              f"gate={st.items[100].gate} state={st.items[100].state}")
        check("a4 verdict line in the stock format",
              "GATE PASS — #100 Passco — Revelio Labs: #100 Passco "
              "3,000 / 100 (3.3%) → verdict PASS." in
              log.read_text(encoding="utf-8"))

        out = gate_intake.record_packet(
            revelio("Alertco", 300, 20, 6.7), log_path=log)
        st = state_mod.parse_log(str(log))
        check("b1 mid-size: plain PASS, no alert flag, landed pass",
              out["verdict"] == "PASS" and out["alert"] is False
              and st.items[101].gate == "pass", str(out))

        out = gate_intake.record_packet(
            revelio("Tinyco", 50, 5, 10.0), log_path=log)
        st = state_mod.parse_log(str(log))
        kinds = [e[2] for e in st.items[102].events]
        check("c1 size hard pass: verdict, no block, landed fail",
              out["verdict"] == "HARD_PASS_SIZE"
              and out["block_company"] is False
              and st.items[102].gate == "fail", str(out))
        check("c2 the submitted item gains NO skipped outcome",
              st.items[102].state == "submitted"
              and "skipped" not in kinds,
              f"state={st.items[102].state} kinds={kinds}")
        check("c3 GATE HARD PASS line written",
              "GATE HARD PASS — #102 Tinyco" in
              log.read_text(encoding="utf-8"))

        out = gate_intake.record_packet(
            revelio("Tata Consultancy Services", 2053083, 1810203,
                    88.6,
                    page="https://www.reveliolabs.com/companies/"
                         "tata-consultancy-services-ltd/employees"),
            log_path=log)
        st = state_mod.parse_log(str(log))
        check("e1 TCS packet: HARD_PASS_INDIA_BLOCK on South Asia",
              out["verdict"] == "HARD_PASS_INDIA_BLOCK"
              and out["block_company"] is True
              and out["india"] == 1810203
              and st.items[103].gate == "fail"
              and st.items[103].state == "submitted", str(out))

        # REVELIO-FIRST VETTING (the user, Nov 12, 2026; the LinkedIn
        # fallback for not-on-Revelio companies was added
        # Nov 13, 2026 — case f2-f4 below): a non-Revelio packet
        # outside the fallback is refused whole, for every gate
        # use; nothing is written.
        before_f = log.read_text(encoding="utf-8")
        f1_refused = False
        try:
            gate_intake.record_packet(
                {"company": "Leadco", "source": "LeadIQ", "total": 5400,
                 "india": 206, "india_pct": 3.8, "as_of": "2026-11",
                 "page": "https://leadiq.com/c/wex/123"}, log_path=log)
        except ValueError:
            f1_refused = True
        st = state_mod.parse_log(str(log))
        check("f1 non-Revelio packet refused whole (Revelio-first)",
              f1_refused
              and log.read_text(encoding="utf-8") == before_f
              and st.items[104].gate == "deferred",
              f"refused={f1_refused} gate={st.items[104].gate}")

        # LINKEDIN FALLBACK (the user, Nov 13, 2026): a company NOT on
        # Revelio is gated on LinkedIn instead (headcount first,
        # then the India ratio) — the packet must attest the
        # Revelio lookup with "revelio_not_found": true.
        clean, prob = gate_intake.validate_packet(
            {"company": "Leadco", "source": "LinkedIn People",
             "total": 5400, "india": 206, "india_pct": 3.8,
             "as_of": "2026-11",
             "page": "https://www.linkedin.com/company/leadco",
             "revelio_not_found": True})
        check("f2 LinkedIn fallback packet validates with the "
              "marker; the india count is read directly",
              prob is None and clean["source"] == "LinkedIn People"
              and clean["india"] == 206
              and clean["india_basis"] == "india", str(prob))
        clean2, prob2 = gate_intake.validate_packet(
            {"company": "Leadco", "source": "LinkedIn People",
             "total": 5400, "india": 206, "india_pct": 3.8,
             "as_of": "2026-11",
             "page": "https://www.linkedin.com/company/leadco"})
        check("f3 LinkedIn packet without the marker is refused",
              clean2 is None and prob2 is not None
              and "revelio_not_found" in prob2, str(prob2))
        fb_packet = {"company": "Leadco",
                     "source": "LinkedIn People",
                     "total": 5400, "india": 206, "india_pct": 3.8,
                     "as_of": "2026-11",
                     "page": "https://www.linkedin.com/company/"
                             "leadco",
                     "revelio_not_found": True}
        before_f4 = log.read_text(encoding="utf-8")
        f4a_refused = False
        try:
            gate_intake.record_packet(
                fb_packet, log_path=log, fallback_state_path=fb)
        except ValueError:
            f4a_refused = True
        check("f4a fallback packet with NO open code order "
              "refused whole — the code step between Revelio "
              "and LinkedIn owns the sequence",
              f4a_refused
              and log.read_text(encoding="utf-8") == before_f4)
        gate_fallback_mod.open_pending("Leadco", state_path=fb)
        out = gate_intake.record_packet(
            fb_packet, log_path=log, fallback_state_path=fb)
        st = state_mod.parse_log(str(log))
        check("f4 fallback verdict records against the item "
              "(pending order cleared on record)",
              out["verdict"] == "PASS"
              and st.items[104].gate == "pass"
              and "LinkedIn People" in log.read_text(
                  encoding="utf-8")
              and gate_fallback_mod.pending_for(
                  "Leadco", state_path=fb) is None, str(out))

        # LOCATION DICTIONARY (the user, Nov 13, 2026, with
        # screenshots): total = the "associated members" number
        # at the top; the South Asia count comes from the marked
        # "Where they live" rows. Her first screenshot: India
        # 298 with Karnataka 204, Greater Bengaluru Area 204 and
        # Bengaluru 194 nested below it — the country row IS
        # the count (298/339 = 87.9%), never the nested sum.
        shot_one = {"company": "Leadco",
                    "source": "LinkedIn People",
                    "total": 339,
                    "locations": [
                        {"label": "India", "count": 298,
                         "south_asia": True},
                        {"label": "Karnataka, India", "count": 204,
                         "south_asia": True},
                        {"label": "Greater Bengaluru Area",
                         "count": 204, "south_asia": True},
                        {"label": "Bengaluru, Karnataka, India",
                         "count": 194, "south_asia": True},
                        {"label": "United States", "count": 34,
                         "south_asia": False}],
                    "as_of": "2026-11",
                    "page": "https://www.linkedin.com/company/"
                            "leadco",
                    "revelio_not_found": True}
        clean, prob = gate_intake.validate_packet(shot_one)
        check("f5 location dictionary: country row counted "
              "once, nested rows not double-counted",
              prob is None and clean["india"] == 298
              and abs(clean["region_pct"] - 87.9) < 0.1
              and clean["south_asia_counted_labels"] == ["India"],
              str(prob))
        regional = {"company": "Leadco",
                    "source": "LinkedIn People",
                    "total": 1000,
                    "locations": [
                        {"label": "Maharashtra, India",
                         "count": 120, "south_asia": True},
                        {"label": "Greater Delhi Area",
                         "count": 80, "south_asia": True},
                        {"label": "United States", "count": 700,
                         "south_asia": False}],
                    "as_of": "2026-11",
                    "page": "https://www.linkedin.com/company/"
                            "leadco",
                    "revelio_not_found": True}
        clean, prob = gate_intake.validate_packet(regional)
        check("f6 no country row: broadest marked rows count, "
              "including a metro row that never says India",
              prob is None and clean["india"] == 200
              and abs(clean["region_pct"] - 20.0) < 0.1,
              str(prob))
        bad = dict(shot_one, india=900)
        clean, prob = gate_intake.validate_packet(bad)
        check("f7 a worker-summed india that disagrees with "
              "the dictionary is refused",
              clean is None and prob is not None
              and "disagrees" in prob, str(prob))
        gate_fallback_mod.open_pending("Leadco", state_path=fb)
        out = gate_intake.record_packet(
            shot_one, log_path=log, fallback_state_path=fb)
        st = state_mod.parse_log(str(log))
        check("f8 location packet records: code decides "
              "HARD_PASS_INDIA_BLOCK and appends the dictionary",
              out["verdict"] == "HARD_PASS_INDIA_BLOCK"
              and out["india"] == 298
              and st.items[104].gate == "fail"
              and "LinkedIn location dictionary: India 298 "
                  "[South Asia]" in log.read_text(encoding="utf-8")
              and gate_fallback_mod.pending_for(
                  "Leadco", state_path=fb) is None, str(out))

        before = log.read_text(encoding="utf-8")
        bad_packets = [
            revelio("Passco", 300, 20, 50.0),                # pct off
            revelio("Passco", 300, 400, 133.3),              # over total
            revelio("Passco", 300, 20, 6.7, source="Owler"),  # source
            revelio("Passco", 300, 20, 6.7, bogus=1),        # field
            {"company": "Passco", "source": "Revelio Labs",
             "total": 300, "india": 20, "india_pct": 6.7,
             "as_of": "2026-06",
             "page": "https://www.reveliolabs.com/companies/x"},
            revelio("Passco", 300, 20, 6.7, page="notaurl"),  # page
            revelio("Passco", 0, 0, 0.0),                    # total
            revelio("Alertco", 300, 20, 6.7, item_id=100),   # mismatch
        ]
        refused = 0
        for pkt in bad_packets:
            try:
                gate_intake.record_packet(pkt, log_path=log)
            except ValueError:
                refused += 1
        check("g1 every invalid packet refused",
              refused == len(bad_packets), f"{refused}/{len(bad_packets)}")
        check("g2 refusals wrote nothing",
              log.read_text(encoding="utf-8") == before)

        try:
            gate_intake.record_packet(
                revelio("Dupe Co", 3000, 100, 3.3), log_path=log)
            amb = False
        except ValueError:
            amb = True
        check("h1 ambiguous company refused without item_id", amb)
        out = gate_intake.record_packet(
            revelio("Dupe Co", 3000, 100, 3.3, item_id=106),
            log_path=log)
        st = state_mod.parse_log(str(log))
        check("h2 item_id pins the check to the named item",
              out["item_id"] == 106 and st.items[106].gate == "pass"
              and st.items[105].gate != "pass", str(out))
        try:
            gate_intake.record_packet(
                revelio("Ghost Co", 3000, 100, 3.3), log_path=log)
            ghost = False
        except ValueError:
            ghost = True
        check("h3 unknown company refused", ghost)

        check("i1 format states the packet + the contract",
              all(s in gate_intake.FORMAT_TEXT for s in
                  ("south_asia", "south_asia_pct", "total", "as_of",
                   "page", "item_id", "India")),
              "")

        # Public-page rule (the user, Nov 27, 2026): the gate reads
        # the PUBLIC Revelio page signed out — no account exists or
        # is needed, and no run may report a Revelio login blocker.
        check("i2 format states the no-account public-page rule",
              all(s in gate_intake.FORMAT_TEXT for s in
                  ("NO ACCOUNT, NO SIGN-IN", "signed out",
                   "account.reveliolabs.com", "app.reveliolabs.com",
                   "no Revelio account and none is needed")),
              "")

    if FAILS:
        print(f"\n{len(FAILS)} FAILURE(S): {FAILS}")
        return 1
    print("\nALL GATE INTAKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
