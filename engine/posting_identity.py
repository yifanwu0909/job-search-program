"""posting_identity.py — is this posting the same job as that one?

the user, Nov 13, 2026: the three discovery sources are highly duplicated
by nature — a company posts the same role on Jobright, Indeed and
LinkedIn at once — "make sure the code handles that." Per-posting
duplication across platforms is decided HERE, in code, from identity
signals that survive the platform hop:

  * ATS / requisition identity — the employer-side posting id that
    every platform's copy points back to: Greenhouse gh_jid values,
    Lever/Ashby URL UUIDs, Workday R-numbers, Jobright's 24-hex
    listing id, SmartRecruiters/icims long numeric ids, and any
    `req <id>` the log recorded. Extracted from URLs and from the
    free text of an item's recorded events alike.
  * Role identity — the role title with the abbreviations platforms
    vary expanded (Sr. = Senior, ML = Machine Learning, ...), so
    "Sr. Data Scientist" on Indeed and "Senior Data Scientist" on
    Jobright produce the SAME token set.

stock.py's dedupe consults this module in addition to its existing
checks (LinkedIn job id, exact apply URL, the fuzzy company+role
overlap): a candidate whose ATS id set intersects a prior item's, or
whose company + expanded role token set equals a prior item's, is
the same posting — whichever platform it arrived from.
"""
from __future__ import annotations

import re

# Abbreviations platforms swap freely in the same posting's title.
_EXPANSIONS = {
    "sr": ("senior",),
    "jr": ("junior",),
    "ml": ("machine", "learning"),
    "ds": ("data", "scientist"),
    "sci": ("scientist",),
    "engr": ("engineer",),
    "assoc": ("associate",),
    "asst": ("assistant",),
    "mgr": ("manager",),
    "dev": ("developer",),
}

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_HEX24_RE = re.compile(r"\b[0-9a-f]{24}\b")
_QUERY_ID_RE = re.compile(
    r"[?&](?:gh_jid|job_id|jobid|jid|req|req_id|requisition_id|"
    r"requisitionid|posting_id|jobidnum)=([A-Za-z0-9_-]{4,})")
_WORKDAY_REQ_RE = re.compile(r"\bR-?(\d{5,})\b")
_LONG_NUM_RE = re.compile(r"/(\d{5,})(?:[/?#]|$)")
_REQ_TEXT_RE = re.compile(r"\breq(?:uisition)?[\s#:\-]+([A-Za-z0-9_-]{4,})",
                          re.IGNORECASE)


def expanded_tokens(text: str) -> set[str]:
    """Role-title tokens with platform abbreviations expanded."""
    out: set[str] = set()
    for tok in re.split(r"[^a-z0-9]+", (text or "").lower()):
        if not tok:
            continue
        if tok in _EXPANSIONS:
            out.update(_EXPANSIONS[tok])
        elif len(tok) > 2 or tok in ("i", "ii", "iii", "iv"):
            out.add(tok)
    return out


def role_key(company: str, role: str):
    """(normalized company, expanded role token set) — equal keys
    mean the same posting title at the same company."""
    from state import normalize_company
    return (normalize_company(company or ""),
            frozenset(expanded_tokens(role or "")))


def extract_ids(text: str) -> set[str]:
    """Employer/posting identity tokens found in a URL or log text.

    Values are compared bare (a Greenhouse id is the same number in
    a query string, a path, or a `req` note), lowercased, with the
    Workday R-prefix normalized off.
    """
    text = text or ""
    ids: set[str] = set()
    ids.update(m.group(0).lower() for m in _UUID_RE.finditer(text))
    ids.update(m.group(0).lower() for m in _HEX24_RE.finditer(text))
    ids.update(m.group(1).lower() for m in _QUERY_ID_RE.finditer(text))
    ids.update(m.group(1) for m in _WORKDAY_REQ_RE.finditer(text))
    ids.update(m.group(1) for m in _LONG_NUM_RE.finditer(text))
    ids.update(m.group(1).lower() for m in _REQ_TEXT_RE.finditer(text))
    return {i for i in ids if len(i) >= 4}


def candidate_ids(raw: dict) -> set[str]:
    """Identity tokens for an incoming stock form."""
    ids: set[str] = set()
    ids.update(extract_ids(str(raw.get("url") or "")))
    for field in ("req_id", "jr_id", "indeed_id", "linkedin_job_id"):
        value = str(raw.get(field) or "").strip()
        if value:
            ids.add(value.lower())
            ids.update(extract_ids(value))
    return ids


def prior_ids(item) -> set[str]:
    """Identity tokens for an existing log item: its LinkedIn job id
    plus every id extractable from its recorded events (the stocked
    event carries the apply URL and any req id)."""
    ids: set[str] = set()
    if getattr(item, "linkedin_job_id", ""):
        ids.add(str(item.linkedin_job_id).strip().lower())
    for event in getattr(item, "events", []) or []:
        ids.update(extract_ids(str(event[3] or "")))
    return ids
