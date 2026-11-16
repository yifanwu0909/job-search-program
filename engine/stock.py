#!/usr/bin/env python3
"""Stocking, standardized (the user, Nov 5, 2026): the stocking half of the
log is written by THIS program, never by hand.

Why: discovery/stocking segments were the last hand-written part of the
outreach log. Runs stocked items in whatever shorthand came to hand —
"SEGMENT STATE — gate-passed — #367 (Central Insurance; figure …)" —
while the log parser takes an item's company/role ONLY from standard
stocking segments. Four items (#364–#367, Nov 5, 2026) landed with
blank names; the recorder then copied the blanks into their SUBMITTED
lines ("#367 , , (Dayforce …)"), and every name-based reader (the
email scan's watch list first) lost them. Counting never noticed —
it works on item numbers, not names.

The pattern is the application's (spine.py record) and the email
scan's (email_sweep.py record): the program hands Muse a
CODE-FRIENDLY FORMAT to return; Muse does the research and judgment
(finding jobs, reading workforce counts, computing the city
equivalent, building the tailored resume) and returns the filled form;
the program validates it, decides the gate and pay verdicts IN CODE
(same thresholds as spine.py gate/pay, from config/rules.yaml),
assigns the item numbers, dedupes against the log, and writes every
log line itself in the standard formats the parser mines.

Commands:
  stock.py format
      Print the return form: the JSON shape + the field rules. A run
      reads this before stocking; it never invents a log format.
  stock.py record <form.json>
      Record one batch of stocked items from the filled form.
      Per item the program writes, in order: the STOCKED entry
      (identity + source tag — the segment the parser takes the name
      from), the gate entry (GATE PASS with counts, or a SKIPPED entry
      on a hard pass), the SEGMENT STATE gate-passed bench line (gate
      pass + pay OK only), a pay SKIPPED entry when the attainable
      figure is below the city equivalent, and a PREP READY entry when
      a verified tailored resume is named. Returns one JSON object:
      recorded (with assigned ids + verdicts), duplicates (refused,
      with the existing item id), errors, alert_companies (always
      empty since Nov 12, 2026 — the user removed size alerts; the field
      stays in the output shape), blocked_companies (India
      majority — the program itself appends them to the log's
      Blocked companies section, bullet + total line, the user,
      Nov 13, 2026), fallback_orders (a bare not-found hand-in is
      tracked as fallback-owed by gate_fallback and the ORDER for
      the LinkedIn check is returned here — the code step between
      Revelio and LinkedIn, the user, Nov 13, 2026).

The program never browses and never applies.

STOCKING AS DATA (the user, Nov 6, 2026 — fix #1 of the text-parsing
audit): for every item that lands verified, record() ALSO writes the
stocking payload as fixed data — a minimal `stocked` event in
events.jsonl (the events contract: {ts, type, item, src, win} only)
plus one entry in the stocked-items data file (events.stocked.json
beside the live event book; derived beside any other log): company,
role, apply URL, host, ATS, gate counts + verdict, pay figure /
basis / bar, resume file, disposition. Work orders read route and
salary from that data — pipeline.py no longer mines the STOCKED
prose for them (the regex miner was deleted with this change; items
stocked before it were backfilled once into the same data file by
backfill_stocked.py).

THE HANDOFF CONTRACT (the user, Nov 5, 2026 — Muse and the program must
fully understand what the other handed off):
  * Program → Muse: `format` states the exact shape; every refusal
    quotes what was received against what was expected; every result
    echoes the form back as "understood".
  * Muse → program: the filled form, validated field by field.
  * Landing proof: after writing, the program re-parses the log and
    compares the parser's view ("landed_as") against the form. Only
    "verified: true" items count as stocked; anything else is reported
    under "unverified" with the exact discrepancies — never silently.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import yaml

BASE = Path(__file__).resolve().parent.parent
GOAL = BASE.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))
import events as events_mod  # noqa: E402
import gate_fallback as gate_fallback_mod  # noqa: E402
import log_writer  # noqa: E402
import posting_identity as posting_identity_mod  # noqa: E402
import state as state_mod  # noqa: E402

LOG_PATH = GOAL / "hidden_files" / "outreach-log.md"
RULES_PATH = BASE / "config" / "rules.yaml"
ANSWERS_PATH = BASE / "config" / "answers.yaml"
MARKER = "(Recorded by stock program.)"
SOURCES = ("LINKEDIN", "JOBRIGHT", "INDEED", "LINKEDIN_ALERT")

# Host -> ATS name, computed from the apply URL the form carries —
# a data operation on a URL, never a read of prose.
HOST_ATS = (
    ("ashbyhq.com", "Ashby"), ("greenhouse.io", "Greenhouse"),
    ("lever.co", "Lever"), ("myworkdayjobs.com", "Workday"),
    ("gem.com", "Gem"), ("rippling.com", "Rippling"),
    ("workable.com", "Workable"),
    ("smartrecruiters.com", "SmartRecruiters"),
    ("icims.com", "iCIMS"), ("taleo.net", "Taleo"),
    ("successfactors.com", "SuccessFactors"),
    ("successfactors.eu", "SuccessFactors"),
    ("oraclecloud.com", "Oracle HCM"), ("eightfold.ai", "Eightfold"),
    ("phenom.com", "Phenom"), ("jobvite.com", "Jobvite"),
    ("breezy.hr", "Breezy"), ("recruitee.com", "Recruitee"),
    ("ukg.net", "UKG"), ("paycomonline.net", "Paycom"),
    ("dayforcehcm.com", "Dayforce"), ("jazzhr.com", "JazzHR"),
    ("adp.com", "ADP"), ("workday.com", "Workday"),
)


def ats_for_url(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    for suffix, name in HOST_ATS:
        if host == suffix or host.endswith("." + suffix):
            return name
    return ""


def data_paths(log_path: Path) -> tuple[Path, Path]:
    """(events_path, stocked_path) for a log: the live log uses the
    program's event book; any other log (tests, copies) derives both
    beside itself so a test can never write the live files — the
    same rule Spine applies to its event book."""
    lp = Path(log_path)
    if lp == LOG_PATH:
        ev = BASE / "events.jsonl"
    else:
        ev = lp.parent / f"{lp.stem}.events.jsonl"
    return ev, events_mod.stocked_path_for(ev)


def _window_date_now() -> str:
    """The batch window a stocking lands in: windows open 8:23 AM CT."""
    now = datetime.now(state_mod.CT)
    d = now.date()
    if (now.hour, now.minute) < (8, 23):
        d = d - timedelta(days=1)
    return d.isoformat()


def _persist_stocked(events_path: Path, stocked_path: Path,
                     entry: dict) -> None:
    """Write one item's stocking payload as data: the minimal
    `stocked` event plus its entry in the stocked-items file
    (read-modify-write via a temp file + rename)."""
    events_mod.append_event(events_path, "stocked",
                            item=entry["item_id"], src=entry["source"],
                            win=_window_date_now())
    data: dict = {}
    if stocked_path.exists():
        try:
            data = json.loads(stocked_path.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    data[str(entry["item_id"])] = entry
    stocked_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = stocked_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, stocked_path)

FORMAT_TEXT = """\
RETURN FORM — stock.py record takes a JSON file of this shape:

