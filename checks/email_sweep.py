#!/usr/bin/env python3
"""Hourly application-email scan — the bookkeeping half, in code.

Division of labor (the user, Nov 5, 2026): THIS SCRIPT NEVER READS OR JUDGES
EMAIL. Reading an email and judging what it means — which application it
belongs to, whether it moves the user forward, a rejection, a receipt, a
deadline — is Muse's work (language understanding). The script does
everything mechanical around that:

  * builds the watch list (submitted within 90 days + the limbo watch)
    from the outreach log UNION the scan state file's watch bullets;
  * computes the search window — THE PAST HOUR ONLY (the user, Nov 5, 2026:
    never the whole history; the scan runs every 30 minutes, so
    consecutive runs overlap by 30 minutes and two consecutive failed
    runs still leave no gap);
  * searches Gmail and returns the UNRECORDED candidates (sender /
    subject / date pass through untouched — the script interprets none
    of it) plus the watch list, as one JSON work list;
  * takes Muse's judgment for one message as a JSON file and RECORDS
    it: the outreach-log entry and the scan-state bullets in the house
    formats, the dedupe record, and — for forward-moving items — a
    PROGRESS record (held for delivery hours / ready / reported) that
    it keeps updated;
  * for forward-moving items ONLY (the user, Nov 6, 2026): also creates a
    TO-DO entry in the sidecar (status open, deduped by gmail_id).
    The scan agent turns that entry into a Google Tasks to-do in
    the user's "My Tasks" list; the daily 10:00 AM CT reminder lists every
    still-open to-do. A to-do stays open until --complete-todo marks
    it completed — delivery/reporting does NOT close it;
  * builds and maintains THE TRACK FILE (the user, Nov 6, 2026: "The code
    build a file to keep track of important info"):
    state/forward_todos.json, rebuilt on EVERY sidecar save from the
    to-do records — every forward item's important info in one file
    (company, role, subtype, gist, deadline, proposed times, status,
    Gmail ID, Google Tasks ID), split open / completed, open items
    sorted by deadline. --list-todos and the 10 AM reminder read
    their list from this same record;
  * on --complete, advances the scan watermark to the run's start time
    and writes the run's summary entry. A run that never completes
    never advances the watermark, so its unrecorded candidates are
    listed again next run (dedupe protects the recorded ones).

Commands:
  email_sweep.py --tz <zone> [--dry-run]
      Print the work list JSON. A real run also stages the run in the
      sidecar (pending watermark + fresh run stats).
  email_sweep.py record <judgment.json> --tz <zone>
      Record ONE judgment. Judgment fields: gmail_id, kind (forward |
      rejection | confirmation | limbo_confirmation | process |
      out_of_scope), item_id (or company), gist, sender, subject,
      date_iso, subtype (forward: interview request / next step /
      offer), deadline_iso, proposed_times. Returns JSON with
      deliver_now for forward items (delivery hours 8 AM–10 PM in the
      --tz zone, or a deadline within 24 hours).
  email_sweep.py --complete --tz <zone>
      Finish the staged run: summary log entry + watermark advance.
  email_sweep.py --mark-delivered <gmail_id>
      Move a forward item's progress to "reported to the user".
  email_sweep.py --dismiss <gmail_id>
      Mark a message out of scope forever (same as an out_of_scope
      record, for use outside a run).
  email_sweep.py --list-todos
      Print the open forward-move to-dos as JSON (for the 10 AM CT
      reminder and for the scan agent's Google Tasks sync).
  email_sweep.py --complete-todo <gmail_id>
      Mark that gmail_id's to-do completed (the user confirmed it done).
  email_sweep.py add-todo <todo.json>
      Backfill/manual: add one to-do for an already-recorded forward
      item. Fields: gmail_id, item_id, company, role, subtype, gist,
      deadline_iso, proposed_times. Deduped by gmail_id.

The script never sends mail, never clicks links, never replies, and
never writes program/events.jsonl (a limbo verification recorded here
is prose-only; the nightly audit reconciles it, as with all carried
pre-go-live items).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent.parent
GOAL = BASE.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))
import log_writer  # noqa: E402
import state as state_mod  # noqa: E402

LOG_PATH = GOAL / "hidden_files" / "outreach-log.md"
SCAN_STATE_PATH = GOAL / "hidden_files" / "application-email-scan-state.md"
SIDECAR_PATH = BASE / "state" / "email_sweep.json"
GMAIL_CLI = "/opt/hatch/bin/hatch_gws_cli"
CT = ZoneInfo("America/Chicago")

PRUNE_DAYS = 90
WINDOW = timedelta(hours=1)
DELIVERY_START_HOUR = 8
DELIVERY_END_HOUR = 22
DEADLINE_CRITICAL = timedelta(hours=24)

ATS_SENDERS = (
    "ashbyhq.com", "us.greenhouse-mail.io", "myworkday.com",
    "hire.lever.co", "appreview.gem.com", "brassring.com",
    "clinchtalent.com", "recruiting.facebook.com", "smartrecruiters.com",
    "workable.com",
)

_ABBR_TZ = {
    "HST": "Pacific/Honolulu", "HDT": "Pacific/Honolulu",
    "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles",
    "MST": "America/Denver", "MDT": "America/Denver",
    "CST": "America/Chicago", "CDT": "America/Chicago",
    "EST": "America/New_York", "EDT": "America/New_York",
    "UTC": "UTC", "GMT": "UTC",
}

KINDS = ("forward", "rejection", "confirmation", "limbo_confirmation",
         "process", "out_of_scope")


# ------------------------------------------------------------- Gmail (search only)

def gmail_search(query: str, max_results: int) -> list[dict]:
    """Triage-level search: IDs + sender/subject/date, passed through
    untouched. The script never reads a message body. Transient Gmail
    failures (a 400 'Precondition check failed' under parallel load, an
    empty reply) are retried with backoff — one blip must not fail the
    whole hourly run."""
    import time
    last_error = "no attempt made"
    for attempt, wait in enumerate((0, 5, 15)):
        if wait:
            time.sleep(wait)
        proc = subprocess.run(
            [GMAIL_CLI, "gmail", "+triage", "--query", query,
             "--max", str(max_results), "--format", "json"],
            capture_output=True, text=True, timeout=120)
        if "connector_rate_limited" in (proc.stderr or ""):
            # Quota is a hard stop, not a blip: retrying only burns
            # more of it. Fail at once; the next scheduled run retries.
            raise RuntimeError(
                f"gmail rate limited ({query!r}) — attempt stopped, "
                f"no retries against a quota error")
        if proc.returncode == 0:
            if not proc.stdout.strip():
                return []  # zero hits: the CLI prints nothing at all
            try:
                return json.loads(proc.stdout).get("messages", [])
            except json.JSONDecodeError:
                last_error = "gmail returned unparseable output"
                continue
        last_error = (proc.stderr or "").strip()[:200] or \
            f"exit {proc.returncode}"
    raise RuntimeError(f"gmail search failed ({query!r}): {last_error}")


# --------------------------------------------------------- scan state parsing

_ID_BULLET_RE = re.compile(r"^\s+- ([0-9a-f]{16})\b")
_LAST_SCAN_RE = re.compile(
    r"^- Last scan: (\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}) ([A-Z]{2,5})\b")


def parse_scan_state(text: str) -> dict:
    ids: set[str] = set()
    last_scan = None
    for line in text.splitlines():
        m = _ID_BULLET_RE.match(line)
        if m:
            ids.add(m.group(1))
        m = _LAST_SCAN_RE.match(line)
        if m and last_scan is None:
            last_scan = (int(m.group(1)), int(m.group(2)), int(m.group(3)),
                         int(m.group(4)), int(m.group(5)), m.group(6))
    return {"ids": ids, "last_scan": last_scan}


# ------------------------------------------------------------- watch list

class WatchEntry:
    """One watched application: company + role, from the log parse or
    from a watch-list bullet in the scan state file."""
    def __init__(self, company: str, role: str, item_id=None,
                 submitted_str: str = "", limbo: bool = False,
                 item=None):
        self.company = company
        self.role = role
        self.id = item_id
        self.submitted_str = submitted_str
        self.limbo = limbo
        self.item = item

    def as_dict(self) -> dict:
        return {"item_id": self.id, "company": self.company,
                "role": self.role, "submitted": self.submitted_str,
                "limbo": self.limbo}


_PROSE_COMPANY_MARKERS = ("likely", "presumed", "listings", "duplicates",
                          "to be confirmed", "treat as")


def _plausible_company(name: str) -> bool:
    """Reject parser artifacts: summary segments can mine a sentence
    fragment as a 'company' (e.g. 'Atlassian Sr MLE listings are likely
    same req'). A real company name is short and contains no prose."""
    if not name or len(name.split()) > 5:
        return False
    low = name.lower()
    return not any(m in low for m in _PROSE_COMPANY_MARKERS)


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower())
            if len(t) > 2}


