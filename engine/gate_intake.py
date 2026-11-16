#!/usr/bin/env python3
"""Gate intake, standardized (the user, Nov 12, 2026): a company-gate
check hands its counts to THIS program as a dictionary — the same
clean-packet pattern as stock.py (format → record) — never as prose
and never as the run's own verdict math.

Why: GATE TIMING (the user, Nov 12, 2026, 4:05 PM CT — the deferral is
REVERSED): the gate runs AT IDENTIFICATION, as soon as a new job
posting is identified, before stocking/applying. At stocking time
the packet rides INSIDE the stock item's gate field — stock.py
validates it through this module's validate_packet and decides
with the same _gate_verdict. This record command serves the items
that already exist in the log: verdict-less BACKLOG items (stocked
or submitted under the Nov 11, 2026 deferral) when they move
forward, and forward-movement checks generally. The run reads the
company's page on the primary gate source (Revelio
Labs, the user, Nov 12, 2026) and returns the numbers it read; the program
validates the packet, maps the counts to the gate's inputs IN CODE
(for Revelio, the SOUTH ASIA count is the India figure — the user,
Nov 12, 2026: "that's your Indian employee count"), applies the
EXISTING gate decision (stock.py's _gate_verdict — the same
threshold function spine.py gate uses, from config/rules.yaml), and
writes the verdict line to the outreach log itself, in the same
format stock.py writes at stocking time. The verdict comes back to
the run as structured JSON: the run reports the code's output, not
its own arithmetic.

Commands:
  gate_intake.py format
      Print the packet form: the JSON shape + the field rules.
  gate_intake.py record <packet.json> [--log PATH]
      Validate one packet, decide, and record the verdict against
      the item it belongs to. Refusals write NOTHING and exit 2.

Also wired into spine.py as `spine.py gate-packet format|record`.

Recording shape (parsed by state.py): PASS / PASS_ALERT verdicts are
written exactly as stock.py writes them ("GATE PASS — #id Company —
Source: #id Company total / india (pct%) → verdict ..."), so the
parser's existing gate mining lands them. A hard pass on an
already-submitted item is NOT a SKIPPED entry (the application
stands — nothing about the item's recorded state changes); it is a
"GATE HARD PASS — ..." entry, which state.py mines as gate=fail
only. A recorded verdict supersedes the item's "deferred" gate
placeholder in the parser (state.py, Nov 12, 2026) — that is the
backlog path: a pre-reversal item with no verdict gets its gate
here when it moves forward, before anything proceeds.

The program never browses and never applies.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
GOAL = BASE.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))
import gate_fallback as gate_fallback_mod  # noqa: E402
import log_writer  # noqa: E402
import state as state_mod  # noqa: E402
import stock as stock_mod  # noqa: E402

LOG_PATH = GOAL / "hidden_files" / "outreach-log.md"
RULES_PATH = BASE / "config" / "rules.yaml"
MARKER = "(Recorded by gate program.)"

# Gate sources. HISTORICAL (the user, Nov 3, 2026): the gate once ran on
# any approved workforce source (the tuple below — kept so old
# packets/names still canonicalize for reading). Nov 12, 2026 made
# vetting REVELIO-ONLY, no exception. Nov 13, 2026 (the user) carved ONE
# exception back: a company NOT on Revelio (only a handful) is
# gated on LINKEDIN instead — headcount first, then the India
# employee ratio — via a "LinkedIn People" packet that must carry
# "revelio_not_found": true. validate_packet refuses every other
# non-Revelio packet, and a LinkedIn packet without the marker.
# Verdicts already on record from other sources stand (recording
# is not vetting).
APPROVED_SOURCES = (
    "LinkedIn People", "LeadIQ", "Revelio Labs", "Unify", "Lightcast",
    "LinkedIn Talent Insights", "Apollo", "ZoomInfo", "RocketReach",
    "SignalHire", "Lusha",
)
_SOURCE_ALIASES = {"linkedin people list": "LinkedIn People"}

# The page rounds its percents; the packet's stated percent must sit
# within this many percentage points of the counts' own percent.
PCT_TOLERANCE = 1.5

_PACKET_FIELDS = {"company", "source", "total", "south_asia",
                  "south_asia_pct", "india", "india_pct", "as_of",
                  "page", "item_id", "revelio_not_found",
                  "locations", "location_counts",
                  "south_asia_locations"}

# Country rows in LinkedIn's "Where they live" distribution are
# the broadest South Asia rows: an "India" row already includes
# every state, city and metro row beneath it, so code counts a
# country row once and never adds its nested rows on top of it
# (the user's screenshots, Nov 13, 2026: 339 total / India 298 with
# Karnataka 204, Greater Bengaluru Area 204 and Bengaluru 194
# listed below — those three are inside the 298).
_SOUTH_ASIA_COUNTRIES = {
    "india", "pakistan", "bangladesh", "sri lanka", "nepal",
    "bhutan", "maldives", "afghanistan",
}

FORMAT_TEXT = """\
RETURN PACKET — gate_intake.py record (spine.py gate-packet record)
takes a JSON file of this shape. ONE packet per company checked.

