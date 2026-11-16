"""discovery.py — code manages every job-discovery source.

the user, Nov 13, 2026: "manage these in code" (of the three discovery
sources: LinkedIn job alerts, Jobright.ai, Indeed) — on top of her
standing contract: code handles the flow, code gives the worker short
fixed instructions, the worker returns JSON, code decides and records.

Until now the sources' parameters lived in rules.yaml `discovery:`
and rode the `spine.py next` packet, but the WORK ORDER for a pass was
prose in worker_template.md and nothing in code tracked which sources
had actually run. This module is the sources' manager:

  * SOURCES — the registry of the three live sources, built entirely
    from rules.yaml `discovery:` (search matrices, the sites' own
    filters, pass counts, page caps). Change a rule in config and the
    plan changes; there is no second copy here.
  * plan(rules, source?) — the short fixed instruction packet for one
    source (or all three): exactly what a worker is to run, nothing
    more. Jobright and Indeed are worker passes; LINKEDIN_ALERT is
    NOT a worker pass — its plan names its real manager, the daily
    inbox job-alert flow (inbox.py), so no worker ever improvises an
    alert pass.
  * record(state_path, packet) — the worker returns ONE JSON packet
    per pass ({source, run_id, searches_done, cards_seen,
    candidates}); code validates it — known source, the searches_done
    set must cover the config matrix exactly, counts are non-negative
    ints, and ONE pass per source per run_id (a second record for the
    same run+source is REFUSED, enforcing the user's one-pass rule in code,
    not prose) — and appends it to the discovery state file.
  * status(state_path, day) — code-computed coverage for a date: per
    source, passes recorded, cards seen, candidates returned, last
    run. The morning report and the guardian read this, not prose.

Candidates themselves still stock through stock.py (screening order,
gate, dedupe) — this module manages the sources and their passes, not
individual postings.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from state import CT

WORKER_SOURCES = ("JOBRIGHT", "INDEED")
ALL_SOURCES = ("JOBRIGHT", "INDEED", "LINKEDIN_ALERT")


def _search_rows(cfg: dict, key: str) -> list[dict]:
    rows = []
    for row in cfg.get(key) or []:
        rows.append({"title": row.get("title"),
                     "location_scope": row.get("location_scope"),
                     "location_via": row.get("location_via"),
                     "remote_via": row.get("remote_via")})
    return rows


def build_plan(rules: dict, source: str | None = None) -> dict:
    """The per-source work orders, generated from rules.yaml only."""
    cfg = (rules or {}).get("discovery") or {}
    plans: dict[str, dict] = {}
    plans["JOBRIGHT"] = {
        "source": "JOBRIGHT",
        "kind": "worker_pass",
        "method": cfg.get("jobright_method"),
        "passes_per_run": cfg.get("passes_per_source_per_run"),
        "searches": _search_rows(cfg, "jobright_searches"),
        "filters": {"date_posted": cfg.get("jobright_date_filter"),
                    "job_type": cfg.get("jobright_job_type_filter")},
        "newest_first": cfg.get("newest_first"),
        "max_posting_age_hours": cfg.get("max_posting_age_hours"),
        "screening_only": True,
        "apply_route": "employer/ATS site — never through Jobright",
        "card_cap_per_pass": 50,
        "instructions": [
            "Run ONLY the searches listed, each with BOTH site filters set first.",
            "Screen newest-first; stop at the 24-hour boundary.",
            "Return candidates as stock forms; return the pass packet to `spine.py discovery record`.",
        ],
    }
    plans["INDEED"] = {
        "source": "INDEED",
        "kind": "worker_pass",
        "method": cfg.get("indeed_method"),
        "passes_per_run": cfg.get("passes_per_source_per_run"),
        "searches": _search_rows(cfg, "indeed_searches"),
        "filters": {"date_posted": cfg.get("indeed_date_filter"),
                    "job_type": cfg.get("indeed_job_type_filter")},
        "newest_first": cfg.get("newest_first"),
        "max_posting_age_hours": cfg.get("max_posting_age_hours"),
        "screening_only": True,
        "apply_route": "employer/ATS site — never through Indeed",
        "card_cap_per_pass": 50,
        "instructions": [
            "Run ONLY the searches listed, each with BOTH site filters set first (Remote goes in the location field).",
            "Screen newest-first; stop at the 24-hour boundary.",
            "Return candidates as stock forms; return the pass packet to `spine.py discovery record`.",
        ],
    }
    plans["LINKEDIN_ALERT"] = {
        "source": "LINKEDIN_ALERT",
        "kind": "email_flow",
        "method": cfg.get("linkedin_alert_method"),
        "managed_by": "the daily inbox check's job-alert flow (inbox.py "
                      "jobalert-intake / jobalert-record) — NOT a batch "
                      "worker pass",
        "alerts": cfg.get("linkedin_alerts"),
        "max_pages": cfg.get("linkedin_alert_max_pages"),
        "easy_apply_allowed": cfg.get("linkedin_alert_easy_apply_allowed"),
        "screening": "inbox.py hands the daily run short fixed "
                     "instructions; candidates return as JSON; code "
                     "screens (blacklist, duplication, Revelio gate) "
                     "before any posting is opened",
        "instructions": [
            "Do NOT run an alert pass from a batch worker — the daily inbox check owns this source.",
        ],
    }
    if source:
        key = str(source).upper()
        if key not in plans:
            raise ValueError(
                f"REFUSED — unknown discovery source {source!r}; "
                f"known sources: {', '.join(ALL_SOURCES)}.")
        return {key: plans[key]}
    return plans


def _load_state(state_path: Path) -> dict:
    if Path(state_path).exists():
        try:
            data = json.loads(Path(state_path).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {"passes": []}


def _save_state(state_path: Path, data: dict) -> None:
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    Path(state_path).write_text(json.dumps(data, indent=1), encoding="utf-8")


def _matrix_keys(cfg: dict, source: str) -> set:
    key = {"JOBRIGHT": "jobright_searches",
           "INDEED": "indeed_searches"}[source]
    return {(r.get("title"), r.get("location_scope"))
            for r in cfg.get(key) or []}


def record_pass(state_path, packet: dict, rules: dict,
                now: datetime | None = None) -> dict:
    """Validate and record ONE worker discovery pass. Returns the row.

    Raises ValueError (REFUSED, nothing written) on: unknown or
    non-worker source, missing run_id, a searches_done set that does
    not cover the config matrix exactly, bad counts, or a second pass
    for the same run+source (the user's one-pass-per-run rule, in code).
    """
    cfg = (rules or {}).get("discovery") or {}
    if not isinstance(packet, dict):
        raise ValueError("REFUSED — pass packet must be a JSON object.")
    source = str(packet.get("source") or "").upper()
    if source not in WORKER_SOURCES:
        raise ValueError(
            f"REFUSED — discovery passes are recorded only for the "
            f"worker sources {', '.join(WORKER_SOURCES)}; got "
            f"{packet.get('source')!r}. (LINKEDIN_ALERT passes are "
            f"recorded by the inbox job-alert flow, not here.)")
    run_id = str(packet.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("REFUSED — pass packet needs its run_id.")
    done = {(str(s.get("title")), str(s.get("location_scope")))
            for s in packet.get("searches_done") or []}
    want = {(str(t), str(l)) for t, l in _matrix_keys(cfg, source)}
    if done != want:
        raise ValueError(
            f"REFUSED — searches_done for {source} must cover the "
            f"config matrix exactly. Missing: {sorted(want - done)}; "
            f"extra: {sorted(done - want)}.")
    counts = {}
    for field in ("cards_seen", "candidates"):
        value = packet.get(field)
        if not isinstance(value, int) or isinstance(value, bool) \
                or value < 0:
            raise ValueError(
                f"REFUSED — {field} must be a non-negative int, "
                f"got {value!r}.")
        counts[field] = value
    now = now or datetime.now(CT)
    row = {"source": source, "run_id": run_id,
           "day": now.date().isoformat(),
           "ts": now.isoformat(),
           "cards_seen": counts["cards_seen"],
           "candidates": counts["candidates"]}
    data = _load_state(Path(state_path))
    for prior in data["passes"]:
        if prior.get("run_id") == run_id \
                and prior.get("source") == source:
            raise ValueError(
                f"REFUSED — a {source} pass is already recorded for "
                f"run {run_id} (one pass per source per run, in code). "
                f"Nothing was written.")
    data["passes"].append(row)
    _save_state(Path(state_path), data)
    return row


def coverage(state_path, day: str | None = None,
             now: datetime | None = None) -> dict:
    """Code-computed per-source coverage for one CT date."""
    day = day or (now or datetime.now(CT)).date().isoformat()
    data = _load_state(Path(state_path))
    out: dict[str, dict] = {}
    for source in ALL_SOURCES:
        rows = [p for p in data["passes"]
                if p.get("source") == source and p.get("day") == day]
        out[source] = {
            "passes": len(rows),
            "cards_seen": sum(p.get("cards_seen", 0) for p in rows),
            "candidates": sum(p.get("candidates", 0) for p in rows),
            "last_run_id": rows[-1]["run_id"] if rows else None,
        }
    return {"date": day, "sources": out}