_WATCH_BULLET_RE = re.compile(
    r"^  - (?P<company>.+?) — (?P<role>.+?) — submitted "
    r"(?P<date>[A-Z][a-z]+ \d{1,2}, \d{4})")
_BULLET_ID_RE = re.compile(r"#(\d{2,3})\b")


def parse_watch_bullets(state_text: str) -> list[WatchEntry]:
    """The state file's watch-list bullets — the agent-maintained half of
    the watch list (it enumerates submissions the log parser does not
    mine as item events, e.g. one-offs)."""
    out = []
    in_section = False
    for line in state_text.splitlines():
        if line.startswith("- Watch list at scan time"):
            in_section = True
            continue
        if in_section and line.startswith("- ") and \
                not line.startswith("  - "):
            break
        if in_section:
            m = _WATCH_BULLET_RE.match(line)
            if m and _plausible_company(m.group("company")):
                idm = _BULLET_ID_RE.search(line)
                out.append(WatchEntry(
                    m.group("company").strip(), m.group("role").strip(),
                    int(idm.group(1)) if idm else None,
                    submitted_str=m.group("date")))
    return out


_SEGSTATE_RE = re.compile(
    r"SEGMENT STATE — gate-passed — #(\d+) \((.*?); figure")
_PREP_COMMA_RE = re.compile(
    r"PREP READY(?: —)? #(\d+)(?: —)? ([^,—:]+), ([^—:\n]+?)(?::| —)")