{
  "items": [
    {
      "company": "Central Insurance",            // required, exact name
      "role": "Machine Learning Engineer",       // required, exact title
      "source": "JOBRIGHT",                      // LINKEDIN | JOBRIGHT |
                                                 //   INDEED | LINKEDIN_ALERT
                                                 //   (the user, Nov 12, 2026 —
                                                 //   Indeed a discovery
                                                 //   source on the exact
                                                 //   Jobright rules;
                                                 //   LINKEDIN_ALERT =
                                                 //   LinkedIn job alerts
                                                 //   via the daily alert
                                                 //   emails only)
      "url": "https://…",                        // required, the apply/posting link
      "location": "Chicago, IL — Hybrid",        // optional, as posted
      "req_id": "R12345",                        // optional, if the posting shows one
      "linkedin_job_id": "4312345678",           // optional, LinkedIn postings
      "posted_age_hours": 5,                   // OPTIONAL: the posting's
                                                 //   age when the source shows
                                                 //   it (or "posted_text":
                                                 //   "2 days ago"). JOBRIGHT /
                                                 //   INDEED stocks whose KNOWN
                                                 //   age exceeds discovery
                                                 //   .max_posting_age_hours (24)
                                                 //   are REFUSED (the user, Nov 12,
                                                 //   2026); unknown age allowed;
                                                 //   LINKEDIN_ALERT exempt.
      "gate": {"total": 3000, "india": 100,   // GATE AT IDENTIFICATION
               "source": "Revelio Labs"},        //   (the user, Nov 12, 2026 —
                                                 //   timing REVERSED:
                                                 //   "check the company as
                                                 //   soon as you identified
                                                 //   a new job posting";
                                                 //   rules.yaml gate.timing:
                                                 //   on_identification). The
                                                 //   gate verdict is decided
                                                 //   BEFORE stocking, from an
                                                 //   approved source (Revelio
                                                 //   first). Two forms work:
                                                 //   counts {total, india,
                                                 //   source}, or the GATE
                                                 //   PACKET itself (the
                                                 //   gate_intake fields:
                                                 //   source, total, south_asia
                                                 //   + south_asia_pct for
                                                 //   Revelio / for LinkedIn
                                                 //   the LOCATION DICTIONARY
                                                 //   below, as_of, page) —
                                                 //   the program validates
                                                 //   the packet and maps
                                                 //   South Asia to India in
                                                 //   code.
                                                 //   {"deferred": true} is
                                                 //   REFUSED for new stocks
                                                 //   under this timing.
                                                 //   REVELIO FIRST
                                                 //   (the user, Nov 12, 2026):
                                                 //   the verdict comes
                                                 //   from Revelio Labs.
                                                 //   Company NOT on
                                                 //   Revelio: the LINKEDIN
                                                 //   FALLBACK (the user, Nov 13,
                                                 //   2026) — gate it on
                                                 //   LinkedIn instead and
                                                 //   return the LinkedIn
                                                 //   People packet with
                                                 //   "revelio_not_found":
                                                 //   true. THE PACKET IS A
                                                 //   DICTIONARY OF NUMBERS:
                                                 //   "total" is the
                                                 //   "associated members"
                                                 //   number at the top of
                                                 //   the People page (the
                                                 //   total headcount), and
                                                 //   "locations" carries
                                                 //   EVERY "Where they
                                                 //   live" row as {label,
                                                 //   count, south_asia} —
                                                 //   mark each row South
                                                 //   Asia or not by
                                                 //   judgment ("Greater
                                                 //   Bengaluru Area" is
                                                 //   India even though it
                                                 //   does not say so).
                                                 //   Code derives the
                                                 //   South Asia count and
                                                 //   ratio from the rows
                                                 //   itself — do no math.
                                                 //   Only when
                                                 //   LinkedIn gives no
                                                 //   usable counts either:
                                                 //   gate
                                                 //   {"revelio_not_found":
                                                 //   true,
                                                 //   "linkedin_checked":
                                                 //   true} — recorded
                                                 //   SKIPPED (dropped,
                                                 //   NOT blocked; a later
                                                 //   posting is checked
                                                 //   fresh). The bare
                                                 //   {"revelio_not_found":
                                                 //   true} form is the
                                                 //   NOT-FOUND HAND-IN:
                                                 //   code tracks the
                                                 //   company as
                                                 //   fallback-owed and
                                                 //   returns an ORDER —
                                                 //   the LinkedIn check
                                                 //   runs only on that
                                                 //   order, and the
                                                 //   packet / drop forms
                                                 //   above record only
                                                 //   against an open
                                                 //   order (the user, Nov 13,
                                                 //   2026). Company
                                                 //   listed but its counts
                                                 //   cannot form a packet:
                                                 //   gate {"revelio_
                                                 //   insufficient": true} —
                                                 //   recorded SKIPPED with
                                                 //   that distinct reason.
      "pay": {                                   // required — figure YOU researched
        "figure": 210000,                        // attainable: top of the posted
                                                 //   range, else the market figure
        "basis": "city",                         // city | remote_national |
                                                 //   remote_zone — the PROGRAM
                                                 //   picks the bar: city = the
                                                 //   universal $200,000;
                                                 //   remote_national = $120,000;
                                                 //   remote_zone = your researched
                                                 //   equivalent (next field)
        "equivalent": 231120,                    // remote_zone ONLY: the city
                                                 //   equivalent (2-person, 2BR,
                                                 //   30-min commute, taxes incl.)
        "city": "San Francisco, CA",
        "source": "bestplaces"
      },
      "resume_file": "central-insurance-….pdf",  // optional; only with
      "resume_verified": true                    //   read-back verification done
    }
  ]
}

SCREENING ORDER — IN CODE, NOT YOUR JUDGMENT (the user, Nov 13, 2026:
"Blacklist. Company duplications and Revelio check" — every fresh
posting is screened off the list, without opening it, in this
order): (1) BLACKLIST — a company on the blocked list is dropped
on sight, no exemption; (2) DUPLICATION — a company already in the
all-time applied record is dropped before the gate; the only
exemption is a the user-directed or recruiter-requested one-off, marked
with a top-level "wu_directed": true on the item (the blacklist
has NO exemption); (3) the Revelio gate (LinkedIn fallback when
the company is not on Revelio). record() runs screens 1 and 2
itself on every form. A fresh list candidate can also be handed
in as a SCREEN FORM — gate {"screen_only": true} and NO pay
field — and the program records the screen drop itself, or
refuses and tells you the job passed both screens and must be
vetted in full before stocking.