Revelio Labs packet (the primary gate source — read the company's
public page at reveliolabs.com/companies and copy the numbers off
it; do no math of your own beyond reading them):

{
  "company": "Tata Consultancy Services",   // required, exact name
  "source": "Revelio Labs",                 // required — the PRIMARY
                                            //   vetting source (the user,
                                            //   Nov 12, 2026); the one
                                            //   fallback is below
  "total": 2053083,                         // required, int — overall
                                            //   headcount from the page
  "south_asia": 1810203,                    // required for Revelio, int —
                                            //   the page's South Asia
                                            //   employee count. THE
                                            //   PROGRAM maps it to the
                                            //   gate's India figure
                                            //   (the user, Nov 12, 2026)
  "south_asia_pct": 88.6,                   // required for Revelio —
                                            //   the percent the page
                                            //   prints beside the count
  "as_of": "2026-06",                       // required — the data date
                                            //   the page shows
  "page": "https://www.reveliolabs.com/companies/tata-consultancy-services-ltd/employees",
                                            // required — the page URL
  "item_id": 621                            // optional — the application
                                            //   item # this check belongs
                                            //   to; omit only when the
                                            //   company has exactly one
                                            //   plausible item in the log
}

ONE fallback packet shape exists (the user, Nov 13, 2026): a company
that is NOT on Revelio — only a handful — is gated on LinkedIn
instead. Same shape, with "source": "LinkedIn People",
"revelio_not_found": true (required — it attests the company was
looked up on Revelio and has no listing there), and the LinkedIn
company page URL in "page". THE LINKEDIN PACKET IS A DICTIONARY
OF NUMBERS (the user, Nov 13, 2026): "total" is the FIRST number on
the People page — the "associated members" count at the top,
which LinkedIn always shows there; that is the total headcount.
Below it, the "Where they live" location distribution goes in
"locations": EVERY row as {"label": <exact row label>,
"count": <exact row number>, "south_asia": true/false}. Mark a
row south_asia with your best judgment — a row counts when it
is in India or elsewhere in South Asia even when the label
does not say India ("Greater Bengaluru Area", "Greater Delhi
Area" are India). Code derives the South Asia count from the
marked rows itself: a country row ("India") already includes
its state/city/metro rows and is counted once, never added to
them; with no country row, the broadest marked rows are
counted and narrower rows inside them are not double-counted.
Code then divides by "total", applies the >50% rule, and
appends the packet and its verdict to the log. (The legacy
"india" / "india_pct" fields are still accepted when they
agree with the dictionary; a locations dictionary wins.) A
LinkedIn packet WITHOUT "revelio_not_found":
true is refused, and every other non-Revelio source is refused
whole. (Historical verdicts recorded from other sources before
these rules stand untouched.) THE CODE STEP (the user, Nov 13, 2026):
a LinkedIn packet also records ONLY against an open code order
for the company — hand the not-found Revelio result to code
first (spine.py gate-packet not-found, or a stock form with
gate {"revelio_not_found": true}); code tracks the company as
fallback-owed and hands back the order, and the LinkedIn check
runs only on that order, never self-directed. A packet with no
open order is refused whole; a recorded verdict clears it.

Rules: the program validates the packet field by field (source is
Revelio Labs, or LinkedIn People under the fallback above;
positive total; every location count an int between 0 and the
total; the derived South Asia count between 0 and the total;
any stated percent within 1.5 points of the counts'
own percent — the page rounds), refuses an invalid packet WHOLE
(nothing is written), decides the verdict with the standing gate
thresholds (India strictly over 50% → hard pass + block; total
under 100 → hard pass, no block; total 100 and up → pass with NO
alert — size alerts removed by the user, Nov 12, 2026), writes the verdict line to the log itself, and prints the
verdict as JSON. Report the program's numbers, never your own."""


def _norm_source(source: str) -> str | None:
    """The canonical approved-source name for a packet's source
    string, or None when the source is not an approved gate source."""
    key = re.sub(r"\s+", " ", (source or "").strip().lower())
    if key in _SOURCE_ALIASES:
        return _SOURCE_ALIASES[key]
    for name in APPROVED_SOURCES:
        if key == name.lower():
            return name
    return None


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _label_key(label: str) -> str:
    return re.sub(r"\s+", " ", (label or "").strip().lower())


def _label_segments(label: str) -> list:
    return [seg.strip() for seg in (label or "").split(",")
            if seg.strip()]


def _core_place(label: str) -> str:
    """The most specific place a location row names, normalized:
    "Greater Bengaluru Area" and "Bengaluru, Karnataka, India"
    share the core "bengaluru" — the two rows overlap, so code
    must never add both."""
    segs = _label_segments(label)
    first = _label_key(segs[0]) if segs else _label_key(label)
    first = re.sub(r"^(greater|city of)\s+", "", first)
    first = re.sub(r"\s+(metropolitan area|metro area|area|"
                   r"region)$", "", first)
    return first.strip()


def _parse_locations(packet: dict, total: int):
    """(entries, None) or (None, reason). The LinkedIn location
    dictionary (the user, Nov 13, 2026): "locations" (or
    "location_counts") as a list of {label, count, south_asia}
    rows copied exactly off the "Where they live" distribution,
    or as a {label: count} mapping whose South Asia rows are
    named in "south_asia_locations". Every count is an exact
    number from the page; the worker marks rows, code counts."""
    raw = packet.get("locations")
    if raw is None:
        raw = packet.get("location_counts")
    if raw is None:
        return None, None
    marked = packet.get("south_asia_locations")
    marked_keys = None
    if marked is not None:
        if not isinstance(marked, list) or \
                not all(isinstance(x, str) and x.strip()
                        for x in marked):
            return None, ("south_asia_locations must be a list "
                          "of location labels; got "
                          f"{marked!r}")
        marked_keys = {_label_key(x) for x in marked}
    entries: list = []
    seen: set = set()

    def add(label, count, south_asia):
        if not isinstance(label, str) or not label.strip():
            return f"location label must be a non-empty string; got {label!r}"
        if not _is_int(count) or count < 0:
            return (f"location {label!r} count must be an int "
                    f"≥ 0; got {count!r}")
        if count > total:
            return (f"location {label!r} count ({count}) exceeds "
                    f"total ({total})")
        if not isinstance(south_asia, bool):
            return (f"location {label!r} needs \"south_asia\": "
                    f"true/false — mark every row (the user, Nov 13, "
                    f"2026); got {south_asia!r}")
        key = _label_key(label)
        if key in seen:
            return f"duplicate location row {label!r}"
        seen.add(key)
        entries.append({"label": label.strip(), "count": count,
                        "south_asia": south_asia})
        return None

    if isinstance(raw, dict):
        if marked_keys is None:
            return None, ("a {label: count} locations dictionary "
                          "must name its South Asia rows in "
                          "\"south_asia_locations\" — code counts "
                          "only marked rows (the user, Nov 13, 2026)")
        for label, count in raw.items():
            problem = add(label, count,
                          _label_key(label) in marked_keys)
            if problem:
                return None, problem
    elif isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict):
                label = row.get("label") or row.get("location") \
                    or row.get("name")
                count = row.get("count")
                if count is None:
                    count = row.get("value")
                if count is None:
                    count = row.get("members")
                south_asia = row.get("south_asia")
                if south_asia is None:
                    south_asia = row.get("in_south_asia")
                if south_asia is None:
                    south_asia = row.get("is_south_asia")
                if south_asia is None and marked_keys is not None \
                        and isinstance(label, str):
                    south_asia = _label_key(label) in marked_keys
                if isinstance(south_asia, str):
                    low = south_asia.strip().lower()
                    if low in ("true", "yes", "south asia"):
                        south_asia = True
                    elif low in ("false", "no"):
                        south_asia = False
                problem = add(label, count, south_asia)
                if problem:
                    return None, problem
            elif isinstance(row, (list, tuple)) and len(row) == 3:
                problem = add(row[0], row[1], row[2])
                if problem:
                    return None, problem
            else:
                return None, (f"location rows must be objects "
                              f"{{label, count, south_asia}}; got "
                              f"{row!r}")
    else:
        return None, (f"locations must be a list of rows or a "
                      f"{{label: count}} dictionary; got "
                      f"{type(raw).__name__}")
    if not entries:
        return None, "locations must carry at least one row"
    if marked_keys is not None:
        unmatched = marked_keys - seen
        if unmatched:
            return None, ("south_asia_locations names rows that "
                          "are not in locations: "
                          + ", ".join(sorted(unmatched)))
    return entries, None


