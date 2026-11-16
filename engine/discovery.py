"""discovery.py — code manages every job-discovery source.

the user, Nov 13, 2026: "manage these in code" (of the discovery
sources: LinkedIn job alerts, Jobright.ai, Indeed) — on top of her
standing contract: code handles the flow, code gives the worker short
fixed instructions, the worker returns JSON, code decides and records.

CAREEROPS IS AN ADDITIONAL SOURCE (the user, Nov 16, 2026 — first
"Use CareerOps job discovery function to substitute bench. Still
verify for duplicate", then reversed the same day: "Don't replace
indeed and jobright. Use career ops as additional resources to stock
the bench. Roll back the commitment and build from last commit."):
the career-ops SCAN function (the zero-token scanners in the
career-ops install — scan-ats-full.mjs, the keyword-first sweep of
the public ATS datasets, plus scan.mjs over portals.yml
tracked_companies) runs as a THIRD worker source alongside the
Jobright and Indeed browser passes, which are unchanged. Scan output
is a CANDIDATE FEED ONLY: every candidate still stocks through
stock.py, whose screening order is unchanged — (1) BLACKLIST,
(2) DUPLICATION (the all-time applied record plus the cross-platform
posting-ID match), (3) the Revelio gate with its LinkedIn fallback.
The duplicate screen remains the code authority; this program
remains the only system of record.

This module is the sources' manager:

  * SOURCES — the registry of the live sources, built from
    rules.yaml `discovery:` (search matrices, the sites' own filters,
    scan steps, pass counts, page caps). Change a rule in config and
    the plan changes; there is no second copy here. One override (the
    user, Nov 16, 2026 — "wire it so the onboarding answers drive the
    search"): when answers.yaml carries a real `job_search` (titles
    and locations from onboarding), effective_cfg derives the worker
    sources' matrices, job-type filters and the CAREEROPS scan's
    titles/locations from it instead.
  * plan(rules, source?) — the short fixed instruction packet for one
    source (or all): exactly what a worker is to run, nothing more.
    Jobright, Indeed and CAREEROPS are worker passes; LINKEDIN_ALERT
    is NOT a worker pass — its plan names its real manager, the daily
    inbox job-alert flow (inbox.py), so no worker ever improvises an
    alert pass.
  * record(state_path, packet) — the worker returns ONE JSON packet
    per pass ({source, run_id, searches_done | steps_done,
    cards_seen, candidates}); code validates it — known worker
    source, the searches_done set must cover the config matrix
    exactly (Jobright/Indeed) or the steps_done set must cover the
    config scan steps exactly (CAREEROPS), counts are non-negative
    ints (a CAREEROPS packet may carry the candidate list itself,
    each entry needing company/title/url), and ONE pass per source
    per run_id (a second record for the same run+source is REFUSED,
    enforcing the user's one-pass rule in code, not prose) — and
    appends it to the discovery state file.
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

WORKER_SOURCES = ("JOBRIGHT", "INDEED", "CAREEROPS")
ALL_SOURCES = ("JOBRIGHT", "INDEED", "CAREEROPS", "LINKEDIN_ALERT")


def _real_strings(values) -> list[str]:
    out = []
    for value in values or []:
        if isinstance(value, str) and value.strip() \
                and "YOUR_" not in value:
            out.append(value.strip())
    return out


def effective_cfg(rules: dict, answers: dict | None = None) -> dict:
    """The discovery config the plan and the pass validation run on.

    When answers.yaml carries a real job_search (titles AND locations,
    written by onboarding), the worker sources' search matrices and
    job-type filters are derived from it: one location-field search
    per title over the user's places combined into a single scope,
    plus one Remote search per title when Remote is among the places
    or the workplace says remote; the CAREEROPS scan's titles and
    locations are derived from it too. Without a real job_search, the
    rules.yaml discovery config is used exactly as written.
    """
    cfg = dict((rules or {}).get("discovery") or {})
    js = (answers or {}).get("job_search") or {}
    titles = _real_strings(js.get("titles"))
    locations = _real_strings(js.get("locations"))
    if not titles or not locations:
        return cfg
    remote = any(loc.lower() == "remote" for loc in locations)
    if "remote" in str(js.get("workplace") or "").lower():
        remote = True
    scope = "/".join(loc for loc in locations if loc.lower() != "remote")

    def rows(remote_via):
        out = []
        if scope:
            out += [{"title": t, "location_scope": scope,
                     "location_via": "location_field"} for t in titles]
        if remote:
            out += [{"title": t, "location_scope": "Remote",
                     "remote_via": remote_via} for t in titles]
        return out

    cfg["jobright_searches"] = rows("work_model_filter")
    cfg["indeed_searches"] = rows("location_field")
    job_type = "part_time" if "part" in str(
        js.get("employment_type") or "").lower() else "full_time"
    cfg["jobright_job_type_filter"] = job_type
    cfg["indeed_job_type_filter"] = job_type
    cfg["careerops_titles"] = titles
    cfg["careerops_locations"] = locations
    cfg["careerops_job_type"] = job_type
    return cfg


def _search_rows(cfg: dict, key: str) -> list[dict]:
    rows = []
    for row in cfg.get(key) or []:
        rows.append({"title": row.get("title"),
                     "location_scope": row.get("location_scope"),
                     "location_via": row.get("location_via"),
                     "remote_via": row.get("remote_via")})
    return rows


def _scan_steps(cfg: dict) -> list[dict]:
    steps = []
    for row in cfg.get("careerops_scanners") or []:
        steps.append({"scanner": row.get("scanner"),
                      "command": row.get("command")})
    return steps


def build_plan(rules: dict, source: str | None = None,
               answers: dict | None = None) -> dict:
    """The per-source work orders, generated from the effective
    discovery config (see effective_cfg)."""
    cfg = effective_cfg(rules, answers)
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
    plans["CAREEROPS"] = {
        "source": "CAREEROPS",
        "kind": "worker_pass",
        "method": cfg.get("careerops_method"),
        "passes_per_run": cfg.get("passes_per_source_per_run"),
        "install_root": cfg.get("careerops_root"),
        "portals_config": cfg.get("careerops_portals"),
        "scan_steps": _scan_steps(cfg),
        "titles": cfg.get("careerops_titles"),
        "locations": cfg.get("careerops_locations"),
        "job_type": cfg.get("careerops_job_type"),
        "newest_first": cfg.get("newest_first"),
        "max_posting_age_hours": cfg.get("max_posting_age_hours"),
        "screening_only": True,
        "apply_route": "employer/ATS site — never through the scanner",
        "env": cfg.get("careerops_env"),
        "output": "the scanners append NEW matches to the install's "
                  "data/pipeline.md Pending section; hand each new "
                  "match to stock.py as a screen form (source "
                  "CAREEROPS: company, title, url, location, posted "
                  "date, pay when the ATS API provides it) — code "
                  "screens blacklist, duplication and the Revelio "
                  "gate in that order before anything is opened",
        "instructions": [
            "Run ONLY the scan steps listed, from the install root, "
            "with the env the packet names. The scanners are "
            "script/API-based — no browser, no site sign-in.",
            "Take only the NEW matches this pass added; screening is "
            "code (stock.py), never your judgment.",
            "Return candidates as stock screen forms; return the "
            "pass packet to `spine.py discovery record`.",
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


def _step_names(cfg: dict) -> set:
    return {str(s.get("scanner")) for s in cfg.get("careerops_scanners")
            or []}


def record_pass(state_path, packet: dict, rules: dict,
                now: datetime | None = None,
                answers: dict | None = None) -> dict:
    """Validate and record ONE worker discovery pass. Returns the row.

    Raises ValueError (REFUSED, nothing written) on: unknown or
    non-worker source, missing run_id, a searches_done set that does
    not cover the config matrix exactly (Jobright/Indeed) or a
    steps_done set that does not cover the config scan steps exactly
    (CAREEROPS), bad counts, or a second pass for the same run+source
    (the user's one-pass-per-run rule, in code).
    """
    cfg = effective_cfg(rules, answers)
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
    counts = {}
    if source == "CAREEROPS":
        done = {str(s) for s in packet.get("steps_done") or []}
        want = _step_names(cfg)
        if done != want:
            raise ValueError(
                f"REFUSED — steps_done for {source} must cover the "
                f"config scan steps exactly. Missing: "
                f"{sorted(want - done)}; extra: {sorted(done - want)}.")
        cand = packet.get("candidates")
        if isinstance(cand, list):
            # The CAREEROPS packet may carry the candidates
            # themselves (company, title, url, location, posted
            # date, pay when the ATS feed provides it); the recorded
            # count is the list's length. A malformed entry refuses
            # the whole pass.
            for entry in cand:
                if not isinstance(entry, dict) \
                        or not entry.get("company") \
                        or not entry.get("title") \
                        or not entry.get("url"):
                    raise ValueError(
                        f"REFUSED — each candidate needs company, "
                        f"title and url, got {entry!r}.")
            counts["candidates"] = len(cand)
        elif isinstance(cand, int) and not isinstance(cand, bool) \
                and cand >= 0:
            counts["candidates"] = cand
        else:
            raise ValueError(
                f"REFUSED — candidates must be a list of candidate "
                f"objects or a non-negative int, got {cand!r}.")
    else:
        done = {(str(s.get("title")), str(s.get("location_scope")))
                for s in packet.get("searches_done") or []}
        want = {(str(t), str(l)) for t, l in _matrix_keys(cfg, source)}
        if done != want:
            raise ValueError(
                f"REFUSED — searches_done for {source} must cover the "
                f"config matrix exactly. Missing: {sorted(want - done)}; "
                f"extra: {sorted(done - want)}.")
        value = packet.get("candidates")
        if not isinstance(value, int) or isinstance(value, bool) \
                or value < 0:
            raise ValueError(
                f"REFUSED — candidates must be a non-negative int, "
                f"got {value!r}.")
        counts["candidates"] = value
    value = packet.get("cards_seen")
    if not isinstance(value, int) or isinstance(value, bool) \
            or value < 0:
        raise ValueError(
            f"REFUSED — cards_seen must be a non-negative int, "
            f"got {value!r}.")
    counts["cards_seen"] = value
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
