"""outreach_targets.py — code decides who outreach may invite.

the user, Nov 13, 2026: "use code to dictate all these rules; leave minimum
decision making to the agent." The hiring-contact rules (career-ops
contacto finding, NO per-role cap, NO peers) lived in prose — the
outreach run judged each person's title itself. This module moves the
judgment into code, in the same packet pattern as gate_intake:

  * the run finds people with contacto and hands code ONE JSON packet:
    {"targets": [{"person", "title", "company", "type", "link",
                  "current_employee", "role"?}, ...]};
  * code validates EVERY target against rules.yaml
    invitations.hiring_contacts (the allow-keyword groups and the peer
    filter live in config; this module only applies them) and against
    the blocked-company set parsed from the outreach log;
  * code returns {"accepted": [...], "rejected": [{..., "reason"}]}.
    The run invites ONLY accepted people. There is NO per-role cap in
    code — every accepted person for a role stays accepted; the daily
    30-verified target in invitations.py still bounds the day's sends.

A target is ACCEPTED only when ALL of these hold:
  * the source is labelled contacto (the user, Nov 14, 2026 — ALL outreach
    comes from contacto; a target with NO source label is refused, and
    a target labelled with any other source — LinkedIn search, My
    Network suggestions, the Premium hiring list — is refused; if
    contacto finds nobody for a job, the run moves to the next job and
    never searches LinkedIn for outreach);
  * REPLENISHMENT (the user, Nov 23, 2026; widened Nov 24, 2026, with
    the order refined the same day — California first, US-wide only
    when California yields no more): when the contacto pool for the
    applied jobs runs out before the daily target is met, the run
    replenishes — still through contacto, never LinkedIn search — by
    running contacto on AI/ML/Data job postings and collecting the
    general AI technical recruiters it returns, California-based
    first, then anywhere else in the US. A target flagged
    "replenishment": true must ALSO pass the replenishment gate in
    config: a recruiter title carrying a technical/AI/ML/data keyword,
    and a US location — matched by _us_location (config keywords incl.
    US city/metro names, or a ", ST" state abbreviation), because
    LinkedIn locations rarely spell the state out (the gate is the
    outer boundary; the CA-first order is the run's);
  * person, title and company are present (else malformed);
  * the worker did not itself label the person a peer (type "peer");
  * current_employee is exactly true (the run verifies employment on
    the profile BEFORE this packet — code will not accept an
    unverified or former employee);
  * the link is a linkedin.com/in/ profile link;
  * the company is not on the blocked list;
  * the title matches one config allow group (recruiting, leadership,
    senior_ic, manager — checked in that order). A title matching no
    group is at or below the user's level (Senior Data Scientist) and is
    rejected as a peer: a bare "Senior Data Scientist", "Data
    Scientist", "Junior Data Scientist" or "Senior Machine Learning
    Engineer" title carries no allow keyword, by construction.
"""
from __future__ import annotations

import re

GROUP_ORDER = ("recruiting", "leadership", "senior_ic", "manager")

# US state abbreviations (USPS, incl. DC). LinkedIn profile locations and
# search snippets very often carry ONLY the abbreviation ("San Jose, CA",
# "Austin, TX, United States") or a bare city / metro name ("Austin",
# "Greater Seattle Area") — the config keyword list holds full state
# names, so a substring pass over it alone refused plainly-US recruiters
# as replenishment_location_not_us (Nov 25, 2026: 22 of 22 targets in one
# packet refused on city-only locations; Nov 27, 2026: replenishment
# produced 0 code-ready targets and the day closed at 5 of 30). The
# abbreviation is accepted only in the ", ST" position LinkedIn uses, so
# ordinary words (IN, ME, OR) in a location string can never trip it.
_US_STATE_ABBR = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA",
    "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX",
    "UT", "VT", "VA", "WA", "WV", "WI", "WY",
)
_US_ABBR_RE = re.compile(
    r",\s*(?:" + "|".join(_US_STATE_ABBR) + r")\b")


def _us_location(location: str, keywords) -> bool:
    """True when a free-text location is recognisably in the US.

    Three passes, any one enough: (1) a config keyword (full state
    names, "united states", and the US city / metro names config also
    carries) appears in the text; (2) a US state abbreviation in the
    ", ST" position; (3) nothing else — a bare non-US place name
    ("London, England, United Kingdom", "Toronto, Ontario, Canada",
    "Vancouver, British Columbia") matches none of these and stays out.
    """
    loc = str(location or "")
    loc_low = loc.lower()
    if any(str(k).lower() in loc_low for k in (keywords or [])):
        return True
    return bool(_US_ABBR_RE.search(loc))


def _keyword_re(keyword: str) -> re.Pattern:
    kw = str(keyword).strip().lower()
    if " " in kw:
        return re.compile(re.escape(kw))
    return re.compile(r"\b" + re.escape(kw) + r"\b")