def _counted_south_asia(entries: list):
    """(count, counted_labels, basis) — the distinct South Asia
    headcount inside a marked location dictionary. LinkedIn's
    rows NEST (a country row contains its state rows, which
    contain their city and metro rows), so adding every marked
    row would count the same people two or three times. Code
    counts the broadest marked geography and skips narrower
    rows already inside it (the user's intent, Nov 13, 2026: the
    marked rows are the South Asia evidence; the India row in
    her screenshot — 298 of 339 — IS the South Asia count)."""
    marked = [e for e in entries if e["south_asia"]]
    if not marked:
        return 0, [], "no South Asia row marked"
    countries = [e for e in marked
                 if _label_key(e["label"]) in _SOUTH_ASIA_COUNTRIES]
    if countries:
        return (sum(e["count"] for e in countries),
                [e["label"] for e in countries],
                "country row(s)")
    state_rows = []
    for e in marked:
        segs = _label_segments(e["label"])
        if len(segs) == 2 and \
                _label_key(segs[-1]) in _SOUTH_ASIA_COUNTRIES:
            state_rows.append(e)
    if state_rows:
        counted = list(state_rows)
        total_count = sum(e["count"] for e in state_rows)
        state_keys = {_label_key(_label_segments(e["label"])[0])
                      for e in state_rows}
        counted_keys = {_label_key(e["label"]) for e in counted}
        city_state: dict = {}
        for e in marked:
            segs = _label_segments(e["label"])
            if len(segs) >= 3 and \
                    _label_key(segs[-1]) in _SOUTH_ASIA_COUNTRIES:
                city_state[_core_place(e["label"])] = \
                    _label_key(segs[1])
        for e in marked:
            if _label_key(e["label"]) in counted_keys:
                continue
            segs = _label_segments(e["label"])
            if any(_label_key(seg) in state_keys
                   for seg in segs[1:]):
                continue  # inside a counted state row
            if city_state.get(_core_place(e["label"])) \
                    in state_keys:
                continue  # a metro/city row inside a counted state
            counted.append(e)
            counted_keys.add(_label_key(e["label"]))
            total_count += e["count"]
        return (total_count, [e["label"] for e in counted],
                "state row(s), plus marked rows outside them")
    groups: dict = {}
    for e in marked:
        groups.setdefault(_core_place(e["label"]), []).append(e)
    counted = []
    total_count = 0
    for rows in groups.values():
        best = max(rows, key=lambda e: e["count"])
        counted.append(best)
        total_count += best["count"]
    return (total_count, [e["label"] for e in counted],
            "broadest row per marked place")