Rules: one object per job you are stocking, all fields truthful and
researched by you; the program assigns the item numbers, decides the
gate verdict (size <100 hard pass; India >50% hard pass + block;
size 100 and up passes with NO alert — size alerts removed by the user,
Nov 12, 2026) and the pay verdict (the bar
depends on the basis YOU name: city = the universal $200,000 bar;
remote_national = $120,000; remote_zone = your researched equivalent;
a figure below its bar = do not stock for application), dedupes
against the log, and writes every log line itself. Never hand-write STOCKED,
SEGMENT STATE, GATE, or PREP READY lines again.

THE HANDOFF IS VERIFIED BOTH WAYS (the user, Nov 5, 2026): the result echoes
each item back as "understood" (your form as the program received it)
and "landed_as" (what the log parser actually reads after the lines
were written), with "verified": true only when the two agree and the
item's state matches its verdicts. Compare them against your form
before treating an item as stocked: an item under "unverified" was
written but did NOT land as intended — do not use it; report it."""


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower())
            if len(t) > 2}


def _gate_verdict(total: int, india: int, cfg: dict) -> tuple[str, bool]:
    """Identical decision to spine.py cmd_gate, same config."""
    pct = (100.0 * india / total) if total else 0.0
    if total < cfg.get("hard_pass_total_below", 100):
        return "HARD_PASS_SIZE", False
    if pct > cfg.get("india_block_pct", 50):
        return "HARD_PASS_INDIA_BLOCK", True
    if total <= cfg.get("alert_band_max", 500):
        return "PASS_ALERT", False
    return "PASS", False


def _posting_age_hours(raw: dict) -> float | None:
    """The posting's age in hours when the stock form carries it —
    a numeric posted_age_hours wins; otherwise a posted_text /
    posted string the source showed ("3 hours ago", "2 days ago",
    "30+ days ago", "1 week ago") is parsed. "today" / "just now"
    read as within the window; "yesterday" as exactly 24 (not over
    the boundary). None when the source showed no usable age — an
    unknown age is ALLOWED (the user, Nov 12, 2026: the scan boundary is
    the control; the Nov 10 undeterminable-age bar is not back)."""
    v = raw.get("posted_age_hours")
    if isinstance(v, (int, float)) and not isinstance(v, bool) \
            and v >= 0:
        return float(v)
    text = raw.get("posted_text") or raw.get("posted") or ""
    if not isinstance(text, str):
        return None
    t = text.strip().lower()
    if not t:
        return None
    if "yesterday" in t:
        return 24.0
    if "just now" in t or "today" in t or t == "new":
        return 0.0
    m = re.search(r"(\d+)\s*\+?\s*(hour|day|week|month)", t)
    if not m:
        return None
    n = int(m.group(1))
    return float(n * {"hour": 1, "day": 24, "week": 168,
                      "month": 720}[m.group(2)])


def _validate(raw: dict, gate_cfg: dict | None = None,
              age_limit_hours: float | None = None,
              age_sources: tuple = ()) -> str | None:
    """None when the form item is usable, else the refusal reason."""
    for field in ("company", "role", "source", "url"):
        if not (raw.get(field) or "").strip():
            return f"missing required field: {field}"
    if raw["source"] not in SOURCES:
        return f"source must be one of {SOURCES}; got {raw['source']!r}"
    # PAST-24-HOURS SCAN WINDOW (the user, Nov 12, 2026: "For indeed and
    # jobright, also only scan the past 24 hours"): a Jobright /
    # Indeed stock whose KNOWN posting age exceeds the configured
    # window is refused — the pass stops at the boundary, and this
    # is the code backstop. LINKEDIN_ALERT is exempt (the daily
    # email is the window) and an unknown age is allowed.
    if age_limit_hours is not None and raw["source"] in age_sources:
        age = _posting_age_hours(raw)
        if age is not None and age > age_limit_hours:
            return (f"posting age {age:g}h exceeds the "
                    f"{age_limit_hours:g}-hour discovery window for "
                    f"{raw['source']} (the user, Nov 12, 2026 — Jobright "
                    f"and Indeed scan only the past 24 hours)")
    if not re.match(r"https?://", raw["url"].strip()):
        return f"url must be an http(s) link; got {raw['url']!r}"
    gate = raw.get("gate") or {}
    _has_counts = isinstance(gate.get("total"), int) and \
        isinstance(gate.get("india"), int)
    _src = (gate.get("source") or "").strip().lower()
    if gate.get("screen_only") is True:
        pass  # SCREEN FORM (the user, Nov 13, 2026): the run hands the
        # program a fresh list candidate with NO gate counts and NO
        # pay research; record() runs the blacklist and duplication
        # screens itself and either records the drop or refuses,
        # telling the run to vet the job fully. Screening is code,
        # never the run's judgment.
    elif gate.get("revelio_not_found") is True and not _has_counts:
        if gate.get("linkedin_checked") is not True:
            # NOT-FOUND IS NO LONGER A DROP BY ITSELF (the user,
            # Nov 13, 2026): a company missing from Revelio gets
            # the LinkedIn fallback gate first. The bare not-found
            # form is refused so the fallback actually happens;
            # the drop survives only when LinkedIn was checked too
            # and gave no usable counts.
            return ("gate {\"revelio_not_found\": true} alone no "
                    "longer drops a posting (the user, Nov 13, 2026): a "
                    "company not on Revelio gets the LinkedIn "
                    "fallback gate — return a LinkedIn People "
                    "packet (india / india_pct counts, "
                    "\"revelio_not_found\": true). Only when "
                    "LinkedIn gives no usable counts either, use "
                    "{\"revelio_not_found\": true, "
                    "\"linkedin_checked\": true}")
        pass  # BOTH CHECKS EMPTY (the user, Nov 13, 2026): Revelio has
        # no listing and the LinkedIn fallback produced no usable
        # counts — the posting is DROPPED, never stocked.
    elif gate.get("revelio_insufficient") is True:
        pass  # REVELIO DROP FORM (the user, Nov 12, 2026): the company
        # IS listed on Revelio but its counts cannot form a valid
        # packet (revelio_insufficient — no stock, a distinct
        # reason). No counts exist for this form, by definition.
    elif (gate_cfg or {}).get("timing") == "on_identification" and \
            _has_counts and \
            _src not in ("revelio labs", "revelio") and \
            not (_src in ("linkedin people", "linkedin") and
                 gate.get("revelio_not_found") is True):
        # REVELIO FIRST for new stocks (the user, Nov 12, 2026), with
        # the LINKEDIN FALLBACK (the user, Nov 13, 2026): under
        # on_identification the stocking gate's verdict must come
        # from Revelio Labs — or from LinkedIn People counts
        # marked as the fallback for a company Revelio does not
        # list. Any other non-Revelio gate (counts or packet)
        # cannot stock a new item. (gate_intake validates packets
        # for every gate use; this refusal is stocking-only.)
        return ("the stocking gate requires a Revelio Labs verdict "
                "for new items (the user, Nov 12, 2026), or a LinkedIn "
                "People fallback verdict marked "
                "\"revelio_not_found\": true for a company Revelio "
                "does not list (the user, Nov 13, 2026); got gate source "
                f"{gate.get('source')!r}")
    if gate.get("deferred") is True and \
            (gate_cfg or {}).get("timing") != "on_forward_movement":
        # GATE TIMING REVERSED (the user, Nov 12, 2026, 4:05 PM CT: "change
        # it back to check the company as soon as you identified a
        # new job posting that hasn't been applied. Burn this into
        # code."): under on_identification a new stock MUST carry a
        # real gate verdict — the deferred form is refused, never
        # silently stocked. Items stocked under the Nov 11, 2026
        # deferral are historical state and are not affected here.
        return ("gate {\"deferred\": true} is refused — the gate "
                "runs AT IDENTIFICATION now (the user, Nov 12, 2026; "
                "rules.yaml gate.timing: "
                f"{(gate_cfg or {}).get('timing')!r}); a new stock "
                "must carry gate counts or a gate packet with a real "
                "verdict")
    if (gate_cfg or {}).get("timing") == "on_forward_movement" and \
            gate.get("deferred") is True:
        pass  # GATE DEFERRED (the user, Nov 11, 2026): no counts at stocking.
    elif gate.get("screen_only") is True:
        pass  # screen forms carry no counts (see above)
    elif (gate.get("revelio_not_found") is True
            and not _has_counts) or \
            gate.get("revelio_insufficient") is True:
        pass  # drop forms carry no counts (see above); a fallback
        # form (revelio_not_found WITH LinkedIn counts) falls
        # through to the counts check below like any counted gate
    elif not isinstance(gate.get("total"), int) or \
            not isinstance(gate.get("india"), int) or \
            not (gate.get("source") or "").strip():
        return ("gate needs total (int), india (int), source (name); "
                f"got total={gate.get('total')!r} "
                f"india={gate.get('india')!r} "
                f"source={gate.get('source')!r}")
    if isinstance(gate.get("india"), int) and \
            isinstance(gate.get("total"), int) and \
            gate["india"] > gate["total"]:
        return (f"gate india count ({gate['india']}) exceeds total "
                f"({gate['total']})")
    pay = raw.get("pay") or {}
    if gate.get("screen_only") is True and raw.get("pay") is None:
        pass  # SCREEN FORM (the user, Nov 13, 2026): no pay research
        # exists yet — the pay check happens later, when a job
        # that survives the screens is vetted and stocked in full.
    elif not isinstance(pay.get("figure"), int) or \
            pay.get("basis") not in ("city", "remote_national",
                                     "remote_zone") or \
            not (pay.get("city") or "").strip() or \
            not (pay.get("source") or "").strip():
        return ("pay needs figure (int), basis (city|remote_national|"
                "remote_zone), city, source; got "
                f"figure={pay.get('figure')!r} "
                f"basis={pay.get('basis')!r} "
                f"city={pay.get('city')!r} "
                f"source={pay.get('source')!r}")
    if pay.get("basis") == "remote_zone" and \
            not isinstance(pay.get("equivalent"), int):
        return ("pay basis remote_zone needs equivalent (int) — the "
                f"researched city equivalent; got "
                f"{pay.get('equivalent')!r}")
    if raw.get("resume_file"):
        if not str(raw["resume_file"]).endswith(".pdf"):
            return "resume_file must be a .pdf"
        if raw.get("resume_verified") is not True:
            return "resume_file requires resume_verified: true"
    return None


def _pay_bar(pay: dict, cfg: dict) -> int:
    """PAY RULE v2 (the user, Nov 5, 2026) — the bar is picked HERE, from
    config, exactly as spine.py pay picks it: city → the universal
    bar; remote_national → the Houston basis (unchanged); remote_zone
    → the researched equivalent from the form (unchanged)."""
    if pay["basis"] == "city":
        return int(cfg.get("universal_bar", 200000))
    if pay["basis"] == "remote_national":
        return int(cfg.get("remote_national_bar",
                           cfg.get("base_houston_annual", 120000)))
    return int(pay["equivalent"])


def _is_restockable(item, pay: dict, pay_cfg: dict) -> bool:
    """RE-STOCK POOL (the user, Nov 5, 2026): an item whose ONLY outcome was
    a skip under the old city-equivalent pay bar, and whose attainable
    figure meets the CURRENT bar, is NOT a duplicate — it may be
    stocked fresh through the full pipeline. The old-bar skip is read
    from the item's own record: folded state "skipped" (which also
    guarantees no submission outranks the skip), the gate did not
    fail, and a skipped event carries the canonical BELOW
    CITY-EQUIVALENT PAY text. The new form must pass the bar as
    computed TODAY — a posting still below the bar stays a duplicate.
    """
    if item is None or item.state != "skipped" or item.gate == "fail":
        return False
    if not any(e[2] == "skipped" and "BELOW CITY-EQUIVALENT PAY" in e[3]
               for e in item.events):
        return False
    return pay["figure"] >= _pay_bar(pay, pay_cfg)


def _is_revelio_recheckable(item) -> bool:
    """A prior item whose ONLY outcome was the no-Revelio drop
    (skipped, gate never failed, the skip carries the canonical
    not-found text) does not make a later posting a duplicate —
    the company is checked fresh (the user, Nov 12, 2026)."""
    if item is None or item.state != "skipped" or item.gate == "fail":
        return False
    return any(e[2] == "skipped" and "company not found on Revelio"
               in e[3] for e in item.events)


def _find_url_owner(raw: dict, log_state):
    """The item whose stocked entry carries this apply URL, if any
    (the raw-log URL branch of _is_duplicate cannot name it)."""
    url = raw["url"].strip()
    for it in log_state.items.values():
        if any(e[2] == "stocked" and url in e[3] for e in it.events):
            return it
    return None


def _prior_ids_map(log_state) -> dict[int, set]:
    """Per-item posting-identity tokens, mined from the item's own
    log entries (the STOCKED line carries the apply URL and any req
    id; result lines carry req ids too). Event detail strings do not
    hold the URL, so the entries themselves are the source."""
    out: dict[int, set] = {}
    for entry in getattr(log_state, "entries", []) or []:
        text = f"{entry.head} {entry.body}"
        m = re.search(r"#(\d+)\b", text)
        if not m:
            continue
        ids = posting_identity_mod.extract_ids(text)
        if ids:
            out.setdefault(int(m.group(1)), set()).update(ids)
    return out


def _is_duplicate(raw: dict, log_state, raw_log: str,
                  ids_map: dict | None = None) -> tuple[bool, int | None]:
    """Dedupe (the log is the source of truth): same company + role,
    same LinkedIn job id, or the same apply URL already in the log.

    CROSS-PLATFORM (the user, Nov 13, 2026 — the three sources duplicate
    each other by nature): posting_identity adds the signals that
    survive a platform hop — a shared employer/ATS posting id (the
    same Greenhouse gh_jid, Lever UUID, Workday R-number or req id
    behind a Jobright copy and an Indeed copy), and company +
    abbreviation-expanded role-title equality ("Sr. Data Scientist"
    on one platform = "Senior Data Scientist" on another). Both new
    branches require the same normalized company, so an id collision
    across companies can never merge two different jobs."""
    norm = state_mod.normalize_company(raw["company"])
    role_toks = _tokens(raw["role"])
    ljid = (raw.get("linkedin_job_id") or "").strip()
    cand_ids = posting_identity_mod.candidate_ids(raw)
    cand_role_key = posting_identity_mod.role_key(raw["company"],
                                                  raw["role"])
    for it in log_state.items.values():
        if ljid and it.linkedin_job_id == ljid:
            return True, it.id
        if it.company and state_mod.normalize_company(it.company) == norm:
            if cand_ids and ids_map and \
                    cand_ids & ids_map.get(it.id, set()):
                return True, it.id
            if cand_role_key[1] and \
                    posting_identity_mod.role_key(it.company,
                                                  it.role) == cand_role_key:
                return True, it.id
            have = _tokens(it.role)
            if have and role_toks and \
                    len(have & role_toks) >= max(1, min(len(have),
                                                       len(role_toks)) // 2):
                return True, it.id
    if raw["url"].strip() in raw_log:
        return True, None
    return False, None


def _append_blocked_to_log(log_path, details: list) -> list:
    """Append India-majority blocks to the log's Blocked companies
    section — BY CODE (the user, Nov 13, 2026: the code appends the
    result to the existing track of records; a blocked company
    lands in the section through the program, never through run
    prose — the Factspan/UST verdicts nearly lived only in report
    notes). Each new company gets a bullet under a program
    sub-header at the end of the section (just before its
    "Blocked list total" line when one is present), and that
    total line is bumped by the number actually added. Companies
    already in the section are skipped. Returns the names
    actually added ([] when the log has no Blocked section)."""
    p = Path(log_path)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("#") and "Blocked companies" in ln:
            start = i
            break
    if start is None:
        return []
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("#"):
            end = j
            break
    existing = state_mod.parse_log(str(p)).blocked_companies
    fresh, seen = [], set(existing)
    for d in details:
        norm = state_mod.normalize_company(d["company"])
        if norm in seen:
            continue
        seen.add(norm)
        fresh.append(d)
    if not fresh:
        return []
    now = datetime.now(state_mod.CT)
    date_str = f"{now:%b} {now.day}, {now.year}"
    block = [f"Blocked by the India-majority gate — recorded by "
             f"the stock program ({date_str}):"]
    for d in fresh:
        block.append(
            f"- {d['company']} — blocked {date_str} by the "
            f"India-majority gate ({d['source']}: {d['total']:,} "
            f"total / {d['india']:,} India ({d['pct']:.1f}%)) — "
            f"item #{d['id']}. {MARKER}")
    total_idx = None
    for j in range(start + 1, end):
        if re.search(r"Blocked list total: \d+ companies",
                     lines[j]):
            total_idx = j
    insert_at = total_idx if total_idx is not None else end
    while insert_at > start + 1 and lines[insert_at - 1] == "":
        insert_at -= 1
    if lines[insert_at - 1].strip():
        block = [""] + block
    lines[insert_at:insert_at] = block + [""]
    text = "\n".join(lines)
    # The total the parser reads is the LAST match in the file
    # (state._blocked_total) — bump exactly that one.
    matches = list(re.finditer(
        r"Blocked list total: (\d+) companies", text))
    if matches:
        m = matches[-1]
        text = (text[:m.start()]
                + f"Blocked list total: "
                  f"{int(m.group(1)) + len(fresh)} companies"
                + text[m.end():])
    p.write_text(text, encoding="utf-8")
    return [d["company"] for d in fresh]


def record(form: dict, log_path: Path = LOG_PATH,
           events_path: Path | None = None,
           stocked_path: Path | None = None,
           fallback_state_path: Path | None = None) -> dict:
    items = form.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("form needs a non-empty 'items' list")
    _dev, _dst = data_paths(Path(log_path))
    events_path = Path(events_path) if events_path else _dev
    stocked_path = Path(stocked_path) if stocked_path else _dst
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    try:
        _answers = yaml.safe_load(
            ANSWERS_PATH.read_text(encoding="utf-8")) or {}
        _never = (_answers.get("applications") or {}).get(
            "never_name") or []
    except Exception:
        _never = []
    never_txt = "/".join(str(n) for n in _never) if _never \
        else "never-name employers"
    gate_cfg = rules.get("gate") or {}
    pay_cfg = rules.get("pay_filter") or {}
    disc_cfg = rules.get("discovery") or {}
    age_limit = disc_cfg.get("max_posting_age_hours")
    age_sources = tuple(disc_cfg.get("max_posting_age_sources") or ())
    log_state = state_mod.parse_log(str(log_path))
    raw_log = log_path.read_text(encoding="utf-8") \
        if log_path.exists() else ""
    next_id = (max(log_state.items) + 1) if log_state.items else 1
    # NUMBERING (Nov 15, 2026 fix): prose mentions mint shells for
    # numbers ahead of the stocking frontier, and the Nov 14–15
    # ITEM_RE collision era left #1009–#1015 carrying other
    # companies' drop records. A new stock must take the first
    # number that carries NO identity and NO events, or it lands
    # inside an existing item and read-back verifies as that
    # company instead of its own.
    while next_id in log_state.items and (
            log_state.items[next_id].company
            or log_state.items[next_id].events):
        next_id += 1
    # SCREEN INPUTS (the user, Nov 13, 2026): the blacklist set (parsed
    # from the log's Blocked companies section by state.py) and
    # the all-time applied-company record — both are the program's
    # own records, read once for the whole batch.
    blocked_set = log_state.blocked_companies
    prior_ids_map = _prior_ids_map(log_state)
    try:
        applied_companies = (log_state.window_status().get(
            "all_time_verified_by_company") or {})
    except Exception:
        applied_companies = {}

    recorded, duplicates, errors, unverified = [], [], [], []
    alert_companies, blocked_companies = [], []
    fallback_orders: list = []
    blocked_details: list = []

    for raw in items:
        label = f"{raw.get('company', '?')} — {raw.get('role', '?')}"
        # GATE PACKET FORM (the user, Nov 12, 2026): an item's gate may BE
        # the gate packet (Revelio fields south_asia/south_asia_pct,
        # or india/india_pct for other approved sources, plus as_of
        # and page). Normalize it to counts through the packet's own
        # validator (gate_intake.validate_packet — one validation +
        # South Asia mapping implementation, imported lazily to keep
        # the module graph acyclic) BEFORE the counts validation.
        _gate = raw.get("gate") or {}
        if isinstance(_gate, dict) and any(
                k in _gate for k in ("south_asia", "south_asia_pct",
                                     "india_pct", "as_of", "page",
                                     "locations", "location_counts",
                                     "south_asia_locations")):
            import gate_intake as _gi
            _clean, _prob = _gi.validate_packet(
                {**_gate, "company": raw.get("company") or ""})
            if _prob:
                errors.append({"item": label,
                               "error": f"gate packet refused: {_prob}"})
                continue
            raw["gate"] = {"total": _clean["total"],
                           "india": _clean["india"],
                           "source": _clean["source"]}
            if _clean.get("locations"):
                # LINKEDIN LOCATION DICTIONARY (the user, Nov 13,
                # 2026): the exact "Where they live" rows ride
                # the normalized gate so the record below can
                # append the packet itself to the log, next to
                # the verdict code derived from it.
                raw["gate"]["locations"] = _clean["locations"]
                raw["gate"]["south_asia_counted_labels"] = \
                    _clean.get("south_asia_counted_labels") or []
                raw["gate"]["south_asia_count_basis"] = \
                    _clean.get("south_asia_count_basis") or ""
            if _clean.get("revelio_not_found"):
                # LINKEDIN FALLBACK packet (the user, Nov 13, 2026): the
                # marker rides the normalized counts so _validate
                # can tell a fallback verdict from an unmarked
                # non-Revelio one.
                raw["gate"]["revelio_not_found"] = True
        # THE CODE STEP (the user, Nov 13, 2026 — "Between Revelio and
        # LinkedIn company check, there should be a step of code
        # to track and give orders"): a bare not-found hand-in
        # (gate {"revelio_not_found": true}, no counts, no
        # linkedin_checked) is NOT a stocking and NOT an error —
        # code tracks the company as fallback-owed (gate_fallback)
        # and hands back the ORDER for the LinkedIn check. The
        # worker runs LinkedIn only on that order and returns
        # either the fallback packet or the linkedin_checked
        # drop, which the pending check below then admits.
        _gate_now = raw.get("gate") or {}
        if isinstance(_gate_now, dict) and \
                _gate_now.get("revelio_not_found") is True and \
                _gate_now.get("linkedin_checked") is not True and \
                _gate_now.get("screen_only") is not True and \
                not (isinstance(_gate_now.get("total"), int)
                     and isinstance(_gate_now.get("india"), int)):
            _nf_company = (raw.get("company") or "").strip()
            if not _nf_company:
                errors.append({"item": label, "error":
                               "a not-found hand-in needs a "
                               "company name"})
                continue
            _opened = gate_fallback_mod.open_pending(
                _nf_company,
                run_label=(raw.get("run") or raw.get("source")
                           or ""),
                state_path=fallback_state_path)
            fallback_orders.append(
                {"company": _nf_company,
                 "role": raw.get("role"),
                 "already_pending": _opened["already_pending"],
                 "order": _opened["order"]})
            continue
        problem = _validate(raw, gate_cfg, age_limit, age_sources)
        if problem:
            errors.append({"item": label, "error": problem})
            continue
        # SCREENING ORDER, IN CODE (the user, Nov 13, 2026: "Blacklist.
        # Company duplications and Revelio check" — and "all these
        # rules should be burned into code... it shall not be
        # handled using agent"): every fresh posting is screened
        # OFF THE LIST, without opening it — (1) BLACKLIST first:
        # a blocked company is declined on sight, absolute, no
        # exemption; (2) DUPLICATION second: a company already in
        # the all-time applied record is dropped before any gate
        # math (the ONLY exemption: a the user-directed or
        # recruiter-requested one-off, marked "wu_directed": true
        # on the form); (3) the Revelio gate in the verdict chain
        # below. Both screens read the program's own records — no
        # website is opened for either screen.
        _norm_company = state_mod.normalize_company(raw["company"])
        screen = None
        if _norm_company in blocked_set:
            screen = "blocked"
        elif not raw.get("wu_directed") and \
                _norm_company in applied_companies:
            screen = "duplicate"
        if (raw.get("gate") or {}).get("screen_only") is True \
                and screen is None:
            errors.append({"item": label, "error":
                           "passed the blacklist and duplication "
                           "screens — a screen form is not stocked; "
                           "vet the job fully (Revelio gate or the "
                           "LinkedIn fallback packet, description "
                           "vetting, pay research) and stock the "
                           "full form (the user, Nov 13, 2026)"})
            continue
        dup, existing_id = (False, None) if screen else \
            _is_duplicate(raw, log_state, raw_log,
                          ids_map=prior_ids_map)
        restock_of = None
        restock_kind = None
        if dup:
            old = (log_state.items.get(existing_id)
                   if existing_id is not None
                   else _find_url_owner(raw, log_state))
            if _is_restockable(old, raw["pay"], pay_cfg):
                restock_of = old.id
                restock_kind = "pay_bar"
            elif _is_revelio_recheckable(old):
                # A company dropped ONLY because Revelio had no
                # listing is checked FRESH on a later posting (the user,
                # Nov 12, 2026) — Revelio may list it by then. The
                # new form goes through the full pipeline again.
                restock_of = old.id
                restock_kind = "revelio_recheck"
            else:
                duplicates.append({"company": raw["company"],
                                   "role": raw["role"],
                                   "source": raw.get("source"),
                                   "existing_id": existing_id})
                continue

        # FALLBACK SEQUENCE, ENFORCED (the user, Nov 13, 2026): a
        # LinkedIn fallback packet — or the linkedin_checked
        # drop — records ONLY against an open code order for the
        # company. Without one the LinkedIn check was
        # self-directed: refuse, and point at the code step.
        _gate_v = raw["gate"]
        _fb_packet = _gate_v.get("revelio_not_found") is True and \
            isinstance(_gate_v.get("total"), int) and \
            isinstance(_gate_v.get("india"), int)
        _fb_drop = _gate_v.get("revelio_not_found") is True and \
            not _fb_packet and \
            _gate_v.get("linkedin_checked") is True
        if screen is None and (_fb_packet or _fb_drop) and \
                gate_fallback_mod.pending_for(
                    raw["company"],
                    state_path=fallback_state_path) is None:
            errors.append({"item": label, "error":
                           "LinkedIn fallback refused — code "
                           "holds no fallback order for "
                           f"{raw['company']!r}: hand the Revelio "
                           "not-found result to code first (a "
                           "stock form with gate "
                           "{\"revelio_not_found\": true}, or "
                           "spine.py gate-packet not-found) and "
                           "run the LinkedIn check only on the "
                           "order code hands back (the user, "
                           "Nov 13, 2026)"})
            continue

        iid = next_id
        next_id += 1
        item = {"id": iid, "company": raw["company"].strip(),
                "role": raw["role"].strip()}
        who = log_writer._who(item)
        gate = raw["gate"]
        deferred = (gate_cfg.get("timing") == "on_forward_movement"
                    and gate.get("deferred") is True)
        _has_counts = isinstance(gate.get("total"), int) and \
            isinstance(gate.get("india"), int)
        if screen == "blocked":
            total, india, pct = None, None, 0.0
            verdict, block = "DROPPED_BLOCKED_COMPANY", False
        elif screen == "duplicate":
            total, india, pct = None, None, 0.0
            verdict, block = "DROPPED_DUPLICATE_COMPANY", False
        elif gate.get("revelio_not_found") is True and \
                not _has_counts:
            total, india, pct = None, None, 0.0
            verdict, block = "DROPPED_NO_REVELIO", False
        elif gate.get("revelio_insufficient") is True:
            total, india, pct = None, None, 0.0
            verdict, block = "DROPPED_REVELIO_INSUFFICIENT", False
        elif deferred:
            total, india, pct = None, None, 0.0
            verdict, block = "DEFERRED", False
        else:
            total, india = gate["total"], gate["india"]
            pct = (100.0 * india / total) if total else 0.0
            verdict, block = _gate_verdict(total, india, gate_cfg)
        pay = raw.get("pay") or {}
        pay_bar = _pay_bar(pay, pay_cfg) if pay else None
        pay_ok = bool(pay) and pay["figure"] >= pay_bar

        # (a) STOCKED — identity + source, the segment the parser
        # takes the item's name from. Always written.
        extra = ""
        if restock_of is not None and restock_kind == "revelio_recheck":
            extra += (f" — RE-STOCK of #{restock_of} (previously "
                      f"dropped only because the company was not "
                      f"found on Revelio; checked fresh per the user, "
                      f"Nov 12, 2026 — not a duplicate)")
        elif restock_of is not None:
            extra += (f" — RE-STOCK of #{restock_of} (skipped under "
                      f"the pre-Nov-5 city-equivalent pay bar; the "
                      f"figure meets the current bar — not a "
                      f"duplicate per the Nov 5, 2026 re-stock rule)")
        if (raw.get("location") or "").strip():
            extra += f" — {raw['location'].strip()}"
        extra += f" — apply: {raw['url'].strip()}"
        if (raw.get("req_id") or "").strip():
            extra += f" — req {raw['req_id'].strip()}"
        if (raw.get("linkedin_job_id") or "").strip():
            extra += f" — LinkedIn job {raw['linkedin_job_id'].strip()}"
        log_writer.append_entry(
            str(log_path),
            f"STOCKED — #{iid} {item['company']}, {item['role']}{extra}. "
            f"SOURCE TAG: {raw['source']}. {MARKER}")

        state_out = "bench"
        # (b) gate outcome
        if deferred:
            log_writer.append_entry(
                str(log_path),
                f"GATE DEFERRED — #{iid} {item['company']} — company "
                f"check deferred until forward movement (the user, "
                f"Nov 11, 2026). {MARKER}")
        elif verdict == "DROPPED_BLOCKED_COMPANY":
            # SCREEN 1 (the user, Nov 13, 2026): the blacklist. Absolute
            # — declined on sight, no gate run, no opening, no
            # exemption (not even a the user-directed one-off).
            log_writer.append_entry(
                str(log_path),
                f"SKIPPED — BLOCKED company (blacklist — screen 1 "
                f"of the screening order; the user, Nov 13, 2026) — "
                f"declined on sight — {who}. {MARKER}")
            state_out = "skipped_blocked"
        elif verdict == "DROPPED_DUPLICATE_COMPANY":
            # SCREEN 2 (the user, Nov 13, 2026): duplication against the
            # all-time applied record — dropped before the gate,
            # before any opening.
            log_writer.append_entry(
                str(log_path),
                f"SKIPPED — DUPLICATE company — already applied "
                f"(duplication screen, before the gate; the user, "
                f"Nov 13, 2026) — dropped — {who}. {MARKER}")
            state_out = "skipped_duplicate"
        elif verdict == "DROPPED_NO_REVELIO":
            # NOT a merits verdict: the company is NOT blocked,
            # and a later posting from it is checked fresh (the
            # recheck path in the duplicate handling). Since
            # Nov 13, 2026 this drop means BOTH checks came back
            # empty — no Revelio listing AND no usable LinkedIn
            # fallback counts.
            log_writer.append_entry(
                str(log_path),
                f"SKIPPED — company not found on Revelio and the "
                f"LinkedIn fallback check gave no usable counts — "
                f"dropped (the user, Nov 13, 2026); not a merits verdict "
                f"— the company is NOT blocked and a later posting "
                f"is checked fresh — {who}. {MARKER}")
            state_out = "skipped_gate"
        elif verdict == "DROPPED_REVELIO_INSUFFICIENT":
            log_writer.append_entry(
                str(log_path),
                f"SKIPPED — Revelio data insufficient (the company "
                f"is listed on Revelio but its page's counts cannot "
                f"form a valid gate packet — no gate verdict; the user, "
                f"Nov 12, 2026) — {who}. {MARKER}")
            state_out = "skipped_gate"
        elif verdict.startswith("HARD_PASS"):
            reason = (f"GATE {verdict} ({total:,} total / {india:,} India "
                      f"({pct:.1f}%) per {gate['source']}"
                      + ("; company blocked" if block else "") + ")")
            log_writer.append_entry(
                str(log_path),
                f"SKIPPED — {reason} — {who}. {MARKER}")
            state_out = "skipped_gate"
            if block:
                blocked_companies.append(item["company"])
                blocked_details.append(
                    {"company": item["company"],
                     "source": gate.get("source"),
                     "total": total, "india": india, "pct": pct,
                     "id": iid})
        else:
            alert_txt = (" — ALERT BAND (alert the user)"
                         if verdict == "PASS_ALERT" else "")
            log_writer.append_entry(
                str(log_path),
                f"GATE PASS — #{iid} {item['company']} — "
                f"{gate['source']}: #{iid} {item['company']} "
                f"{total:,} / {india:,} ({pct:.1f}%){alert_txt} → "
                f"verdict {verdict}. {MARKER}")
            if verdict == "PASS_ALERT":
                alert_companies.append(
                    {"company": item["company"], "total": total,
                     "source": gate["source"]})

        # The fallback is now ON RECORD (its verdict or drop
        # entry is written above): clear the company's pending
        # order — code owns the sequence end to end (the user,
        # Nov 13, 2026).
        if screen is None and (_fb_packet or _fb_drop):
            gate_fallback_mod.clear_pending(
                item["company"], state_path=fallback_state_path)

        # THE LOCATION PACKET ITSELF, ON RECORD (the user, Nov 13,
        # 2026): when the fallback gate ran on the LinkedIn
        # location dictionary, append the exact rows the worker
        # returned — every "Where they live" label and number,
        # with the South Asia marks — plus which rows code
        # counted, so the existing track of records holds the
        # packet behind the verdict, not just the verdict.
        if gate.get("locations"):
            _loc_rows = ", ".join(
                f"{e['label']} {e['count']:,}"
                + (" [South Asia]" if e.get("south_asia") else "")
                for e in gate["locations"])
            _loc_counted = ", ".join(
                gate.get("south_asia_counted_labels") or []) \
                or "none"
            _loc_basis = gate.get("south_asia_count_basis") \
                or "the marked rows"
            log_writer.append_entry(
                str(log_path),
                f"GATE LOCATION PACKET — #{iid} "
                f"{item['company']} — LinkedIn People location "
                f"dictionary: {_loc_rows}. Code counted the "
                f"South Asia headcount from {_loc_basis}: "
                f"{_loc_counted} = {india:,} of {total:,} "
                f"({pct:.1f}%). {MARKER}")

        # (c)+(d) bench line only when gate AND pay both pass; a pay
        # failure is a SKIPPED entry naming the bar that applied.
        if state_out == "bench" and not pay_ok:
            if pay["basis"] == "city":
                bar_txt = (f"universal bar = ${pay_bar:,} (the user, Nov 5, "
                           f"2026); posting top/market "
                           f"${pay['figure']:,} in {pay['city']} per "
                           f"{pay['source']}")
            elif pay["basis"] == "remote_national":
                bar_txt = (f"remote national bar = ${pay_bar:,}; "
                           f"posting top/market ${pay['figure']:,} per "
                           f"{pay['source']}")
            else:
                bar_txt = (f"120k Houston = ${pay['equivalent']:,} in "
                           f"{pay['city']} per {pay['source']}; posting "
                           f"top/market ${pay['figure']:,}")
            log_writer.append_entry(
                str(log_path),
                f"SKIPPED — BELOW CITY-EQUIVALENT PAY ({bar_txt}) — "
                f"{who}. {MARKER}")
            state_out = "skipped_pay"
        if state_out == "bench":
            log_writer.append_entry(
                str(log_path),
                f"SEGMENT STATE — gate-passed — #{iid} "
                f"({item['company']}; figure {pay['figure']})")

        # (e) PREP READY — only for benched items with a verified
        # tailored resume.
        if state_out == "bench" and raw.get("resume_file"):
            log_writer.append_entry(
                str(log_path),
                f"PREP READY — #{iid} {item['company']}, "
                f"{item['role']} — tailored resume "
                f"{raw['resume_file']} (#{iid}) built from the base "
                f"resume only and read-back verified (header contact "
                f"line + U.S. Green Card Holder printed; zero "
                f"{never_txt}). {MARKER}")

        # keep the in-memory parse current for dedupe within the batch
        log_state = state_mod.parse_log(str(log_path))
        raw_log = log_path.read_text(encoding="utf-8")
        prior_ids_map = _prior_ids_map(log_state)

        # VERIFY THE HANDOFF (the user, Nov 5, 2026): the program reads back
        # what it just wrote, through the same parser every reader
        # uses, and compares it against the form it was handed. An
        # item counts as recorded only when the two agree.
        understood = {"company": item["company"], "role": item["role"],
                      "source": raw["source"],
                      "gate_counts": [total, india],
                      "pay_figures": [pay.get("figure"), pay_bar],
                      "pay_basis": pay.get("basis")}
        landed = log_state.items.get(iid)
        landed_as = None
        problems = []
        if landed is None:
            problems.append("item not found in the re-parsed log")
        else:
            kinds = [e[2] for e in landed.events]
            landed_as = {"company": landed.company, "role": landed.role,
                         "source": landed.source, "gate": landed.gate,
                         "events": sorted(set(kinds))}
            if landed.company != item["company"]:
                problems.append(
                    f"company landed as {landed.company!r}")
            if landed.role != item["role"]:
                problems.append(f"role landed as {landed.role!r}")
            if landed.source != raw["source"]:
                problems.append(f"source landed as {landed.source!r}")
            if state_out == "bench":
                if "stocked" not in kinds:
                    problems.append("no stocked event landed")
                if landed.gate not in ("pass", "alert", "deferred"):
                    problems.append(f"gate landed as {landed.gate!r}")
            else:
                if "skipped" not in kinds:
                    problems.append("no skipped event landed")
            if raw.get("resume_file") and state_out == "bench" and \
                    landed.resume_file != raw["resume_file"]:
                problems.append(
                    f"resume landed as {landed.resume_file!r}")
        entry_out = {"id": iid, "company": item["company"],
                     "role": item["role"], "source": raw["source"],
                     "gate": verdict, "pay_ok": pay_ok,
                     "state": state_out, "restock_of": restock_of,
                     "understood": understood,
                     "landed_as": landed_as,
                     "verified": not problems}
        if problems:
            entry_out["problems"] = problems
            unverified.append(entry_out)
        else:
            recorded.append(entry_out)
            # STOCKING AS DATA (the user, Nov 6, 2026): the verified item's
            # payload goes to the data file + the event book, so no
            # reader ever mines the prose above for route or salary.
            url = raw["url"].strip()
            _persist_stocked(events_path, stocked_path, {
                "item_id": iid, "company": item["company"],
                "role": item["role"], "source": raw["source"],
                "url": url,
                "host": urlparse(url).netloc.lower(),
                "ats": ats_for_url(url),
                "location": (raw.get("location") or "").strip() or None,
                "req_id": (raw.get("req_id") or "").strip() or None,
                "linkedin_job_id":
                    (raw.get("linkedin_job_id") or "").strip() or None,
                "gate": {"total": total, "india": india,
                         "source": gate.get("source"),
                         "verdict": verdict,
                         "locations": gate.get("locations") or [],
                         "south_asia_counted_labels":
                             gate.get("south_asia_counted_labels")
                             or []},
                "pay": {"figure": pay.get("figure"),
                        "basis": pay.get("basis"),
                        "bar": pay_bar, "city": pay.get("city"),
                        "source": pay.get("source")},
                "resume_file": raw.get("resume_file"),
                "disposition": state_out, "restock_of": restock_of,
                "stocked_at": events_mod.now_iso(),
            })

    # BLOCKED SECTION, WRITTEN BY CODE (the user, Nov 13, 2026): an
    # India-majority block lands in the log's Blocked companies
    # section through this program — bullet + bumped total line —
    # never through run prose.
    if blocked_details:
        _append_blocked_to_log(log_path, blocked_details)

    return {"recorded": recorded, "unverified": unverified,
            "duplicates": duplicates,
            "errors": errors, "alert_companies": alert_companies,
            "blocked_companies": blocked_companies,
            "fallback_orders": fallback_orders}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["format", "record"])
    ap.add_argument("form_file", nargs="?",
                    help="filled form JSON file (for record)")
    args = ap.parse_args()
    if args.command == "format":
        print(FORMAT_TEXT)
        return 0
    if not args.form_file:
        print("record needs a form JSON file", file=sys.stderr)
        return 1
    try:
        form = json.loads(Path(args.form_file).read_text(encoding="utf-8"))
        print(json.dumps(record(form), indent=1))
        return 0
    except (ValueError, OSError) as exc:
        print(f"stock: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