def classify_title(title: str, allow_groups: dict) -> str | None:
    """Return the allow-group name a title matches, or None (peer)."""
    text = " " + re.sub(r"\s+", " ", str(title or "").lower()).strip() + " "
    for group in GROUP_ORDER:
        for kw in (allow_groups or {}).get(group) or []:
            if _keyword_re(kw).search(text):
                return group
    return None


def validate_targets(packet, hiring_cfg: dict, blocked_keys) -> dict:
    """Validate one contacto packet. Returns accepted/rejected lists.

    Raises ValueError on a malformed packet (no targets list) — the
    packet is refused whole, like gate packets; nothing is decided
    from prose.
    """
    if isinstance(packet, list):
        targets = packet
    elif isinstance(packet, dict):
        targets = packet.get("targets")
    else:
        targets = None
    if not isinstance(targets, list):
        raise ValueError(
            "REFUSED — packet must be a JSON list or {\"targets\": [...]} "
            "of contacto people. Nothing was decided.")
    cfg = hiring_cfg or {}
    # The cap lives in config: null means NO per-role cap (the user, Nov 13,
    # 2026). Code enforces whatever config says — if a numeric cap is
    # ever set there, it is applied per (company, role) here, never by
    # the agent's judgment.
    max_per_role = cfg.get("max_per_role")
    allow_groups = cfg.get("allow_title_keywords") or {}
    blocked = blocked_keys or set()

    accepted: list[dict] = []
    rejected: list[dict] = []
    per_role_counts: dict[tuple, int] = {}

    for raw in targets:
        t = dict(raw or {})
        person = str(t.get("person") or t.get("name") or "").strip()
        title = str(t.get("title") or "").strip()
        company = str(t.get("company") or "").strip()
        row = {"person": person, "title": title, "company": company,
               "type": t.get("type"), "link": t.get("link"),
               "role": t.get("role"), "source": t.get("source"),
               "location": t.get("location"),
               "replenishment": t.get("replenishment")}

        def refuse(reason: str) -> None:
            rejected.append({**row, "reason": reason})

        if not person or not title or not company:
            refuse("malformed_missing_person_title_or_company")
            continue
        # CONTACTO ONLY (the user, Nov 14, 2026 — "Burn this into code"): all
        # outreach people come from contacto, and the packet must SAY so.
        # Under contacto_only, every target carries a "source" label:
        # missing/blank is refused, and any source other than contacto
        # (LinkedIn search, My Network suggestions, the Premium hiring
        # list, people-viewers) is refused — the run may not invite from
        # LinkedIn-found people at all, and may not slip a person past
        # code by leaving the source off.
        if cfg.get("contacto_only"):
            src = str(t.get("source") or "").strip().lower()
            if not src:
                refuse("source_missing_contacto_only")
                continue
            if not any(k in src for k in
                       ("contacto", "saved_contact", "saved contact")):
                refuse("non_contacto_source_refused")
                continue
        if str(t.get("type") or "").strip().lower() == "peer":
            refuse("peer_type_labelled_by_finder")
            continue
        if t.get("current_employee") is not True:
            refuse("current_employment_not_verified")
            continue
        link = str(t.get("link") or "")
        if "linkedin.com/in/" not in link:
            refuse("not_a_linkedin_profile_link")
            continue
        from state import normalize_company
        if normalize_company(company) in blocked:
            refuse("blocked_company")
            continue
        group = classify_title(title, allow_groups)
        if group is None:
            refuse("peer_or_below_no_influence_title")
            continue
        if t.get("replenishment") is True:
            # REPLENISHMENT GATE (the user, Nov 23, 2026; US-wide Nov 24,
            # 2026): contacto-found general AI technical recruiters for
            # ML/Data — recruiter title, an AI/ML/data keyword in the
            # title, US location.
            rep = cfg.get("replenishment_when_pool_exhausted") or {}
            if rep.get("enabled") is not True:
                refuse("replenishment_not_enabled")
                continue
            if group != "recruiting":
                refuse("replenishment_not_recruiter_title")
                continue
            title_low = title.lower()
            if not any(str(k).lower() in title_low
                       for k in (rep.get("title_keywords_any") or [])):
                refuse("replenishment_title_not_ai_ml_data")
                continue
            if not _us_location(t.get("location"),
                                rep.get("location_keywords")):
                refuse("replenishment_location_not_us")
                continue
        if isinstance(max_per_role, int) and max_per_role > 0:
            key = (normalize_company(company),
                   str(t.get("role") or "").strip().lower())
            if per_role_counts.get(key, 0) >= max_per_role:
                refuse("per_role_cap_from_config")
                continue
            per_role_counts[key] = per_role_counts.get(key, 0) + 1
        accepted.append({**row, "allow_group": group})

    return {"accepted": accepted, "rejected": rejected,
            "max_per_role": max_per_role}