def validate_packet(packet) -> tuple[dict | None, str | None]:
    """(clean, None) when the packet is usable, else (None, reason).
    The clean dict carries the gate inputs already mapped: for a
    Revelio packet, india == south_asia (the user, Nov 12, 2026)."""
    if not isinstance(packet, dict):
        return None, f"packet must be a JSON object; got {type(packet).__name__}"
    unknown = sorted(set(packet) - _PACKET_FIELDS)
    if unknown:
        return None, (f"unknown field(s) {unknown}; the packet fields "
                      f"are {sorted(_PACKET_FIELDS)}")
    company = packet.get("company")
    if not isinstance(company, str) or not company.strip():
        return None, f"company must be a non-empty string; got {company!r}"
    source = _norm_source(packet.get("source"))
    if source is None:
        return None, (f"source must be \"Revelio Labs\" (or "
                      f"\"LinkedIn People\" under the not-on-Revelio "
                      f"fallback, the user, Nov 13, 2026); got "
                      f"{packet.get('source')!r}")
    if source == "LinkedIn People":
        # LINKEDIN FALLBACK (the user, Nov 13, 2026): Revelio stays the
        # primary gate for every use — stocking, backlog forward
        # movement, recruiter-first threads. ONLY a company with
        # no Revelio listing may be gated on LinkedIn (headcount
        # first, then the India employee ratio), and the packet
        # must attest the Revelio lookup came back empty.
        if packet.get("revelio_not_found") is not True:
            return None, ("a LinkedIn People packet is the FALLBACK "
                          "gate only (the user, Nov 13, 2026): it is "
                          "accepted solely for a company not on "
                          "Revelio — set \"revelio_not_found\": true "
                          "to attest the company was looked up on "
                          "Revelio and has no listing there; "
                          "otherwise read the company on Revelio "
                          "Labs and return its packet instead")
    elif source != "Revelio Labs":
        return None, (f"vetting is Revelio-first (the user, Nov 12, 2026; "
                      f"LinkedIn fallback Nov 13, 2026): a {source} "
                      f"packet is refused whole — read the company "
                      f"on Revelio Labs (or, only when it has no "
                      f"listing there, on LinkedIn People with "
                      f"\"revelio_not_found\": true) and return that "
                      f"packet instead")
    total = packet.get("total")
    if not _is_int(total) or total <= 0:
        return None, f"total must be a positive int; got {total!r}"
    if source == "LinkedIn People":
        region_field, pct_field = "india", "india_pct"
        basis = "india"
    else:
        region_field, pct_field = "south_asia", "south_asia_pct"
        basis = "south_asia"
    other = "india" if basis == "south_asia" else "south_asia"
    if packet.get(other) is not None or packet.get(other + "_pct") is not None:
        return None, (f"a {source} packet carries {region_field} / "
                      f"{pct_field}, not {other} / {other}_pct — the "
                      f"program does the mapping, not the packet")
    locations = None
    counted_labels: list = []
    count_basis = ""
    if source == "LinkedIn People":
        # THE LOCATION DICTIONARY (the user, Nov 13, 2026): when the
        # packet carries the "Where they live" rows, CODE derives
        # the South Asia count from them — the worker returns
        # exact numbers and marks rows; it never does the ratio
        # math. Any legacy india / india_pct riding along must
        # AGREE with the dictionary or the packet is refused.
        locations, problem = _parse_locations(packet, total)
        if problem:
            return None, problem
    if locations is not None:
        count, counted_labels, count_basis = \
            _counted_south_asia(locations)
        if count > total:
            return None, (f"the marked South Asia rows count "
                          f"{count:,} distinct employees, over "
                          f"the total ({total:,}) — the location "
                          f"dictionary is inconsistent")
        pct = 100.0 * count / total
        stated = packet.get(region_field)
        if stated is not None and stated != count:
            return None, (f"{region_field} {stated!r} disagrees "
                          f"with the location dictionary: code "
                          f"counts {count:,} distinct South Asia "
                          f"employees from the marked rows "
                          f"({count_basis}) — return the "
                          f"dictionary and let code count")
        stated_pct = packet.get(pct_field)
        if stated_pct is not None:
            if isinstance(stated_pct, bool) or \
                    not isinstance(stated_pct, (int, float)):
                return None, (f"{pct_field} must be a number; "
                              f"got {stated_pct!r}")
            if abs(float(stated_pct) - pct) > PCT_TOLERANCE:
                return None, (f"{pct_field} {stated_pct} does "
                              f"not match the location "
                              f"dictionary: {count:,} / {total:,} "
                              f"= {pct:.1f}% (tolerance "
                              f"{PCT_TOLERANCE} points)")
    else:
        count = packet.get(region_field)
        if not _is_int(count) or count < 0:
            return None, (f"{region_field} must be an int ≥ 0 (a zero "
                          f"count is real data); got {count!r}")
        if count > total:
            return None, (f"{region_field} count ({count}) exceeds total "
                          f"({total})")
        pct = packet.get(pct_field)
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            return None, f"{pct_field} must be a number; got {pct!r}"
        actual = 100.0 * count / total
        if abs(float(pct) - actual) > PCT_TOLERANCE:
            return None, (f"{pct_field} {pct} does not match the counts: "
                          f"{count:,} / {total:,} = {actual:.1f}% "
                          f"(tolerance {PCT_TOLERANCE} points — the page "
                          f"rounds, the packet must still agree)")
        pct = actual
    as_of = packet.get("as_of")
    if not isinstance(as_of, str) or not as_of.strip():
        return None, (f"as_of must be a non-empty string (the data "
                      f"date shown on the page, e.g. \"2026-06\"); "
                      f"got {as_of!r}")
    page = packet.get("page")
    if not isinstance(page, str) or not re.match(r"https?://", page.strip()):
        return None, f"page must be an http(s) URL; got {page!r}"
    item_id = packet.get("item_id")
    if item_id is not None and (not _is_int(item_id) or item_id <= 0):
        return None, f"item_id must be a positive int; got {item_id!r}"
    clean = {"company": company.strip(), "source": source,
             "total": total, "india": count, "india_basis": basis,
             "region_count": count, "region_pct": float(pct),
             "as_of": as_of.strip(), "page": page.strip(),
             "item_id": item_id,
             "revelio_not_found":
                 packet.get("revelio_not_found") is True,
             "locations": locations or [],
             "south_asia_counted_labels": counted_labels,
             "south_asia_count_basis": count_basis}
    return clean, None