def _segment_fallbacks(raw_text: str) -> dict:
    """Item id -> (company, role) mined from SEGMENT STATE / PREP
    READY lines. Some runs write sparse segments whose SUBMITTED lines
    carry no company/role ('#367 ,  (Dayforce ...)'), leaving the log
    parser's item record blank; the company/role are stated verbatim
    in these prep lines. Gap-filler only — parsed values always win."""
    out: dict[int, list] = {}
    for m in _SEGSTATE_RE.finditer(raw_text or ""):
        out.setdefault(int(m.group(1)), [m.group(2).strip(), None])
    for m in _PREP_COMMA_RE.finditer(raw_text or ""):
        slot = out.setdefault(int(m.group(1)), [None, None])
        if not slot[0]:
            slot[0] = m.group(2).strip()
        if not slot[1]:
            slot[1] = m.group(3).strip()
    return out


def build_watch_list(log_state, now: datetime,
                     state_text: str = "",
                     raw_text: str = "") -> tuple[list, list]:
    """(submitted, limbo) WatchEntries. Sources, merged: the log parse
    (items with a submitted event inside the 90-day prune) and the state
    file's watch bullets. Limbo: an item with a limbo event and NO
    submitted event anywhere (attempted, never confirmed — #180 Fetch;
    items like #136 Zoom carry a later limbo bookkeeping line AFTER
    their submission and are watched as submitted, not limbo)."""
    submitted: list[WatchEntry] = []
    limbo: list[WatchEntry] = []
    fallbacks = _segment_fallbacks(raw_text)
    cutoff = now - timedelta(days=PRUNE_DAYS)
    for it in log_state.items.values():
        if not _plausible_company(it.company):
            fb = fallbacks.get(it.id)
            if fb and fb[0] and _plausible_company(fb[0]):
                it.company = fb[0]
                if not it.role and fb[1]:
                    it.role = fb[1]
            else:
                continue
        kinds = [e[2] for e in it.events]
        if "limbo" in kinds and "submitted" not in kinds:
            limbo.append(WatchEntry(it.company, it.role, it.id,
                                    limbo=True, item=it))
            continue
        ev = it.submitted_event
        if ev and ev[1] is not None and ev[1] >= cutoff:
            submitted.append(WatchEntry(
                it.company, it.role, it.id,
                submitted_str=f"{ev[1].strftime('%b')} {ev[1].day}, "
                              f"{ev[1].year}", item=it))
    covered = {(state_mod.normalize_company(e.company),
                frozenset(_tokens(e.role))) for e in submitted}
    covered_ids = {e.id for e in submitted if e.id}
    for b in parse_watch_bullets(state_text):
        if b.id and b.id in covered_ids:
            continue  # same application, already carried from the log
        key = (state_mod.normalize_company(b.company),
               frozenset(_tokens(b.role)))
        if any(c == key[0] and len(key[1] & r) >= max(1, len(key[1]) // 2)
               for c, r in covered):
            continue
        submitted.append(b)
        covered.add(key)
        if b.id:
            covered_ids.add(b.id)
    submitted.sort(key=lambda e: (e.company.lower(), e.role.lower()))
    limbo.sort(key=lambda e: e.id or 0)
    return submitted, limbo


# ---------------------------------------------------------------- sidecar

def _load_sidecar() -> dict:
    try:
        data = json.loads(SIDECAR_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("held", [])
    data.setdefault("delivered", [])
    data.setdefault("dismissed", [])
    data.setdefault("todos", [])
    data.setdefault("pending_run", None)
    data.setdefault("run_stats", None)
    return data


def open_todos(side: dict | None = None) -> list[dict]:
    """Still-open forward-move to-dos (the user, Nov 6, 2026). Data only:
    a to-do is open exactly when its status field is "open"."""
    side = side if side is not None else _load_sidecar()
    return [t for t in side.get("todos", []) if t.get("status") == "open"]


def add_todo(todo: dict, now: datetime | None = None) -> dict:
    """Add one forward-move to-do, deduped by gmail_id. Used by
    record() for new forward items and by the add-todo command for
    backfilling already-recorded ones. Refuses a bad gmail_id."""
    mid = todo.get("gmail_id") or ""
    if not re.fullmatch(r"[0-9a-f]{16}", mid):
        raise ValueError(f"bad gmail_id: {mid!r}")
    side = _load_sidecar()
    for t in side["todos"]:
        if t.get("gmail_id") == mid:
            return {"added": False, "todo": t,
                    "open_todos": len(open_todos(side))}
    entry = {"gmail_id": mid, "item_id": todo.get("item_id"),
             "company": todo.get("company") or "",
             "role": todo.get("role") or "",
             "subtype": todo.get("subtype") or "next step",
             "gist": todo.get("gist") or "",
             "deadline_iso": todo.get("deadline_iso"),
             "proposed_times": todo.get("proposed_times"),
             "status": "open",
             "created_at": (now or datetime.now(CT)).isoformat(),
             "google_task_id": todo.get("google_task_id")}
    side["todos"].append(entry)
    _save_sidecar(side)
    return {"added": True, "todo": entry,
            "open_todos": len(open_todos(side))}


def todos_file_path() -> Path:
    """The track file lives beside the sidecar, so tests that point
    the sidecar at a temp dir get their own track file too."""
    return SIDECAR_PATH.parent / "forward_todos.json"


def _write_todos_file(data: dict) -> None:
    """Rebuild state/forward_todos.json from the to-do records —
    called on every sidecar save, so the file can never drift from
    the record. Open items sort by deadline (earliest first, no
    deadline last), then by creation time."""
    todos = list(data.get("todos", []))
    opens = sorted(
        (t for t in todos if t.get("status") == "open"),
        key=lambda t: (t.get("deadline_iso") is None,
                       t.get("deadline_iso") or "",
                       t.get("created_at") or ""))
    done = [t for t in todos if t.get("status") != "open"]
    payload = {"updated_at": datetime.now(CT).isoformat(),
               "open_count": len(opens), "completed_count": len(done),
               "open": opens, "completed": done}
    path = todos_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def _save_sidecar(data: dict) -> None:
    SIDECAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    SIDECAR_PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")
    _write_todos_file(data)


def _fresh_stats() -> dict:
    stats = {k: 0 for k in KINDS}
    stats["ids"] = []
    return stats


# -------------------------------------------------------------- formatting

def fmt_report_ts(dt: datetime) -> str:
    return (f"{dt.strftime('%I:%M %p %Z').lstrip('0')}, "
            f"{dt.strftime('%a %b')} {dt.day}, {dt.year}")


def fmt_msg_date(raw: str, tz: ZoneInfo) -> str:
    """Render a message date (ISO or RFC 2822) in the report zone."""
    dt = None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        pass
    if dt is None:
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%d %b %Y %H:%M:%S %z"):
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except (ValueError, TypeError):
                continue
    if dt is None:
        return raw or "date unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    dt = dt.astimezone(tz)
    return (f"{dt.strftime('%b')} {dt.day}, {dt.year}, "
            f"{dt.strftime('%I:%M %p %Z').lstrip('0')}")


def _submitted_date(entry) -> str:
    return entry.submitted_str or "date in log"


def _id_label(entry) -> str:
    return f"#{entry.id}" if entry.id else "(watch-list entry)"


def _section_insert(lines: list[str], header_prefix: str,
                    bullets: list[str]) -> list[str]:
    """Insert bullets at the END of the bullet run under a header line."""
    if not bullets:
        return lines
    for i, line in enumerate(lines):
        if line.startswith(header_prefix):
            j = i + 1
            while j < len(lines) and lines[j].startswith("  - "):
                j += 1
            return lines[:j] + bullets + lines[j:]
    return lines + bullets


# ------------------------------------------------------------ work list

def work_list(report_tz: ZoneInfo, dry_run: bool = False,
              now: datetime | None = None) -> dict:
    """The staged run: watch list + unrecorded candidates, as JSON.
    Candidates carry triage metadata ONLY (id/from/subject/date as
    Gmail returned them) — reading and judging them is Muse's work."""
    now = now or datetime.now(report_tz)
    now_ct = now.astimezone(CT)
    log_state = state_mod.parse_log(str(LOG_PATH))
    state_text = (SCAN_STATE_PATH.read_text(encoding="utf-8")
                  if SCAN_STATE_PATH.exists() else "")
    raw_text = (LOG_PATH.read_text(encoding="utf-8")
                if LOG_PATH.exists() else "")
    submitted, limbo = build_watch_list(log_state, now_ct, state_text,
                                        raw_text)
    parsed = parse_scan_state(state_text)
    side = _load_sidecar()
    dedupe = parsed["ids"] | set(side["dismissed"])

    # Past hour only (the user, Nov 5, 2026). The epoch form of after: is
    # honored by the Gmail API at second precision — the day form
    # would return (and bill for) the whole day's mail.
    window_start = now - WINDOW
    after = str(int(window_start.timestamp()))

    queries = [
        (f"after:{after}", 300),
        ("from:(" + " OR ".join(ATS_SENDERS) + f") after:{after}", 200),
        (f'(interview OR "next steps" OR "phone screen" OR assessment OR '
         f'"schedule a call" OR "schedule a chat" OR "offer letter") '
         f"after:{after}", 200),
    ]
    for e in limbo:
        queries.append((f'"{e.company}" after:{after}', 25))

    candidates: list[dict] = []
    seen: set[str] = set()
    for query, cap in queries:
        for msg in gmail_search(query, cap):
            mid = msg.get("id")
            if mid and mid not in dedupe and mid not in seen:
                seen.add(mid)
                candidates.append({"gmail_id": mid,
                                   "from": msg.get("from", ""),
                                   "subject": msg.get("subject", ""),
                                   "date": msg.get("date", "")})

    # held forward items come due in delivery hours
    held_due = []
    if DELIVERY_START_HOUR <= now.hour < DELIVERY_END_HOUR:
        held_due = list(side["held"])

    if not dry_run:
        side["pending_run"] = {"started_at": now.isoformat(),
                               "tz": str(report_tz)}
        side["run_stats"] = _fresh_stats()
        _save_sidecar(side)

    return {"ran_at": fmt_report_ts(now), "window_after": after,
            "watch_submitted": len(submitted),
            "watch_limbo": [e.id for e in limbo],
            "watch": [e.as_dict() for e in submitted + limbo],
            "candidates": candidates,
            "held_due": held_due,
            "open_todos": open_todos(side),
            "forward_progress": {"held": len(side["held"]),
                                 "delivered_total": len(side["delivered"]),
                                 "todos_open": len(open_todos(side))},
            "dry_run": dry_run}


# ---------------------------------------------------------------- record

def _resolve_entry(judgment: dict, watched: list) -> WatchEntry | None:
    """Resolve a judgment to a watch entry — by item_id, or by company
    name matched against the WATCH LIST (log data, not email)."""
    iid = judgment.get("item_id")
    if iid:
        for e in watched:
            if e.id == iid:
                return e
        return None
    company = judgment.get("company") or ""
    norm = state_mod.normalize_company(company)
    for e in watched:
        if state_mod.normalize_company(e.company) == norm:
            return e
    return None


def _landing_check(kind: str, mid: str) -> tuple[bool, dict, list[str]]:
    """THE HANDOFF CHECK for one recorded judgment (the user, Nov 5, 2026):
    re-read the scan state, the outreach log, and the sweep state
    fresh, and confirm this message's records actually landed — the
    id in the scan state (and the dismissal list for out-of-scope),
    plus the log entry for the kinds that write one."""
    state_text = (SCAN_STATE_PATH.read_text(encoding="utf-8")
                  if SCAN_STATE_PATH.exists() else "")
    log_text = (LOG_PATH.read_text(encoding="utf-8")
                if LOG_PATH.exists() else "")
    needs_log = kind in ("forward", "rejection", "limbo_confirmation")
    landed = {"scan_state": mid in state_text,
              "log_entry": (f"(Gmail {mid})" in log_text)
              if needs_log else None}
    problems: list[str] = []
    if kind == "out_of_scope":
        landed["dismissed"] = mid in _load_sidecar()["dismissed"]
        if not landed["dismissed"]:
            problems.append("the dismissal did not land in the sweep "
                            "state on read-back")
    else:
        if not landed["scan_state"]:
            problems.append("the message id is not in the scan state "
                            "on read-back")
        if needs_log and not landed["log_entry"]:
            problems.append("the log entry is not in the outreach "
                            "log on read-back")
    return not problems, landed, problems


def record(judgment: dict, report_tz: ZoneInfo,
           now: datetime | None = None) -> dict:
    """Record ONE judgment from Claude. Writes the outreach-log entry
    and/or scan-state bullets in the house formats, updates dedupe and
    the forward-progress record, and returns the delivery decision for
    forward items. Refuses (ValueError) a malformed or duplicate
    judgment — nothing is written on a refusal."""
    now = now or datetime.now(report_tz)
    mid = judgment.get("gmail_id") or ""
    kind = judgment.get("kind") or ""
    if not re.fullmatch(r"[0-9a-f]{16}", mid):
        raise ValueError(f"bad gmail_id: {mid!r}")
    if kind not in KINDS:
        raise ValueError(f"bad kind: {kind!r}")

    state_text = (SCAN_STATE_PATH.read_text(encoding="utf-8")
                  if SCAN_STATE_PATH.exists() else "")
    side = _load_sidecar()
    already = parse_scan_state(state_text)["ids"] \
        | set(side["dismissed"]) \
        | set((side["run_stats"] or {}).get("ids", [])) \
        | {p["gmail_id"] for p in side["held"]} \
        | {p["gmail_id"] for p in side["delivered"]}
    if mid in already:
        raise ValueError(f"message {mid} is already recorded")

    gist = (judgment.get("gist") or "").strip()
    sender = judgment.get("sender") or ""
    subject = judgment.get("subject") or ""
    date_str = fmt_msg_date(judgment.get("date_iso") or "", report_tz)
    run_date = f"{now.strftime('%b')} {now.day}, {now.year}"
    credit = ("read and judged by Muse in the application-email "
              "scan; recorded by email_sweep.py")

    if kind == "out_of_scope":
        side["dismissed"].append(mid)
        _bump_stats(side, kind, mid)
        _save_sidecar(side)
        ok, landed, problems = _landing_check(kind, mid)
        out = {"recorded": True, "kind": kind, "gmail_id": mid,
               "deliver_now": False,
               "understood": {"gmail_id": mid, "kind": kind},
               "landed": landed, "verified": ok}
        if problems:
            out["problems"] = problems
        return out

    log_state = state_mod.parse_log(str(LOG_PATH))
    raw_text = (LOG_PATH.read_text(encoding="utf-8")
                if LOG_PATH.exists() else "")
    submitted, limbo = build_watch_list(
        log_state, now.astimezone(CT), state_text, raw_text)
    watched = submitted + limbo
    entry_ref = _resolve_entry(judgment, watched)
    if entry_ref is None:
        raise ValueError(
            f"judgment names no watched application "
            f"(item_id={judgment.get('item_id')!r}, "
            f"company={judgment.get('company')!r})")
    company = entry_ref.company
    # Muse may name the role the EMAIL ties to when it differs from
    # the logged role; the record keeps both straight.
    role = judgment.get("role") or entry_ref.role
    role_note = ""
    if judgment.get("role") and judgment["role"] != entry_ref.role:
        role_note = (f" (the email ties to '{judgment['role']}'; the "
                     f"logged application is '{entry_ref.role}')")
    reported_bullets: list[str] = []
    reviewed_bullets: list[str] = []
    watch_bullets: list[str] = []
    result: dict = {"recorded": True, "kind": kind, "gmail_id": mid,
                    "company": company, "role": role,
                    "deliver_now": False}

    if kind == "rejection":
        entry = (
            f"APPLICATION FOLLOW-UP — {company}, {role}{role_note} "
            f"(submitted {_submitted_date(entry_ref)}) — REJECTION "
            f"(record-only; not reported to the user in chat per her Nov 2, "
            f"2026 rule): email from {sender}, {date_str}, "
            f"\"{subject}\" (Gmail {mid}), {credit} — {gist}; no "
            f"deadline or proposed times.")
        log_writer.append_entry(str(LOG_PATH), entry)
        reported_bullets.append(
            f"  - {mid} — {sender}, {date_str} — \"{subject}\" "
            f"({company} — {role} — REJECTION / decision: {credit} — "
            f"{gist}; RECORD-ONLY under the user's Nov 2, 2026 "
            f"forward-movement-only rule — logged in the outreach log, "
            f"NOT reported to the user in chat)")
    elif kind == "forward":
        subtype = judgment.get("subtype") or "next step"
        deadline_iso = judgment.get("deadline_iso")
        critical = False
        if deadline_iso:
            try:
                dl = datetime.fromisoformat(
                    deadline_iso.replace("Z", "+00:00"))
                if dl.tzinfo is None:
                    dl = dl.replace(tzinfo=report_tz)
                critical = timedelta(0) <= dl - now <= DEADLINE_CRITICAL
            except ValueError:
                critical = False
        in_hours = DELIVERY_START_HOUR <= now.hour < DELIVERY_END_HOUR
        deliver_now = in_hours or critical
        proposed = judgment.get("proposed_times")
        entry = (
            f"APPLICATION FOLLOW-UP — {company}, {role}{role_note} "
            f"(submitted {_submitted_date(entry_ref)}) — FORWARD-MOVING "
            f"({subtype}): email from {sender}, {date_str}, "
            f"\"{subject}\" (Gmail {mid}), {credit} — {gist}."
            + (f" Proposed times: {proposed}." if proposed else "")
            + (f" Deadline: {deadline_iso} (inside 24 hours)."
               if critical else ""))
        log_writer.append_entry(str(LOG_PATH), entry)
        note = ("reported to the user in chat in this run" if deliver_now else
                "chat report HELD under delivery quiet hours; delivered "
                "at the next in-hours run")
        reported_bullets.append(
            f"  - {mid} — {sender}, {date_str} — \"{subject}\" "
            f"({company} — {role} — {subtype}, FORWARD-MOVING: {credit} "
            f"— {gist}; {note}. No reply sent, no link clicked, nothing "
            f"booked)")
        progress = {"gmail_id": mid, "item_id": entry_ref.id,
                    "company": company, "role": role, "subtype": subtype,
                    "from": sender, "date": date_str, "subject": subject,
                    "gist": gist, "deadline_iso": deadline_iso,
                    "proposed_times": proposed,
                    "status": "ready" if deliver_now else "held",
                    "recorded_at": now.isoformat()}
        if not deliver_now:
            side["held"].append(progress)
        # TO-DO (the user, Nov 6, 2026): every forward item gets an open
        # to-do, deduped by gmail_id. It stays open past delivery —
        # only --complete-todo closes it.
        todo = {"gmail_id": mid, "item_id": entry_ref.id,
                "company": company, "role": role, "subtype": subtype,
                "gist": gist, "deadline_iso": deadline_iso,
                "proposed_times": proposed, "status": "open",
                "created_at": now.isoformat(), "google_task_id": None}
        if not any(t.get("gmail_id") == mid for t in side["todos"]):
            side["todos"].append(todo)
        result["deliver_now"] = deliver_now
        result["deadline_critical"] = critical
        result["delivery"] = progress
        result["todo"] = todo
    elif kind == "limbo_confirmation":
        entry = (
            f"APPLICATION FOLLOW-UP — {company}, {role} — LIMBO "
            f"VERIFICATION (record-only; not reported to the user in chat): "
            f"submission-confirmation email from {sender}, {date_str}, "
            f"\"{subject}\" (Gmail {mid}), {credit} — item "
            f"{_id_label(entry_ref)} is SUBMITTED (verified by email) "
            f"and moves from the limbo watch to the submitted watch "
            f"list. Do not re-apply.")
        log_writer.append_entry(str(LOG_PATH), entry)
        reviewed_bullets.append(
            f"  - {mid} — {sender}, {date_str} — \"{subject}\" "
            f"({company} {_id_label(entry_ref)} {role} confirmation "
            f"receipt; {credit} — EMAIL-VERIFYING the "
            f"{_id_label(entry_ref)} limbo submission and closing its "
            f"limbo watch; record-only, never chat-reported)")
        watch_bullets.append(
            f"  - {company} — {role} — verified by email in the "
            f"{run_date} run (email_sweep.py): confirmation from "
            f"{sender}, {date_str}, Gmail ID {mid}, read in full by "
            f"Muse — moved from the limbo watch to this submitted "
            f"watch list")
        result["limbo_item"] = entry_ref.id
    elif kind == "confirmation":
        reviewed_bullets.append(
            f"  - {mid} — {sender}, {date_str} — \"{subject}\" "
            f"({company} {_id_label(entry_ref)} {role} confirmation "
            f"receipt; {credit} — {gist}; EMAIL-VERIFYING the "
            f"{_id_label(entry_ref)} submission; no "
            f"interview/next-step/decision in this mail)")
    elif kind == "process":
        reviewed_bullets.append(
            f"  - {mid} — {sender}, {date_str} — \"{subject}\" "
            f"({company} — submission-process mail; {credit}; no code "
            f"value read or stored; out of scope)")

    if reported_bullets or reviewed_bullets or watch_bullets:
        lines = state_text.splitlines()
        lines = _section_insert(lines, "- Reported message IDs:",
                                reported_bullets)
        lines = _section_insert(lines, "- Reviewed but OUT OF SCOPE",
                                reviewed_bullets)
        if watch_bullets:
            for i, line in enumerate(lines):
                if line.startswith("- Limbo watch"):
                    lines = lines[:i] + watch_bullets + lines[i:]
                    break
        SCAN_STATE_PATH.write_text("\n".join(lines) + "\n",
                                   encoding="utf-8")
    _bump_stats(side, kind, mid)
    _save_sidecar(side)
    # THE HANDOFF CHECK (the user, Nov 5, 2026): echo the judgment as
    # understood (with the application the program resolved it to)
    # and prove the records landed, by reading them back fresh.
    ok, landed, problems = _landing_check(kind, mid)
    result["understood"] = {"gmail_id": mid, "kind": kind,
                            "item_id": entry_ref.id, "company": company,
                            "role": role, "gist": gist}
    result["landed"] = landed
    result["verified"] = ok
    if problems:
        result["problems"] = problems
    return result


def _bump_stats(side: dict, kind: str, mid: str) -> None:
    if side.get("run_stats") is None:
        side["run_stats"] = _fresh_stats()
    side["run_stats"][kind] = side["run_stats"].get(kind, 0) + 1
    side["run_stats"].setdefault("ids", []).append(mid)


# --------------------------------------------------------------- complete

def complete(report_tz: ZoneInfo, now: datetime | None = None) -> dict:
    """Finish the staged run: summary log entry + watermark advance.
    The watermark moves to the RUN'S START time (staged by the work
    list), never to now — mail that arrived during the run stays inside
    the next run's overlap window."""
    now = now or datetime.now(report_tz)
    side = _load_sidecar()
    pending = side.get("pending_run")
    if not pending:
        raise ValueError("no staged run to complete (run the work list "
                         "first)")
    started = datetime.fromisoformat(pending["started_at"])
    stats = side.get("run_stats") or _fresh_stats()
    state_text = (SCAN_STATE_PATH.read_text(encoding="utf-8")
                  if SCAN_STATE_PATH.exists() else "")
    log_state = state_mod.parse_log(str(LOG_PATH))
    raw_text = (LOG_PATH.read_text(encoding="utf-8")
                if LOG_PATH.exists() else "")
    submitted, limbo = build_watch_list(
        log_state, now.astimezone(CT), state_text, raw_text)
    limbo_desc = (f"{len(limbo)} item(s): " +
                  ", ".join(f"#{e.id} {e.company}" for e in limbo)
                  if limbo else "empty")
    parts = []
    if stats.get("forward"):
        parts.append(f"{stats['forward']} forward-moving")
    if stats.get("rejection"):
        parts.append(f"{stats['rejection']} rejection(s)")
    if stats.get("confirmation"):
        parts.append(f"{stats['confirmation']} receipt(s)")
    if stats.get("limbo_confirmation"):
        parts.append(f"{stats['limbo_confirmation']} limbo "
                     f"verification(s)")
    if stats.get("process"):
        parts.append(f"{stats['process']} process")
    if stats.get("out_of_scope"):
        parts.append(f"{stats['out_of_scope']} out of scope")
    outcome = "; ".join(parts) if parts else "no new application mail"
    summary = (
        f"APPLICATION EMAIL SCAN (email_sweep.py) — Muse read "
        f"and judged the new mail; the script recorded it. Outcome: "
        f"{outcome}. Watch list now {len(submitted)} SUBMITTED "
        f"applications; limbo watch: {limbo_desc}. No reply sent, "
        f"nothing booked.")
    log_writer.append_entry(str(LOG_PATH), summary)

    s = started.astimezone(report_tz)
    last_line = (
        f"- Last scan: {s:%Y-%m-%d %H:%M} {s:%Z} ({report_tz}) — scan "
        f"run (email_sweep.py work list; judged by Muse, recorded by "
        f"the script); searched the past hour only, deduped by "
        f"message IDs below. Outcome: "
        f"{outcome}. Watch list: {len(submitted)} SUBMITTED "
        f"applications; limbo watch: {limbo_desc}.")
    lines = state_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("- Last scan:"):
            lines[i] = last_line
            break
    else:
        lines.insert(0, last_line)
    SCAN_STATE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    side["pending_run"] = None
    side["run_stats"] = None
    _save_sidecar(side)
    return {"completed": True, "outcome": outcome,
            "watch_submitted": len(submitted),
            "watch_limbo": [e.id for e in limbo]}


# ------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tz", default="America/Chicago",
                    help="report timezone (the user's current zone)")
    ap.add_argument("--dry-run", action="store_true",
                    help="work list only; stage nothing")
    ap.add_argument("--complete", action="store_true",
                    help="finish the staged run (summary + watermark)")
    ap.add_argument("--mark-delivered", metavar="GMAIL_ID",
                    help="move a forward item's progress to reported")
    ap.add_argument("--dismiss", metavar="GMAIL_ID",
                    help="mark a message out of scope forever")
    ap.add_argument("--list-todos", action="store_true",
                    help="print the open forward-move to-dos")
    ap.add_argument("--rebuild-todos-file", action="store_true",
                    help="rebuild state/forward_todos.json from the "
                         "sidecar record and print its path + counts")
    ap.add_argument("--complete-todo", metavar="GMAIL_ID",
                    help="mark that to-do completed")
    ap.add_argument("--set-todo-task", nargs=2,
                    metavar=("GMAIL_ID", "TASK_ID"),
                    help="store the Google Tasks id on a to-do")
    ap.add_argument("command", nargs="?", choices=["record", "add-todo"],
                    help="'record' reads a judgment JSON file; "
                         "'add-todo' reads a to-do JSON file")
    ap.add_argument("judgment_file", nargs="?",
                    help="judgment JSON file (for record)")
    args = ap.parse_args()
    tz = ZoneInfo(args.tz)

    try:
        if args.mark_delivered:
            side = _load_sidecar()
            moved = None
            for p in list(side["held"]):
                if p.get("gmail_id") == args.mark_delivered:
                    side["held"].remove(p)
                    p["status"] = "reported"
                    p["delivered_at"] = datetime.now(tz).isoformat()
                    side["delivered"].append(p)
                    moved = p
                    break
            if moved is None:  # delivered straight from a ready record
                moved = {"gmail_id": args.mark_delivered,
                         "status": "reported",
                         "delivered_at": datetime.now(tz).isoformat()}
                side["delivered"].append(moved)
            side["delivered"] = side["delivered"][-50:]
            _save_sidecar(side)
            print(json.dumps({"marked_delivered": args.mark_delivered,
                              "held_remaining": len(side["held"])}))
            return 0
        if args.dismiss:
            side = _load_sidecar()
            if args.dismiss not in side["dismissed"]:
                side["dismissed"].append(args.dismiss)
                _save_sidecar(side)
            print(json.dumps({"dismissed": args.dismiss,
                              "dismissed_total": len(side["dismissed"])}))
            return 0
        if args.list_todos:
            print(json.dumps({"open_todos": open_todos()}, indent=1))
            return 0
        if args.rebuild_todos_file:
            side = _load_sidecar()
            _write_todos_file(side)
            print(json.dumps(
                {"todos_file": str(todos_file_path()),
                 "open_count": len(open_todos(side)),
                 "completed_count": len(
                     [t for t in side["todos"]
                      if t.get("status") != "open"])}))
            return 0
        if args.complete_todo:
            side = _load_sidecar()
            hit = None
            for t in side["todos"]:
                if t.get("gmail_id") == args.complete_todo:
                    t["status"] = "completed"
                    t["completed_at"] = datetime.now(tz).isoformat()
                    hit = t
                    break
            if hit is None:
                print(f"email_sweep: no to-do for {args.complete_todo}",
                      file=sys.stderr)
                return 1
            _save_sidecar(side)
            print(json.dumps({"completed_todo": args.complete_todo,
                              "open_todos": len(open_todos(side))}))
            return 0
        if args.set_todo_task:
            mid, task_id = args.set_todo_task
            side = _load_sidecar()
            hit = None
            for t in side["todos"]:
                if t.get("gmail_id") == mid:
                    t["google_task_id"] = task_id
                    hit = t
                    break
            if hit is None:
                print(f"email_sweep: no to-do for {mid}",
                      file=sys.stderr)
                return 1
            _save_sidecar(side)
            print(json.dumps({"todo_task_set": mid,
                              "google_task_id": task_id}))
            return 0
        if args.command == "add-todo":
            if not args.judgment_file:
                print("add-todo needs a to-do JSON file",
                      file=sys.stderr)
                return 1
            todo = json.loads(
                Path(args.judgment_file).read_text(encoding="utf-8"))
            print(json.dumps(add_todo(todo, now=datetime.now(tz)),
                             indent=1))
            return 0
        if args.command == "record":
            if not args.judgment_file:
                print("record needs a judgment JSON file",
                      file=sys.stderr)
                return 1
            judgment = json.loads(
                Path(args.judgment_file).read_text(encoding="utf-8"))
            print(json.dumps(record(judgment, tz), indent=1))
            return 0
        if args.complete:
            print(json.dumps(complete(tz), indent=1))
            return 0
        print(json.dumps(work_list(tz, dry_run=args.dry_run), indent=1))
        return 0
    except (ValueError, RuntimeError) as exc:
        print(f"email_sweep: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
