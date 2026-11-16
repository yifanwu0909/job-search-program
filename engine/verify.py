"""verify.py — post-submission Gmail confirmation check.

Given a company + the date it was submitted, search Gmail (CLI) for the ATS
confirmation. Returns found (message id, sender, date, subject) or not-found.
The +10-minute check is early-verify ONLY; the 30-minute check decides limbo.
A not-found NEVER triggers resubmission — this module only reads.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import date

GMAIL_CLI = "/opt/hatch/bin/hatch_gws_cli"
CONFIRM_SUBJECT_RE = re.compile(
    r"thank|received|application|applying|submitted", re.I)


def _company_tokens(company: str) -> list[str]:
    toks = [t for t in re.split(r"[^A-Za-z0-9]+", company) if len(t) > 2]
    return toks


_ROLE_WORDS = ("scientist", "engineer", "manager", "analyst", "developer",
               "designer", "architect", "recruiter", "consultant", "intern")


def _role_conflict(subject: str, role: str | None) -> bool:
    """True when the subject names a role that is clearly NOT the item's
    role (audit fix, Nov 4, 2026): a confirmation for a different role at
    the same company must never verify this item. A generic subject (no
    role words at all) makes no claim and never conflicts."""
    if not role:
        return False
    s = subject.lower()
    if not any(w in s for w in _ROLE_WORDS):
        return False
    role_toks = {t for t in re.split(r"[^a-z]+", role.lower()) if len(t) > 2}
    return not any(t in s for t in role_toks)


def subject_is_generic(subject: str) -> bool:
    """True when the subject names no role at all ("We received your
    application") — such a receipt cannot be tied to a specific role by
    subject alone."""
    s = (subject or "").lower()
    return not any(w in s for w in _ROLE_WORDS)


def check_confirmation(company: str, since: date,
                       role: str | None = None,
                       max_results: int = 10) -> dict:
    """Search Gmail for a confirmation from/mentioning `company` since `since`."""
    query = f'"{company}" after:{since:%Y/%m/%d}'
    try:
        proc = subprocess.run(
            [GMAIL_CLI, "gmail", "+triage", "--query", query,
             "--max", str(max_results), "--format", "json"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"found": False, "company": company, "error": str(exc)}
    if proc.returncode != 0:
        return {"found": False, "company": company,
                "error": (proc.stderr or "gmail CLI failed").strip()[:300]}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"found": False, "company": company,
                "error": "gmail CLI returned non-JSON output"}
    tokens = [t.lower() for t in _company_tokens(company)]
    best = None
    for msg in data.get("messages", []):
        subject = msg.get("subject", "")
        sender = msg.get("from", "")
        hay = f"{subject} {sender}".lower()
        if not CONFIRM_SUBJECT_RE.search(subject):
            continue
        if tokens and not any(t in hay for t in tokens):
            continue
        if _role_conflict(subject, role):
            continue
        best = msg  # triage returns newest first; the newest match is the receipt
        break
    if best:
        return {"found": True, "company": company,
                "message_id": best.get("id"), "from": best.get("from"),
                "date": best.get("date"), "subject": best.get("subject")}
    return {"found": False, "company": company,
            "note": "no confirmation found (not a failure; never resubmit on this)"}