def _resolve_item(clean: dict, log_state) -> tuple[object | None, str | None]:
    """The log item this check belongs to. Items are identified the
    way spine.py verify identifies them: by item id, or by exact
    company name (normalized). A forward-movement check belongs to a
    SUBMITTED application, so submitted items win the match."""
    if clean["item_id"] is not None:
        item = log_state.items.get(clean["item_id"])
        if item is None:
            return None, (f"item #{clean['item_id']} is not in the log")
        if state_mod.normalize_company(item.company) != \
                state_mod.normalize_company(clean["company"]):
            return None, (f"item #{clean['item_id']} is "
                          f"{item.company!r}, not {clean['company']!r} "
                          f"— packet refused, nothing recorded")
        return item, None
    norm = state_mod.normalize_company(clean["company"])
    matches = [it for it in log_state.items.values()
               if it.company
               and state_mod.normalize_company(it.company) == norm]
    if not matches:
        return None, (f"no item in the log for company "
                      f"{clean['company']!r} — nothing to record "
                      f"this check against")
    submitted = [it for it in matches if it.submitted_event]
    pool = submitted or matches
    if len(pool) > 1:
        ids = ", ".join(f"#{it.id}" for it in sorted(pool,
                                                     key=lambda i: i.id))
        return None, (f"company {clean['company']!r} has more than "
                      f"one plausible item ({ids}) — resend the "
                      f"packet with item_id naming the application "
                      f"this check belongs to")
    return pool[0], None


