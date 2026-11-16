"""The CODE STEP between Revelio and LinkedIn (the user, Nov 13, 2026:
"Between Revelio and LinkedIn company check, there should be a
step of code to track and give orders").

The sequence is owned by code, never by the worker:

  1. The worker returns a gate result to code — a Revelio packet,
     or the not-found result for a company Revelio does not list.
  2. On a not-found result, CODE (this module) writes the company
     into the tracked state (state/gate_fallback.json) as a
     pending fallback — company, when it was opened, which run —
     and hands back the ORDER: short fixed instruction lines
     telling the worker to open that company's LinkedIn company
     People page, take the "associated members" number at the
     top as the TOTAL headcount, copy every "Where they live"
     location row with its exact count, mark each row as South
     Asia or not, and return that dictionary to code. Code —
     never the worker — derives the South Asia count and ratio
     from the returned location dictionary.
  3. The LinkedIn packet (or, when LinkedIn gives no usable
     counts, the linkedin_checked drop) comes back to code; the
     recording paths (stock.record, gate_intake.record_packet)
     REFUSE it when no pending record matches the company — the
     LinkedIn check happens only on code's order — and on a
     successful record they clear the pending record here.
  4. inbox.daily_finish refuses to close a day while a pending
     record opened that day is still open.

State shape: {"pending": [{"company", "company_norm",
"opened_at" (ISO, America/Chicago), "run"}]}. One record per
company (normalized); re-opening an already-pending company
returns the existing record and the same order.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import state as state_mod

PROGRAM = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = PROGRAM / "state" / "gate_fallback.json"
CT = state_mod.CT


def _path(state_path) -> Path:
    return Path(state_path) if state_path else DEFAULT_STATE_PATH


def _load(state_path=None) -> dict:
    p = _path(state_path)
    if not p.exists():
        return {"pending": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"pending": []}
    if not isinstance(data, dict) or \
            not isinstance(data.get("pending"), list):
        return {"pending": []}
    return data


def _save(data: dict, state_path=None) -> None:
    p = _path(state_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")


def order_lines(company: str) -> list:
    """The ORDER code hands the worker when a company's Revelio
    check came back not-found. Short fixed lines; the worker
    executes them and returns JSON — it never decides the
    verdict and never runs this check before the order."""
    return [
        f"ORDER — LinkedIn fallback for {company} (code step, "
        f"the user, Nov 13, 2026): the Revelio check came back "
        f"not-found; code has tracked {company} as "
        f"fallback-owed. Run this check now — only on this "
        f"order, never self-directed.",
        f"1. Open {company}'s LinkedIn company People page.",
        "2. The FIRST number is the total headcount: copy the "
        "\"associated members\" number at the top of the page "
        "into \"total\". LinkedIn always shows it there.",
        "3. Below it, in the \"Where they live\" location "
        "distribution, copy EVERY row's exact label and exact "
        "number into \"locations\". Mark each row "
        "\"south_asia\": true or false with your best judgment: "
        "a row is South Asia when it is in India or elsewhere "
        "in South Asia, even when the label does not say India "
        "— for example \"Greater Bengaluru Area\" and "
        "\"Greater Delhi Area\" are India. Rows such as "
        "\"India\", \"Karnataka, India\", and \"Bengaluru, "
        "Karnataka, India\" are all South Asia; \"United "
        "States\" is not.",
        "4. Return the LinkedIn packet to code as JSON: "
        "{\"company\": ..., \"source\": \"LinkedIn People\", "
        "\"revelio_not_found\": true, \"total\": <associated "
        "members>, \"locations\": [{\"label\": <exact row "
        "label>, \"count\": <exact row number>, "
        "\"south_asia\": true/false}, ...], \"as_of\": ..., "
        "\"page\": <page URL>} — record it through stock.py "
        "(alert lane) or spine.py gate-packet record. Do NO "
        "ratio math yourself: code reads the dictionary, "
        "counts the distinct South Asia employees from the "
        "marked rows without double-counting a narrower row "
        "already inside a broader marked row (an India row "
        "already includes its states, cities and metro "
        "areas), divides by the total, decides pass/fail by "
        "the standing thresholds, and appends the packet and "
        "verdict to the outreach log.",
        "5. If LinkedIn gives no usable counts, return the "
        "drop through stock.py with gate "
        "{\"revelio_not_found\": true, \"linkedin_checked\": "
        "true} — code records the drop.",
        "Do not decide the verdict yourself, and do not write "
        "the company off in notes.",
    ]


def open_pending(company: str, run_label: str = "",
                 now: datetime | None = None,
                 state_path=None) -> dict:
    """Track a company as fallback-owed and return the order.
    Idempotent per company: an already-pending company returns
    its existing record with the same order."""
    name = (company or "").strip()
    if not name:
        raise ValueError("a fallback record needs a company name")
    norm = state_mod.normalize_company(name)
    data = _load(state_path)
    for rec in data["pending"]:
        if rec.get("company_norm") == norm:
            return {"company": rec["company"],
                    "already_pending": True,
                    "record": rec,
                    "order": order_lines(rec["company"])}
    when = now or datetime.now(CT)
    rec = {"company": name, "company_norm": norm,
           "opened_at": when.isoformat(),
           "run": run_label or ""}
    data["pending"].append(rec)
    _save(data, state_path)
    return {"company": name, "already_pending": False,
            "record": rec, "order": order_lines(name)}


def pending_for(company: str, state_path=None) -> dict | None:
    """The pending fallback record for a company, or None."""
    norm = state_mod.normalize_company(company or "")
    if not norm:
        return None
    for rec in _load(state_path)["pending"]:
        if rec.get("company_norm") == norm:
            return rec
    return None


def clear_pending(company: str, state_path=None) -> bool:
    """Drop a company's pending record (its fallback verdict or
    drop is now on record). True when one was cleared."""
    norm = state_mod.normalize_company(company or "")
    data = _load(state_path)
    kept = [r for r in data["pending"]
            if r.get("company_norm") != norm]
    if len(kept) == len(data["pending"]):
        return False
    data["pending"] = kept
    _save(data, state_path)
    return True


def list_pending(state_path=None) -> list:
    return list(_load(state_path)["pending"])


def pending_opened_on(day, state_path=None) -> list:
    """Pending records opened on a given America/Chicago date —
    daily_finish uses this to refuse closing a run whose alert
    pass still owes a fallback."""
    out = []
    for rec in _load(state_path)["pending"]:
        try:
            opened = datetime.fromisoformat(rec["opened_at"])
        except (KeyError, ValueError):
            continue
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=CT)
        if opened.astimezone(CT).date() == day:
            out.append(rec)
    return out