def _location_packet_text(clean: dict) -> str:
    """The returned LinkedIn location dictionary, spelled out for
    the log record (the user, Nov 13, 2026: the packet and the code's
    decision both append to the existing track of records).
    Commas only — state.py splits gate lines on semicolons."""
    rows = clean.get("locations") or []
    if not rows:
        return ""
    parts = [f"{e['label']} {e['count']:,}"
             + (" [South Asia]" if e["south_asia"] else "")
             for e in rows]
    counted = ", ".join(clean.get("south_asia_counted_labels")
                        or []) or "none"
    basis = clean.get("south_asia_count_basis") or \
        "the marked rows"
    return (f" LinkedIn location dictionary: "
            f"{', '.join(parts)}. Code counted the South Asia "
            f"headcount from {basis}: {counted}.")


def _verdict_line(item, clean: dict, verdict: str, block: bool,
                  india: int, pct: float) -> str:
    who = f"#{item.id} {item.company}"
    counts = (f"{clean['source']}: {who} {clean['total']:,} / "
              f"{india:,} ({pct:.1f}%)")
    basis_txt = ("South Asia count used as the India figure"
                 if clean["india_basis"] == "south_asia"
                 else "India count as read from the source")
    prov = (f"Forward-movement check (the user, Nov 12, 2026): "
            f"{clean['source']} data as of {clean['as_of']}, "
            f"{basis_txt}, page {clean['page']}."
            f"{_location_packet_text(clean)} {MARKER}")
    if verdict.startswith("HARD_PASS"):
        if verdict == "HARD_PASS_INDIA_BLOCK":
            tail = " (company blocked)"
        else:
            tail = " (total under 100 — no block for size alone)"
        return (f"GATE HARD PASS — {who} — {counts} → verdict "
                f"{verdict}{tail}. The application was already "
                f"submitted — this verdict is reported to the user with "
                f"the forward-movement news and changes nothing "
                f"about the item's recorded state. {prov}")
    alert_txt = (" — ALERT BAND (alert the user)"
                 if verdict == "PASS_ALERT" else "")
    return (f"GATE PASS — {who} — {counts}{alert_txt} → verdict "
            f"{verdict}. {prov}")


def record_packet(packet, log_path: Path = LOG_PATH,
                  fallback_state_path=None) -> dict:
    """Validate + decide + record one gate packet. Returns the
    structured result on success; raises ValueError with the refusal
    reason (nothing written) on any refusal."""
    clean, problem = validate_packet(packet)
    if problem:
        raise ValueError(problem)
    if clean["source"] == "LinkedIn People" and \
            gate_fallback_mod.pending_for(
                clean["company"],
                state_path=fallback_state_path) is None:
        # FALLBACK SEQUENCE, ENFORCED (the user, Nov 13, 2026 — the
        # code step between Revelio and LinkedIn): a fallback
        # packet records only against an open code order for the
        # company; a self-directed LinkedIn check is refused
        # whole, nothing written.
        raise ValueError(
            "LinkedIn fallback packet refused — code holds no "
            f"fallback order for {clean['company']!r}: hand the "
            "Revelio not-found result to code first (spine.py "
            "gate-packet not-found, or a stock form with gate "
            "{\"revelio_not_found\": true}) and run the LinkedIn "
            "check only on the order code hands back (the user, "
            "Nov 13, 2026)")
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    gate_cfg = rules.get("gate") or {}
    log_state = state_mod.parse_log(str(log_path))
    item, problem = _resolve_item(clean, log_state)
    if problem:
        raise ValueError(problem)
    india = clean["india"]
    pct = (100.0 * india / clean["total"]) if clean["total"] else 0.0
    # The EXISTING decision (stock.py's — the same thresholds
    # spine.py gate applies, from rules.yaml). Never reimplemented.
    verdict, block = stock_mod._gate_verdict(clean["total"], india,
                                             gate_cfg)
    line = log_writer.append_entry(
        str(log_path), _verdict_line(item, clean, verdict, block,
                                     india, pct))
    if clean["source"] == "LinkedIn People":
        # The fallback verdict is on record: clear the pending
        # order code opened for this company (the user, Nov 13, 2026).
        gate_fallback_mod.clear_pending(
            clean["company"], state_path=fallback_state_path)
    if block:
        # A block lands in the log's Blocked companies section
        # through code, not prose — the same writer stock.py
        # uses (the user, Nov 13, 2026).
        stock_mod._append_blocked_to_log(
            log_path,
            [{"company": item.company, "source": clean["source"],
              "total": clean["total"], "india": india, "pct": pct,
              "id": item.id}])
    # THE HANDOFF CHECK (same contract as stock.py): re-parse and
    # prove the verdict landed on the item as the parser reads it.
    landed = state_mod.parse_log(str(log_path)).items.get(item.id)
    expected_gate = {"PASS": "pass", "PASS_ALERT": "alert"}.get(
        verdict, "fail")
    landed_gate = landed.gate if landed else None
    return {"recorded": True, "verified": landed_gate == expected_gate,
            "item_id": item.id, "company": item.company,
            "role": item.role, "source": clean["source"],
            "total": clean["total"], "india": india,
            "india_pct": round(pct, 2),
            "page_pct": clean["region_pct"],
            "india_basis": clean["india_basis"],
            "locations": clean.get("locations") or [],
            "south_asia_counted_labels":
                clean.get("south_asia_counted_labels") or [],
            "south_asia_count_basis":
                clean.get("south_asia_count_basis") or "",
            "verdict": verdict, "block_company": block,
            "alert": verdict == "PASS_ALERT",
            "as_of": clean["as_of"], "page": clean["page"],
            "landed_gate": landed_gate, "log_line": line}


def main() -> int:
    ap = argparse.ArgumentParser(prog="gate_intake.py")
    ap.add_argument("command", choices=["format", "record"])
    ap.add_argument("packet_file", nargs="?",
                    help="filled packet JSON file (for record)")
    ap.add_argument("--log", default=None,
                    help="outreach log path (default: the live log)")
    args = ap.parse_args()
    if args.command == "format":
        print(FORMAT_TEXT)
        return 0
    if not args.packet_file:
        print("record needs a packet JSON file", file=sys.stderr)
        return 1
    try:
        packet = json.loads(Path(args.packet_file).read_text(
            encoding="utf-8"))
        result = record_packet(
            packet, log_path=Path(args.log) if args.log else LOG_PATH)
    except (ValueError, OSError) as exc:
        print(json.dumps({"recorded": False, "refused": str(exc)}))
        return 2
    print(json.dumps(result, indent=1))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
