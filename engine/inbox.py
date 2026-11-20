#!/usr/bin/env python3
"""Inbox packets, standardized (the user, Nov 12, 2026 — "all of these
should be handled in the code not in the run."): the scope limits,
dedupe, triage, and claim checks for the two LinkedIn inbox jobs are
enforced HERE, as clean packets — the stock.py / gate_intake.py
pattern — never as prose judgment in a cron body.

The two jobs:
  * linkedin-message-email-watch (every 15 min): the user's LinkedIn
    messaging email notifications land in Gmail. The run searches
    Gmail (searching is the run's work — it holds the connector) and
    hands EVERY candidate it found to `watch-intake`. Code enforces
    the past-hour window (rules.yaml inbox.past_hour_window_minutes),
    dedupes by Gmail message ID against the processed set, triages
    out the non-message patterns from config (digests, marketing,
    connection-accepted notices carrying no message — a pass-pattern
    subject like "<First name> just messaged you" is the primary
    genuine-message signal), parses the person's name (full name
    from the sender display, preferred over the subject's first
    name), extracts the conversation URL behind the email's "View
    message" button as thread_url, and returns ONLY the actionable
    notifications as the work packet.
    Every refusal is recorded processed at intake, so it never
    resurfaces; an actionable notification is marked processed only
    by `watch-record`, after the run has handled it.
  * linkedin-inbox-replies (four times daily — 8:30 AM, 12:30 PM,
    4:30 PM, 8:30 PM CT; cadence + window, the user, Nov 16, 2026):
    the LinkedIn inbox check limited to conversations whose latest
    incoming message is within the past 12 hours. `daily-scope`
    computes the cutoff
    (now − rules.yaml inbox.daily_check_window_hours) and the
    stand_down list (threads already claimed in the claims ledger or
    handled by the email watch) in code. Outcomes return through
    `daily-record`.

Claims: `check-claim` answers CLAIMED / CLEAR for a person + message
timestamp against hidden_files/inbox-action-claims.md, and both
record steps append the claim line to that same ledger, in its
existing format ("CLAIM [ts] — [key] — claimed by [job] — status:
..."), before anything else is written. The ledger's key format and
rules (any existing claim owns the action; a DECLINED claim is
terminal) are unchanged — this program is one more writer of the
same ledger, never a second ledger.

Connection invitations by email (the user, Nov 12, 2026 — "Burn this
into code. Just like message reply through email."): the user enabled
LinkedIn email notifications for new connection invitations.
Identification is SENDER-ONLY (the user, Nov 16, 2026 — her verdict
after a real invitation arrived matching neither the Nov 12 sender
nor its subject, and after she configured LinkedIn so the address
sends invitations only): From invitations@linkedin.com, NO subject
condition, ever (rules.yaml inbox.invitation_search) — the same
identification shape as job alerts. `invite-intake` enforces, in
code: the pinned sender (any other From address is refused), the
24-hour window, dedupe against the SAME processed-ID pool in
program/state/inbox.json (Gmail IDs are unique across both flows
— one source of truth), and the group / ad-marketing refusal
patterns. It parses the inviter's
name (full name from the sender display, preferred) and extracts
the Accept button/link href as accept_url — the run clicks THAT
link, which redirects and connects the user to the person, without
browsing LinkedIn's invitations page. `invite-record` marks the
ID processed and, per accepted invitation, appends one outreach-
log line naming the person (standing rule, the user, Oct 30, 2026:
accept invitations from real people; skip ads/marketing; decline
group invitations silently — group invitations are never logged).
No claims-ledger lines are written for invitations: dedupe is
the processed pool plus the log line.

Job alerts (the user, Nov 12, 2026 — a third discovery source, via
email only): the user's saved LinkedIn job alerts send one email per
alert per day from the pinned jobalerts-noreply@linkedin.com.
`jobalert-intake` validates the batch run's sender-only Gmail
finds (from that address, past 12 hours) — identification is
SENDER-ONLY: alert subjects arrive in many formats (built from
the first company on the list, in a shape like "<role> job at
<company> for you", and formats vary), so the subject is never
consulted, and the
sender <-> alerts correspondence is one-to-one and closed (any
email from that address IS one of her alerts; no content
classification, no matching against the alert definitions). The
packet extracts the email's job links + the "See all jobs" URL
and carries the code's fixed runner `instructions`.
`jobalert-record` closes an email after the run has vetted its
jobs (the jobs themselves stock through stock.py as
LINKEDIN_ALERT).

Daily finish (the user, Nov 13, 2026 — "fix these in code"): the daily
job's completion is recorded HERE, not by the run's prose.
`daily-finish` takes the run's counts as data, refuses a summary
that does not account for all three parts of the job
(conversations, invitations, AND job alerts), and writes the
"Daily inbox check" line to the outreach log itself — before it
existed, only handled items ever reached the log, so a clean run
left no trace and the daily watchdog could not tell "ran, found
nothing" from "never ran". The same audit hardened
`jobalert-intake`: a candidate carrying no links and no html was
never read in full, and its extraction silently came back empty —
intake now refuses such a candidate WITHOUT consuming it, so the
run must re-read the email and re-feed it.

Processed-ID state lives in ONE place: program/state/inbox.json,
written only by this program. Consumption in that pool is
stamped PER CONSUMER ("inbox" for the message/invitation flows,
"jobalert" for the alert flow): each flow's dedupe asks only
whether ITS consumer has consumed the ID, and stamps merge, so
the flows cannot starve each other. On first use, if that file does not
exist, it is seeded once from any Gmail IDs listed in
hidden_files/linkedin-message-watch-state.md (the watch's original
hand-kept state file); after that the .md is documentation, not
state.

The program never opens LinkedIn, never searches Gmail, and never
sends anything. It validates, decides scope, and records.

Commands (also wired into spine.py as `spine.py inbox ...`):
  inbox.py format
  inbox.py watch-intake candidates.json [--now ISO]
  inbox.py watch-record results.json
  inbox.py daily-scope [--now ISO]
  inbox.py daily-record results.json
  inbox.py daily-finish summary.json
  inbox.py check-claim --person NAME --message-ts ISO
  inbox.py invite-intake candidates.json [--now ISO]
  inbox.py invite-record results.json
  inbox.py jobalert-intake candidates.json [--now ISO]
  inbox.py jobalert-record results.json
Paths default to the live files; --log / --claims / --state point
every path at throwaway copies (tests, smoke runs).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

BASE = Path(__file__).resolve().parent.parent
GOAL = BASE.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))
sys.path.insert(0, str(BASE / "checks"))
import gate_fallback as gate_fallback_mod  # noqa: E402
import log_writer  # noqa: E402
import state as state_mod  # noqa: E402

CT = state_mod.CT
LOG_PATH = GOAL / "hidden_files" / "outreach-log.md"
CLAIMS_PATH = GOAL / "hidden_files" / "inbox-action-claims.md"
WATCH_MD_PATH = GOAL / "hidden_files" / "linkedin-message-watch-state.md"
STATE_PATH = BASE / "state" / "inbox.json"
RULES_PATH = BASE / "config" / "rules.yaml"
MARKER = "(Recorded by inbox program.)"

WATCH_JOB = "linkedin-message-email-watch"
DAILY_JOB = "linkedin-inbox-replies"
OUTCOMES = ("replied", "no_reply_needed", "wu_decision", "skipped")
_STATUS_BY_OUTCOME = {
    "replied": "SENT",
    "no_reply_needed": "DONE (no reply needed)",
    "wu_decision": "CLAIMED — awaiting the user's decision (no reply sent)",
    "skipped": "DONE (skipped by the run)",
}
_GMAIL_ID_RE = re.compile(r"[0-9a-f]{16}")

FORMAT_TEXT = """\
INBOX PACKETS — inbox.py (spine.py inbox ...) hands the two LinkedIn
inbox jobs their scope as data. The run never decides scope itself.

1) EMAIL WATCH INTAKE — `spine.py inbox watch-intake candidates.json`
The run searches Gmail with the search defined in rules.yaml
inbox.gmail_search (LinkedIn senders + a "messaged you" subject +
the past hour) and hands EVERY candidate to the program as a JSON
list (or {"candidates": [...]}):

[
  {
    "gmail_id": "1a1d07bb001d2370",        // required, the Gmail ID
    "sender": "Jane Doe via LinkedIn <notifications-noreply@linkedin.com>",
                                            // required, as Gmail shows it
    "subject": "Jane Doe sent you a message",
                                            // required, exact subject
    "date": "2026-11-12T14:58:00-06:00",   // required, ISO or RFC 2822
    "snippet": "…",                         // optional
    "body": "…",                            // optional — the message
                                            //   text, when the email
                                            //   carries one
    "links": ["https://…"],                 // optional — the email's
                                            //   links (strings, or
                                            //   {"href": …} objects)
    "html": "<html>…"                       // optional — the email's
                                            //   HTML, when available
  }
]

The real notification format (the user's sample, Nov 12, 2026): sender
"Pruthvi Desai via LinkedIn", subject "Pruthvi just messaged you",
a blue "View message" button in the body. The subject form "<First
name> just messaged you" is a PASS pattern in config — it marks
the email a genuine message notification outright. The person's
FULL name is parsed from the sender display name (preferred over
the subject's first name).

The program enforces, IN CODE: received within the past hour
(rules.yaml inbox.past_hour_window_minutes — older is refused);
not already processed (dedupe by Gmail ID); deterministic triage
against the config patterns (digest/summary subjects, marketing
senders/subjects, and connection-accepted notices that carry NO
message body are refused; a pass-pattern subject wins over every
refusal pattern). Every refused candidate is recorded processed
immediately (it never resurfaces) and printed under "refused" with
its reason. The result's "actionable" list is the whole work
packet — ONLY these, each {gmail_id, person, person_parsed,
received_at, thread_url}: reply to that one person only, opening
"thread_url" (the conversation behind the email's "View message"
button) when it is present; when no such link is in the email,
thread_url is null and a "thread_url_note" says so.

2) EMAIL WATCH RECORD — `spine.py inbox watch-record results.json`
After handling, the run returns one result per actionable item:

[
  {
    "gmail_id": "1a1d07bb001d2370",        // required
    "person": "Jane Doe",                  // required
    "outcome": "replied",                  // replied | no_reply_needed
                                           //   | wu_decision | skipped
    "message_ts": "2026-11-12T14:58:00-06:00",
                                           // the thread message's own
                                           //   time (builds the claim key)
    "first_words": "Hi Alex, Thank you",  // optional — first words of
                                           //   their message (claim key)
    "claim_key": "…"                       // optional — a prebuilt
                                           //   ledger key wins over
                                           //   the fields above
  }
]

The program validates each result, appends the claim to the claims
ledger in its existing format (an already-claimed key is REFUSED —
nothing is written for that entry), marks the Gmail ID processed,
writes the outreach-log skeleton line itself, and prints per-entry
results with "verified" from a read-back of all three records.

3) DAILY CHECK SCOPE — `spine.py inbox daily-scope`
Prints {cutoff, window_hours, stand_down: [{person, claim_key,
status, source}]}: the run works ONLY conversations whose latest
incoming message is at/after "cutoff" (now minus the configured 12
hours) and stands down on every thread in "stand_down" (already
claimed in the ledger, or handled by the email watch).

4) DAILY RECORD — `spine.py inbox daily-record results.json`
Same result shape as watch-record, minus gmail_id (the daily check
works from LinkedIn, not Gmail): {person, outcome, message_ts,
first_words?, claim_key?}. Same claim + log writes; nothing is
marked in the Gmail processed set.

5) CLAIM CHECK — `spine.py inbox check-claim --person "Jane Doe"
--message-ts 2026-11-12T14:58:00-06:00`
Prints {"verdict": "CLAIMED", "matches": [...]} or {"verdict":
"CLEAR"}. Any CLAIMED verdict owns the action — stand down.

6) INVITATION INTAKE — `spine.py inbox invite-intake
candidates.json`
Connection-invitation notifications come ONLY from
invitations@linkedin.com — SENDER-ONLY identification (the user,
Nov 16, 2026: she configured her LinkedIn notifications so that
address sends connection invitations and nothing else; the
subject is never a condition — the current subject is
"I want to connect"). TWO runs feed this ONE intake (cadence,
the user, Nov 16, 2026 — the invitation email sweep runs once
every hour, 24 times a day; the 15-minute message-watch
frequency was excessive and four times a day was not enough):
the HOURLY invitation sweep (linkedin-invitation-sweep,
rules.yaml inbox.invitation_hourly_search) searches the past
2 hours, and the four-times-daily inbox sweep
(linkedin-inbox-replies, rules.yaml inbox.invitation_search)
searches the past 12 hours as the backstop. Each run hands
EVERY candidate to the program in the same JSON shape as
watch-intake (gmail_id, sender, subject, date, snippet?, body?,
links?, html?), and the shared processed pool means whichever
run takes an invitation first, the other never sees it again.

The program enforces, IN CODE: the From address EQUALS the pinned
invitation sender (any other address is refused); received within
the configured window (720 minutes — 12 hours); not already processed (the SAME processed
pool as the message watch — one source of truth); group-invitation
patterns and the ad/marketing patterns refuse. Every refused
candidate is recorded processed immediately and printed under
"refused" with its reason (silently — a group invitation is never
logged by name). The result's "actionable" list is the whole work
packet — ONLY these, each {gmail_id, person, person_parsed,
received_at, accept_url}: click "accept_url" (the href behind the
email's Accept button/link — it redirects and connects the user to that
person, with no visit to LinkedIn's invitations page); when no
Accept link is in the email, accept_url is null and an
"accept_url_note" says so — then open the email's Accept button
itself instead.

7) INVITATION RECORD — `spine.py inbox invite-record results.json`
After handling, the run returns one result per actionable item:

[
  {
    "gmail_id": "1a1d07bb001d2370",        // required
    "person": "Jane Doe",                  // required for accepted
    "outcome": "accepted"                  // accepted | skipped
  }
]

The program validates each result, marks the Gmail ID processed,
and for outcome "accepted" appends ONE outreach-log line naming
the person (standing rule: log each acceptance by name) and
prints per-entry results with "verified" from a read-back.
Outcome "skipped" (an ad/marketing or group invitation the run
judged not a real person) marks the ID processed with NO log
line. A replayed record is REFUSED — nothing is written twice.
No claims-ledger lines are written for invitations.

8) JOB-ALERT INTAKE — `spine.py inbox jobalert-intake
candidates.json`
LinkedIn job alerts are a DISCOVERY SOURCE (the user, Nov 12, 2026):
the user's saved alerts send one email per alert per day, ALWAYS from
jobalerts-noreply@linkedin.com (rules.yaml
inbox.job_alert_sender + inbox.jobalert_search — the watch list's
third pinned sender). The batch run searches Gmail with the
jobalert_search query — FROM-ONLY: from:jobalerts-noreply@
linkedin.com, past 12 hours, NO subject terms, ever — and hands
EVERY find to this intake in the same JSON shape as the other
intakes.

IDENTIFICATION IS SENDER-ONLY (the user, Nov 12, 2026): alert subjects
come in many formats (LinkedIn builds the subject from the first
company on the list, in a shape like "<role> job at <company>
for you", and formats vary), so the subject is NEVER consulted
here — no subject
patterns, no content classification, no matching against the
configured alert definitions. The sender <-> alerts
correspondence is ONE-TO-ONE AND CLOSED: nothing else arrives
from that address, and every email from it is necessarily one of
the alerts the user herself set up — any pinned-sender email inside
the 24-hour window that this flow has not consumed is
ACTIONABLE, full stop. The message intake keeps BOTH of its
filters (pinned sender AND subject patterns) and the invitation
intake is sender-only like job alerts; both intakes still
refuse this address as job-alert mail, under their own consumer
stamp (see below).

The packet's actionable entries carry: the extracted job links
({job_url, label} — linkedin.com/jobs/view/ URLs, including the
target inside a redirect href; label = the anchor text when the
link carries one), "see_all_url" (the href behind the email's
"See all jobs" button, as its own field), and "instructions" —
the code's FIXED numbered instruction list for working this
email (the user, Nov 12, 2026: the code spits out simple, clear,
defined instructions for the runner every day). The runner
follows the instructions field exactly. When no links extract,
the email is still actionable with an empty jobs list + a note.
That note path applies only when the candidate actually carried
the email's contents (html, links, or a body with LinkedIn URLs
in it). A candidate with NO html, NO links and no LinkedIn URL
in its body was never read in full — intake REFUSES it (the
refusal carries "consumed": false) and does NOT mark it
processed: re-read the email in full (body, links, html) and
re-feed it. A stripped candidate can never screen as an empty
alert again.

CONSUMER SCOPES: the processed pool is shared, but consumption
is stamped per flow ("inbox" vs "jobalert"). A watch/invite
refusal of a job-alert email consumes the ID for the INBOX flow
only — the alert flow can still take it; a jobalert record
consumes it for the ALERT flow only. Neither flow can starve
the other.

9) JOB-ALERT RECORD — `spine.py inbox jobalert-record
results.json`
After the run has vetted every job in an alert email (per the
packet's instructions), it returns one result per email:

[
  {
    "gmail_id": "1a1d07bb001d2370",        // required
    "outcome": "screened"                  // screened | skipped
  }
]

The program marks the Gmail ID processed under the JOBALERT
consumer stamp and prints verified read-backs. A replay is
REFUSED — nothing is written twice. No claims-ledger lines, no
outreach-log lines: the jobs themselves are recorded through
stock.py as LINKEDIN_ALERT.

10) DAILY FINISH — `spine.py inbox daily-finish summary.json`
The daily check's completion record. At the end of EVERY run —
including a run that handled nothing — the run hands in its
counts as data:

{
  "conversations": {"in_scope": 0, "replied": 0,
                    "no_reply": 0, "wu_decision": 0},
  "invitations":   {"found": 0, "accepted": 0, "skipped": 0},
  "alerts":        {"found": 0, "screened": 0},
  "alerts_not_on_revelio": [
    {"company": "…", "resolution": "linkedin_packet"},
    {"company": "…", "resolution": "linkedin_no_counts"}
  ],
  "note": "…"                          // optional, one clause
}

The program validates that ALL THREE parts are present with
every count, that no handled count exceeds its found/in-scope
count, and then writes the "Daily inbox check" line to the
outreach log itself and verifies it by read-back. A summary
missing the alerts part (or any part) is refused whole —
nothing is written — so a daily run cannot finish without
accounting for the alert pass. This line is the proof the pass
happened; the daily watchdog reads that log.

"alerts_not_on_revelio" is REQUIRED whenever alerts.found > 0
(an empty list is fine): it names EVERY company the alert
pass wrote off as not on Revelio, with the resolution of the
mandatory LinkedIn fallback (the user, Nov 13, 2026 — a company not
on Revelio is vetted through its LinkedIn company profile:
headcount first, then the India employee count):
  "linkedin_packet"  — the fallback gate packet (source
      "LinkedIn People", revelio_not_found: true, total =
      the page's "associated members" number, locations =
      the "Where they live" rows with South Asia marks) was
      recorded through stock.py;
  "linkedin_no_counts" — LinkedIn gave no usable counts and
      the drop was recorded through stock.py with gate
      {"revelio_not_found": true, "linkedin_checked": true}.
The program verifies each named company against the outreach
log and REFUSES the finish — nothing written — for any whose
fallback record is not in the log: a not-on-Revelio company
may never be written off in run notes alone. The finish ALSO
consults code's tracked fallback state (the code step between
Revelio and LinkedIn): a fallback order opened the same day
that is still open — ordered, but never recorded — refuses
the finish too. The tracked state is the stronger source;
both checks must pass."""


# ------------------------------------------------------------------ config

def _inbox_cfg(rules_path: Path = RULES_PATH) -> dict:
    rules = yaml.safe_load(Path(rules_path).read_text(encoding="utf-8"))
    return rules.get("inbox") or {}


def _patterns(cfg: dict, key: str) -> list[re.Pattern]:
    out = []
    for pat in cfg.get(key) or []:
        out.append(re.compile(str(pat), re.IGNORECASE))
    return out


# ------------------------------------------------------------------- state

def _seed_ids_from_md(md_path: Path) -> set[str]:
    """One-time seed: Gmail IDs listed under the watch .md's
    'Processed Gmail message IDs:' heading (the hand-kept state the
    watch started with). Read once, only when the JSON state does
    not exist yet — after that the JSON is the only state."""
    if not md_path.exists():
        return set()
    text = md_path.read_text(encoding="utf-8")
    idx = text.find("Processed Gmail message IDs:")
    if idx < 0:
        return set()
    return set(_GMAIL_ID_RE.findall(text[idx:]))


def load_state(state_path: Path = STATE_PATH,
               md_path: Path = WATCH_MD_PATH) -> dict:
    state_path = Path(state_path)
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
        data.setdefault("processed", {})
        data.setdefault("handled", [])
        return data
    seeded = _seed_ids_from_md(Path(md_path))
    return {"version": 1,
            "processed": {mid: {"via": "seed",
                                "source": "linkedin-message-watch-state.md"}
                          for mid in sorted(seeded)},
            "handled": []}


def save_state(data: dict, state_path: Path = STATE_PATH) -> None:
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, state_path)


def _entry_consumers(entry: dict) -> set:
    """Which flows have consumed this processed entry. The processed
    pool is SHARED (one source of truth for Gmail-ID dedupe), but
    consumption is scoped per consumer — "inbox" (the message watch
    + invitation flow) and "jobalert" (the job-alert discovery
    flow) — so the flows cannot starve each other: the watch's
    refusal of a job-alert email must not burn the ID for the alert
    flow, and the alert flow's screening must not burn it for the
    watch (the user, Nov 12, 2026). New entries carry an explicit
    "consumers" list, written by _mark_processed; older entries
    (written before consumer scoping) are inferred: a jobalert via
    is the alert flow's, a job_alert classification or any
    watch-/invite- via is the inbox flow's, and the one-time seed
    counts for every flow (those IDs are historical for all)."""
    explicit = entry.get("consumers")
    if isinstance(explicit, list) and explicit:
        return {str(c) for c in explicit}
    via = str(entry.get("via") or "")
    if via.startswith("jobalert"):
        return {"jobalert"}
    if via == "seed":
        return {"inbox", "jobalert"}
    return {"inbox"}


def _consumed(processed: dict, gmail_id: str, consumer: str) -> bool:
    """True when this Gmail ID has been consumed BY THIS consumer —
    the only dedupe question any intake or record may ask."""
    entry = processed.get(gmail_id)
    return isinstance(entry, dict) and \
        consumer in _entry_consumers(entry)


def _mark_processed(data: dict, gmail_id: str, entry: dict,
                    consumer: str | None = None) -> None:
    """Stamp a Gmail ID processed, MERGING consumer scopes: an
    existing entry keeps its consumers and gains the new one, so a
    later stamp from the other flow never erases the first flow's
    consumption (the entry's display fields take the latest stamp)."""
    processed = data.setdefault("processed", {})
    existing = processed.get(gmail_id)
    consumers: set = set()
    if isinstance(existing, dict):
        consumers |= _entry_consumers(existing)
    consumers |= _entry_consumers(entry)
    if consumer:
        consumers.add(consumer)
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update(entry)
    merged["consumers"] = sorted(consumers)
    processed[gmail_id] = merged


# -------------------------------------------------------------------- time

def parse_dt(raw) -> datetime | None:
    """ISO 8601 or RFC 2822 → aware datetime (naive read as UTC)."""
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, str) and raw.strip():
        text = raw.strip()
        dt = None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = parsedate_to_datetime(text)
            except (TypeError, ValueError):
                dt = None
        if dt is None:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt


def _ct_stamp(dt: datetime) -> str:
    """The claims ledger's normalized timestamp: 'YYYY-MM-DD HH:MM CT'."""
    return dt.astimezone(CT).strftime("%Y-%m-%d %H:%M CT")


# ------------------------------------------------------------------ claims

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def check_claim(person: str, message_ts=None, claim_key: str = "",
                claims_path: Path = CLAIMS_PATH) -> dict:
    """CLAIMED / CLEAR for one thread action. A ledger line matches
    when it carries the person's name AND the message's normalized
    timestamp (or at least its date) — the ledger's own key is
    name + latest-incoming time, matched semantically across the
    older wordings the file warns about. An explicit claim_key
    matches as a normalized substring."""
    claims_path = Path(claims_path)
    text = claims_path.read_text(encoding="utf-8") \
        if claims_path.exists() else ""
    dt = parse_dt(message_ts) if message_ts else None
    stamp = _ct_stamp(dt) if dt else ""
    date_part = stamp[:10] if stamp else ""
    name = _norm(person)
    matches = []
    for line in text.splitlines():
        low = _norm(line)
        if claim_key and _norm(claim_key) in low:
            matches.append(line.strip())
            continue
        if not name or name not in low:
            continue
        if stamp and (stamp.lower() in low or date_part in low):
            matches.append(line.strip())
    return {"verdict": "CLAIMED" if matches else "CLEAR",
            "person": person, "message_ts": stamp or None,
            "matches": matches}


_CLAIM_LINE_RE = re.compile(r"CLAIM(?:ED)?\b")
_LATEST_INCOMING_RE = re.compile(
    r"latest incoming (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) CT")
_CLAIM_TS_RE = re.compile(r"CLAIM (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) CT")
_BRACKET_TS_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) CT\]")
_STATUS_RE = re.compile(r"status: ([A-Z][A-Z /()—-]*)")


def _claim_entries(claims_path: Path) -> list[dict]:
    """Deterministic reads of the ledger's claim lines: person,
    message/claim timestamp, status — for the daily stand_down list.
    Lines the regexes cannot read (free-form annotations) are
    skipped; check_claim's name+date search still sees them."""
    claims_path = Path(claims_path)
    if not claims_path.exists():
        return []
    out = []
    for line in claims_path.read_text(encoding="utf-8").splitlines():
        if not _CLAIM_LINE_RE.search(line):
            continue
        m = _LATEST_INCOMING_RE.search(line) or \
            _CLAIM_TS_RE.search(line) or _BRACKET_TS_RE.search(line)
        if not m:
            continue
        ts = parse_dt(f"{m.group(1)}T{m.group(2)}:00")
        ts = ts.replace(tzinfo=CT) if ts else None
        person = None
        pm = re.search(r"thread with ([^—(]+)", line)
        if pm:
            person = pm.group(1).strip()
        else:
            pm = re.search(r"—\s*(?:CLAIM —\s*)?([^,(]+?)\s*(?:\(|,)", line)
            if pm:
                person = pm.group(1).strip()
        if not person:
            continue
        sm = _STATUS_RE.search(line)
        out.append({"person": person, "ts": ts,
                    "status": (sm.group(1).strip() if sm else "CLAIMED"),
                    "line": line.strip()})
    return out


def _build_claim_key(result: dict) -> str:
    """The ledger key, in its pinned format: sender name + the latest
    incoming message's normalized time + its first few words +
    action type (linkedin-reply). A run-supplied claim_key wins."""
    if (result.get("claim_key") or "").strip():
        return result["claim_key"].strip()
    person = (result.get("person") or "").strip()
    dt = parse_dt(result.get("message_ts"))
    stamp = _ct_stamp(dt) if dt else "time unknown"
    words = (result.get("first_words") or "").strip()
    if not words and (result.get("snippet") or "").strip():
        words = " ".join(result["snippet"].split()[:6])
    key = f"{person}, latest incoming {stamp}"
    if words:
        key += f' "{words}"'
    return key + " + linkedin-reply"


def _append_claim(claims_path: Path, key: str, job: str, status: str,
                  now: datetime) -> str:
    line = (f"- CLAIM {_ct_stamp(now)} — {key} — claimed by {job} — "
            f"status: {status} {MARKER}")
    claims_path = Path(claims_path)
    existing = claims_path.read_text(encoding="utf-8") \
        if claims_path.exists() else ""
    prefix = "" if (not existing or existing.endswith("\n")) else "\n"
    with claims_path.open("a", encoding="utf-8") as f:
        f.write(prefix + line + "\n")
    return line


# ------------------------------------------------------------------- triage

def _sender_display_name(sender: str, cfg: dict) -> str | None:
    """The sender's display name as a person's name ('Pruthvi Desai
    via LinkedIn' → 'Pruthvi Desai'), or None when the display is
    the platform itself, a bare address, or a triage sender."""
    display = (sender or "").split("<")[0].strip().strip('"')
    display = re.sub(r"\s+via LinkedIn$", "", display,
                     flags=re.IGNORECASE).strip()
    if display and display.lower() not in ("linkedin", "linkedin member") \
            and "@" not in display \
            and not any(p.search(sender or "") for p in
                        _patterns(cfg, "non_message_sender_patterns")):
        return display
    return None


def _parse_person(subject: str, sender: str,
                  cfg: dict) -> tuple[str | None, bool]:
    """The person's name. The subject patterns name the person (the
    'just messaged you' form carries only the FIRST name); the
    sender display name carries the FULL name — when both parse and
    the sender's name is fuller, the sender's wins (the user, Nov 12,
    2026, real sample: subject 'Pruthvi just messaged you', sender
    'Pruthvi Desai via LinkedIn' → 'Pruthvi Desai'). (None, False)
    when neither format allows it — the packet still passes; the
    run identifies the person from the email itself."""
    subject_name = None
    for pat in _patterns(cfg, "message_subject_person_patterns"):
        m = pat.search(subject or "")
        if m and m.group(1).strip():
            subject_name = m.group(1).strip()
            break
    sender_name = _sender_display_name(sender, cfg)
    if sender_name and (not subject_name
                        or len(sender_name.split())
                        > len(subject_name.split())):
        return sender_name, True
    if subject_name:
        return subject_name, True
    if sender_name:
        return sender_name, True
    return None, False


_THREAD_URL_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/messaging/[^\s\"'&<>\\]+")
_VIEW_MESSAGE_A_RE = re.compile(
    r"<a\b[^>]*?href=\"([^\"]+)\"[^>]*>(?:(?!</a>).)*?View message",
    re.IGNORECASE | re.DOTALL)


def _messaging_url(raw: str) -> str | None:
    """The LinkedIn messaging URL inside a raw link, unwrapping one
    level of URL-encoding (notification emails route the button
    through a redirect whose target is encoded in the href)."""
    from urllib.parse import unquote
    for text in (raw or "", unquote(raw or "")):
        m = _THREAD_URL_RE.search(text)
        if m:
            return m.group(0).rstrip(").,")
    return None


def extract_thread_url(candidate: dict) -> str | None:
    """The conversation URL behind the email's 'View message'
    button (the user, Nov 12, 2026: that link lands directly on the one
    conversation — the watch opens IT, not the inbox). Sources, in
    order: an anchor whose text is 'View message' in the email's
    HTML; any messaging-thread URL in the candidate's links list;
    any such URL in the body text. None when no link is present."""
    html = candidate.get("html") or ""
    m = _VIEW_MESSAGE_A_RE.search(html)
    if m:
        url = _messaging_url(m.group(1))
        if url:
            return url
        if "linkedin.com" in m.group(1):
            return m.group(1)
    links = candidate.get("links") or []
    if isinstance(links, (str, bytes)):
        links = [links]
    for link in links:
        raw = link.get("href") or link.get("url") or "" \
            if isinstance(link, dict) else str(link)
        url = _messaging_url(raw)
        if url:
            return url
    for text in (html, candidate.get("body") or ""):
        url = _messaging_url(text)
        if url:
            return url
    return None


def _sender_address(sender: str) -> str:
    """The bare From address, lowercased ('Jane Doe via LinkedIn
    <Messaging-Digest-Noreply@LinkedIn.com>' →
    'messaging-digest-noreply@linkedin.com')."""
    m = re.search(r"<([^>]+)>", sender or "")
    addr = m.group(1) if m else (sender or "")
    return addr.strip().lower()


def _pinned_sender(candidate: dict, cfg: dict) -> bool:
    """True when the candidate's From ADDRESS is the pinned
    notification address (rules.yaml inbox.gmail_search.from_address
    — the user, Nov 12, 2026: "It will always come from this email:
    messaging-digest-noreply@linkedin.com")."""
    pinned = ((cfg.get("gmail_search") or {}).get("from_address")
              or "").strip().lower()
    return bool(pinned) and \
        _sender_address(candidate.get("sender") or "") == pinned


def _job_alert_sender(candidate: dict, cfg: dict) -> bool:
    """True when the candidate's From ADDRESS is the pinned
    job-alert address (rules.yaml inbox.job_alert_sender
    .from_address — jobalerts-noreply@linkedin.com, the user, Nov 12,
    2026: ALL LinkedIn job-alert email comes from this address
    only). Job-alert mail is neither a message nor an invitation:
    both INBOX intakes refuse it on this exact address, and the
    refusal is recorded processed under the INBOX consumer stamp
    only — the job-alert discovery flow (jobalert-intake, below)
    consumes the same ID under its own stamp, so the refusal
    never starves it."""
    pinned = ((cfg.get("job_alert_sender") or {}).get("from_address")
              or "").strip().lower()
    return bool(pinned) and \
        _sender_address(candidate.get("sender") or "") == pinned


def _job_alert_reason(cfg: dict) -> str:
    addr = ((cfg.get("job_alert_sender") or {}).get("from_address")
            or "jobalerts-noreply@linkedin.com")
    return (f"job-alert mail from the pinned job-alert sender "
            f"({addr}) — classified job_alert: not a message, "
            f"not an invitation; the inbox flows take no action on "
            f"it (it belongs to the job-alert discovery flow, which "
            f"consumes the ID under its own consumer stamp)")


def _triage(candidate: dict, cfg: dict) -> str | None:
    """None when the candidate is a genuine message notification,
    else the refusal reason (deterministic, config patterns only).
    A PASS pattern (message / InMail subject, from config) is the
    primary genuine-message signal and wins over every refusal
    pattern — triage checks those first. The PINNED sender address
    is a pass condition of its own: despite the 'digest' in its
    name it carries the real per-message notifications, so sender
    patterns never refuse mail from it (a digest SUBJECT from that
    address is still refused on the subject patterns — the address
    vouches for the sender, not for every subject it sends)."""
    subject = candidate.get("subject") or ""
    sender = candidate.get("sender") or ""
    if _job_alert_sender(candidate, cfg):
        return _job_alert_reason(cfg)
    for key in ("message_subject_patterns", "inmail_subject_patterns"):
        for pat in _patterns(cfg, key):
            if pat.search(subject):
                return None
    if not _pinned_sender(candidate, cfg):
        for pat in _patterns(cfg, "non_message_sender_patterns"):
            if pat.search(sender):
                return f"non-message sender pattern: /{pat.pattern}/"
    for pat in _patterns(cfg, "non_message_subject_patterns"):
        if pat.search(subject):
            return f"non-message subject pattern: /{pat.pattern}/"
    for pat in _patterns(cfg, "connection_accepted_subject_patterns"):
        if pat.search(subject):
            if not (candidate.get("body") or "").strip():
                return ("connection-accepted notice with no message "
                        f"body (subject pattern: /{pat.pattern}/)")
    return None


# ------------------------------------------------------- invitation intake

def _parse_invite_person(subject: str, sender: str,
                         cfg: dict) -> tuple[str | None, bool]:
    """The inviter's name, same preference rule as _parse_person:
    the invitation subject patterns name the person as written
    (often just a first name in the possessive form); the sender
    display name carries the FULL name — when both parse and the
    sender's is fuller, the sender's wins. (None, False) when
    neither format allows it — the packet still passes; the run
    identifies the person from the email itself."""
    subject_name = None
    for pat in _patterns(cfg, "invitation_subject_person_patterns"):
        m = pat.search(subject or "")
        if m and m.group(1).strip():
            subject_name = m.group(1).strip()
            break
    sender_name = _sender_display_name(sender, cfg)
    if sender_name and (not subject_name
                        or len(sender_name.split())
                        > len(subject_name.split())):
        return sender_name, True
    if subject_name:
        return subject_name, True
    if sender_name:
        return sender_name, True
    return None, False


_ACCEPT_A_RE = re.compile(
    r"<a\b[^>]*?href=\"([^\"]+)\"[^>]*>(?:(?!</a>).)*?Accept",
    re.IGNORECASE | re.DOTALL)
_ACCEPT_A_RE_SQ = re.compile(
    r"<a\b[^>]*?href='([^']+)'[^>]*>(?:(?!</a>).)*?Accept",
    re.IGNORECASE | re.DOTALL)
_ANY_URL_RE = re.compile(r"https?://[^\s\"'<>\\]+")


def _accept_url_candidate(raw: str) -> str | None:
    """An Accept link as found: returned as-is when it is an http(s)
    URL (invitation Accept hrefs are LinkedIn redirect links — the
    redirect IS the mechanism, the user, Nov 12, 2026 — so unlike the
    messaging extractor no inner target is unwrapped out of it);
    one level of URL-encoding is tried when the raw text is not
    itself a URL."""
    from urllib.parse import unquote
    for text in (raw or "", unquote(raw or "")):
        m = _ANY_URL_RE.search(text)
        if m:
            return m.group(0).rstrip(").,")
    return None


def extract_accept_url(candidate: dict) -> str | None:
    """The href behind the email's Accept button/link (the user, Nov 12,
    2026: clicking it redirects and connects the user to the person — the
    run clicks THIS link, never the invitations page). Sources, in
    order: an anchor whose text says 'Accept' in the email's HTML;
    a links-list entry whose text/context says Accept or whose URL
    itself carries 'accept'; an 'accept' URL in the body text.
    None when no Accept link is present."""
    html = candidate.get("html") or ""
    for rx in (_ACCEPT_A_RE, _ACCEPT_A_RE_SQ):
        m = rx.search(html)
        if m:
            url = _accept_url_candidate(m.group(1))
            if url:
                return url
    links = candidate.get("links") or []
    if isinstance(links, (str, bytes)):
        links = [links]
    for link in links:
        if isinstance(link, dict):
            raw = link.get("href") or link.get("url") or ""
            context = " ".join(str(link.get(k) or "") for k in
                               ("text", "label", "title", "context"))
        else:
            raw, context = str(link), ""
        if "accept" in context.lower() or "accept" in raw.lower():
            url = _accept_url_candidate(raw)
            if url:
                return url
    for text in (candidate.get("body") or "", html):
        for m in _ANY_URL_RE.finditer(text or ""):
            if "accept" in m.group(0).lower():
                return m.group(0).rstrip(").,")
    return None


def _invite_pinned_sender(candidate: dict, cfg: dict) -> bool:
    """True when the candidate's From ADDRESS is the pinned
    invitation address (rules.yaml inbox.invitation_search
    .from_address — invitations@linkedin.com, the user, Nov 16,
    2026: incoming connection invitations come only from this
    address, and it sends nothing else)."""
    pinned = ((cfg.get("invitation_search") or {}).get("from_address")
              or "").strip().lower()
    return bool(pinned) and \
        _sender_address(candidate.get("sender") or "") == pinned


def _invite_triage(candidate: dict, cfg: dict) -> str | None:
    """None when the candidate is a genuine connection-invitation
    notification, else the refusal reason (deterministic, config
    patterns only). Identification is SENDER-ONLY (the user,
    Nov 16, 2026): the pinned invitations@linkedin.com address IS
    the identification — the user's LinkedIn notifications are
    configured so that address sends connection invitations and
    nothing else, so NO subject pattern gates intake (the Nov 12
    subject pass pattern is scrapped). What remains here is only
    the standing accept-rule refusals: GROUP patterns refuse first
    (a group invitation is declined silently); then the shared
    ad/marketing patterns (non-message subject patterns on the
    subject, non-message sender patterns on the sender display
    name — the pinned From address itself is exact-matched before
    triage and never pattern-refused)."""
    subject = candidate.get("subject") or ""
    sender = candidate.get("sender") or ""
    haystack = f"{subject} {sender}"
    for pat in _patterns(cfg, "invitation_group_patterns"):
        if pat.search(haystack):
            return f"group invitation pattern: /{pat.pattern}/"
    for pat in _patterns(cfg, "non_message_subject_patterns"):
        if pat.search(subject):
            return f"non-message subject pattern: /{pat.pattern}/"
    display = sender.split("<")[0]
    for pat in _patterns(cfg, "non_message_sender_patterns"):
        if pat.search(display):
            return f"non-message sender pattern: /{pat.pattern}/"
    return None


def invite_intake(candidates, now: datetime | None = None,
                  state_path: Path = STATE_PATH,
                  rules_path: Path = RULES_PATH,
                  md_path: Path = WATCH_MD_PATH) -> dict:
    """Validate the watch's invitation-email finds. Returns
    {actionable, refused} — refusals are recorded processed in the
    same call, in the SAME processed pool as the message watch;
    actionable items are NOT (invite-record marks them, after the
    run has handled them). Raises ValueError on a malformed batch
    (nothing written)."""
    if isinstance(candidates, dict):
        candidates = candidates.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("invite-intake needs a non-empty JSON list "
                         "of candidate invitation emails")
    now = now or datetime.now(CT)
    cfg = _inbox_cfg(rules_path)
    inv_search = cfg.get("invitation_search") or {}
    window = timedelta(minutes=int(
        inv_search.get("window_minutes")
        or cfg.get("past_hour_window_minutes", 60)))
    skew = timedelta(minutes=int(cfg.get("future_skew_minutes", 5)))
    state = load_state(state_path, md_path)
    processed = state["processed"]

    actionable, refused = [], []
    seen_in_batch: set[str] = set()
    dirty = False
    for cand in candidates:
        if not isinstance(cand, dict):
            refused.append({"gmail_id": None,
                            "reason": "candidate is not a JSON object"})
            continue
        mid = cand.get("gmail_id") or ""
        label = {"gmail_id": mid or None,
                 "subject": cand.get("subject") or ""}
        reason = None
        if not _GMAIL_ID_RE.fullmatch(mid or ""):
            reason = f"bad gmail_id: {mid!r}"
        elif _consumed(processed, mid, "inbox"):
            reason = "already processed (duplicate Gmail ID)"
        elif mid in seen_in_batch:
            reason = "duplicate within this intake batch"
        else:
            received = parse_dt(cand.get("date"))
            if received is None:
                reason = f"unparseable date: {cand.get('date')!r}"
            elif received < now - window:
                reason = (f"stale: received {_ct_stamp(received)}, "
                          f"older than the past-"
                          f"{int(window.total_seconds() // 60)}-minute "
                          f"window (cutoff {_ct_stamp(now - window)})")
            elif received > now + skew:
                reason = (f"dated in the future: {_ct_stamp(received)} "
                          f"(beyond the {int(skew.total_seconds() // 60)}"
                          f"-minute skew allowance)")
            elif _job_alert_sender(cand, cfg):
                reason = _job_alert_reason(cfg)
            elif not _invite_pinned_sender(cand, cfg):
                reason = ("not from the pinned invitation sender "
                          f"({(inv_search.get('from_address') or '')} "
                          "is the only invitation sender; got "
                          f"{_sender_address(cand.get('sender') or '')!r})")
            else:
                reason = _invite_triage(cand, cfg)
        if mid:
            seen_in_batch.add(mid)
        if reason:
            refused.append(dict(label, reason=reason))
            if _GMAIL_ID_RE.fullmatch(mid or "") and \
                    not _consumed(processed, mid, "inbox"):
                _entry = {"at": now.isoformat(),
                          "via": "invite-intake",
                          "outcome": "refused", "reason": reason}
                if _job_alert_sender(cand, cfg):
                    _entry["classification"] = "job_alert"
                _mark_processed(state, mid, _entry, consumer="inbox")
                dirty = True
            continue
        person, parsed = _parse_invite_person(cand.get("subject") or "",
                                              cand.get("sender") or "",
                                              cfg)
        entry = {"gmail_id": mid, "person": person,
                 "person_parsed": parsed,
                 "received_at": parse_dt(cand.get("date"))
                 .astimezone(CT).isoformat(),
                 "accept_url": extract_accept_url(cand)}
        if entry["accept_url"] is None:
            entry["accept_url_note"] = (
                "no Accept link found in this email — open the "
                "email's Accept button itself to accept")
        actionable.append(entry)
    if dirty:
        save_state(state, state_path)
    return {"generated_at": now.isoformat(),
            "window_minutes": int(window.total_seconds() // 60),
            "cutoff": (now - window).astimezone(CT).isoformat(),
            "actionable": actionable, "refused": refused}


INVITE_OUTCOMES = ("accepted", "skipped")


def invite_record(results, now: datetime | None = None,
                  log_path: Path = LOG_PATH,
                  state_path: Path = STATE_PATH,
                  md_path: Path = WATCH_MD_PATH) -> dict:
    """Record invitation outcomes: per result, validate, mark the
    Gmail ID processed (the shared pool), and — for outcome
    'accepted' ONLY — append ONE outreach-log line naming the
    person (standing rule: log each acceptance by name). A skipped
    outcome (ad/marketing, or a group invitation the run judged)
    marks processed with NO log line, so no ad or group is ever
    named in the log. A replay (already processed) is refused and
    writes nothing twice. No claims-ledger lines: dedupe here is
    the processed pool plus the log line."""
    if isinstance(results, dict):
        results = results.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("invite-record needs a non-empty JSON list "
                         "of results")
    now = now or datetime.now(CT)
    state = load_state(state_path, md_path)

    recorded, refused = [], []
    for res in results:
        label = {"gmail_id": res.get("gmail_id") if isinstance(res, dict)
                 else None,
                 "person": res.get("person") if isinstance(res, dict)
                 else None}
        if not isinstance(res, dict):
            refused.append(dict(label, reason="result is not a JSON object"))
            continue
        person = (res.get("person") or "").strip()
        outcome = res.get("outcome") or ""
        mid = res.get("gmail_id") or ""
        problem = None
        if outcome not in INVITE_OUTCOMES:
            problem = (f"outcome must be one of {INVITE_OUTCOMES}; "
                       f"got {outcome!r}")
        elif outcome == "accepted" and not person:
            problem = "missing required field: person (an acceptance is logged by name)"
        elif not _GMAIL_ID_RE.fullmatch(mid or ""):
            problem = f"bad gmail_id: {mid!r}"
        elif _consumed(state["processed"], mid, "inbox"):
            problem = (f"gmail_id {mid} is already processed — a replay "
                       f"records nothing twice")
        if problem:
            refused.append(dict(label, reason=problem))
            continue

        log_line = None
        if outcome == "accepted":
            log_line = log_writer.append_entry(
                str(log_path),
                f"LINKEDIN INVITATION ACCEPTED (email watch) — "
                f"{person} — accepted via the invitation email's "
                f"Accept link (Gmail {mid}); now connected. {MARKER}",
                when=now)
        handled = {"outcome": outcome, "job": WATCH_JOB,
                   "via": "invite-record", "at": now.isoformat(),
                   "gmail_id": mid}
        if outcome == "accepted":
            handled["person"] = person
        _mark_processed(state, mid,
                        {"at": now.isoformat(), "via": "invite-record",
                         "outcome": outcome,
                         **({"person": person}
                            if outcome == "accepted" else {})},
                        consumer="inbox")
        state["handled"].append(handled)
        save_state(state, state_path)

        landed_state = load_state(state_path, md_path)
        landed_log = Path(log_path).read_text(encoding="utf-8") \
            if Path(log_path).exists() else ""
        landed = {"processed": mid in landed_state["processed"],
                  "log_entry": (log_line in landed_log)
                  if log_line else None}
        problems = [f"the {k} did not land on read-back"
                    for k, v in landed.items() if v is False]
        entry_out = dict(label, outcome=outcome, log_line=log_line,
                         landed=landed, verified=not problems)
        if problems:
            entry_out["problems"] = problems
        recorded.append(entry_out)
    return {"recorded": recorded, "refused": refused}


# ----------------------------------------------------------- job alerts

_JOB_VIEW_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/(?:comm/)?jobs/view/[^\s\"'<>\]\\)]+")
_ANCHOR_RE = re.compile(
    r"<a\b[^>]*?href=\"([^\"]+)\"[^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL)
_ANCHOR_RE_SQ = re.compile(
    r"<a\b[^>]*?href='([^']+)'[^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _anchor_label(inner_html: str) -> str:
    import html as _html
    text = _TAG_STRIP_RE.sub(" ", inner_html or "")
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def _job_target(raw: str) -> str | None:
    """The LinkedIn job-page URL inside a raw link: the URL itself
    when it is a /jobs/view/ link, or the /jobs/view/ target inside
    a redirect href (one level of URL-decoding — alert emails route
    job links through LinkedIn redirect wrappers)."""
    from urllib.parse import unquote
    for text in (raw or "", unquote(raw or "")):
        m = _JOB_VIEW_RE.search(text)
        if m:
            return m.group(0).rstrip(").,")
    return None


def extract_job_links(candidate: dict) -> tuple[list, str | None]:
    """(jobs, see_all_url) for one alert email. jobs is a list of
    {job_url, label} in email order, deduped by job URL — label is
    the anchor text when the link carries one (the job title, in
    the sampled format, the user, Nov 12, 2026), else "". see_all_url is
    the href behind the email's "See all jobs" button, returned
    as-is (a LinkedIn redirect/list link, like the invitation
    Accept URL — the redirect IS the mechanism), or None.
    Deterministic extraction only: no title/company is parsed or
    guessed in code — the run reads those off the page."""
    jobs: list = []
    seen: set = set()
    see_all: str | None = None

    def note_link(raw: str, label: str) -> None:
        nonlocal see_all
        if "see all jobs" in (label or "").lower():
            if see_all is None:
                see_all = _accept_url_candidate(raw or "")
            return
        target = _job_target(raw or "")
        if target and target not in seen:
            seen.add(target)
            jobs.append({"job_url": target, "label": label or ""})

    html = candidate.get("html") or ""
    for rx in (_ANCHOR_RE, _ANCHOR_RE_SQ):
        for m in rx.finditer(html):
            note_link(m.group(1), _anchor_label(m.group(2)))
    links = candidate.get("links") or []
    if isinstance(links, (str, bytes)):
        links = [links]
    for link in links:
        if isinstance(link, dict):
            raw = link.get("href") or link.get("url") or ""
            label = " ".join(str(link.get(k) or "") for k in
                             ("text", "label", "title", "context"))
        else:
            raw, label = str(link), ""
        note_link(raw, label.strip())
    for m in _JOB_VIEW_RE.finditer(candidate.get("body") or ""):
        note_link(m.group(0), "")
    return jobs, see_all


def _applied_companies(rules_path: Path = RULES_PATH) -> list:
    """The program's own record of companies already applied to:
    LogState.window_status's all_time_verified_by_company (the
    same set the diversification order treats as repeat companies),
    keys normalized by state.normalize_company (lower case).
    Read from the outreach log named in rules.yaml paths. Any
    failure returns [] — the packet then carries an empty record
    and the partition step simply finds no repeats."""
    try:
        import state as _state
        rules = yaml.safe_load(
            Path(rules_path).read_text(encoding="utf-8")) or {}
        log = (rules.get("paths") or {}).get("outreach_log")
        if not log:
            return []
        ws = _state.parse_log(
            os.path.expanduser(str(log))).window_status()
        return sorted(k for k in (ws.get(
            "all_time_verified_by_company") or {}).keys() if k)
    except Exception:
        return []


def _jobalert_instructions(cfg: dict) -> list:
    """The FIXED runner instructions for one alert email — SHORT
    lines, generated by code (the user, Nov 12, 2026: the code spits out
    simple, clear, defined instructions for the runner; Nov 13,
    2026: "Code handle flow, spit short fixed instructions to
    worker, worker give back json or dictionary for code"). The
    list carries the whole flow; the worker executes it and
    returns JSON results. Never improvised per run."""
    cap = int((cfg.get("jobalert_search") or {}).get("max_pages")
              or 5)
    _js = cfg.get("jobalert_search") or {}
    pause_min = int(_js.get("page_pause_min_seconds") or 20)
    pause_max = int(_js.get("page_pause_max_seconds") or 45)
    if pause_max < pause_min:
        pause_max = pause_min
    return [
        "Work ONLY from this alert email: its job links and its "
        "'See all jobs' link (see_all_url). Never start a LinkedIn "
        "search; never open LinkedIn Jobs home or a feed.",
        "Read company names off the email and the See-all list — "
        "the company name is basic information in the email "
        "itself. Do NOT open a job's link just to learn its "
        "company.",
        f"Page the See-all list through pages 1-{cap}. STOP at "
        f"page {cap} — never open page {cap + 1}.",
        f"PACE THE PAGING like a person reading the list (the "
        f"user, Nov 19, 2026): after each page loads, read and "
        f"scroll through it, then wait {pause_min}-{pause_max} "
        f"seconds before turning to the next page. Vary the wait "
        f"inside that range — never the same pause twice, never "
        f"flip pages back to back. The same varied pause applies "
        f"before opening the next alert's See-all list.",
        "Sort jobs by company WITHOUT opening any posting, and "
        "keep each job tied to its place (page, title, company, "
        "location as printed). This packet's applied_companies "
        "list is the program's record of companies already "
        "applied to (match case-insensitively). Companies NOT on "
        "it are BRAND-NEW: work those first — they are the only "
        "jobs worked. A company ON the list is a DUPLICATE: "
        "dropped on sight — no gate run, no opening, never "
        "fill-in (screening order, the user, Nov 13, 2026: blacklist, "
        "then duplication, then the Revelio gate — all off the "
        "list). (Jobs listed in the email body carry their own "
        "link in this packet, jobs[].job_url — use it directly.)",
        "Title screen for THIS lane: SENIOR Machine Learning "
        "Engineer titles PASS on alert jobs; plain Machine "
        "Learning Engineer passes; Data Scientist / Senior Data "
        "Scientist pass only when the work is technical. Staff, "
        "Lead, Principal and Consultant titles are OUT in every "
        "track. The "
        "Senior-MLE pass is for LinkedIn alert jobs ONLY — "
        "Jobright and Indeed keep plain MLE only.",
        "LinkedIn identifies jobs only (title, company, location, "
        "link). Gate numbers come from Revelio, never from a "
        "LinkedIn page — and the SEQUENCE is code's, in this "
        "exact order (the user, Nov 13, 2026): (1) look the company up "
        "on Revelio and return its gate packet to code — code "
        "decides the verdict and records it; (2) Revelio has NO "
        "listing → return the not-found result to code (a stock "
        "form whose gate is {\"revelio_not_found\": true}, or "
        "spine.py gate-packet not-found) and STOP — code tracks "
        "the company as fallback-owed and hands back an ORDER; "
        "(3) ONLY on code's order: open the company's LinkedIn "
        "People page and return the fallback packet as a "
        "DICTIONARY OF NUMBERS — \"total\" is the \"associated "
        "members\" number at the top of the page (the total "
        "headcount, always shown there), and \"locations\" is "
        "EVERY \"Where they live\" row as {label, count, "
        "south_asia}: copy each row's exact label and number "
        "and mark it South Asia or not with your best judgment "
        "(a row is South Asia when it is in India or elsewhere "
        "in South Asia even when the label does not say India "
        "— \"Greater Bengaluru Area\" is India). Packet: "
        "{source: \"LinkedIn People\", revelio_not_found: "
        "true, total, locations, as_of, page}. Do NO ratio "
        "math — code counts the distinct South Asia employees "
        "from the marked rows (a country row like \"India\" "
        "already includes its state, city and metro rows, so "
        "code counts it once), divides by the total, decides "
        "by the same thresholds, and appends the packet and "
        "verdict to the log; (4) LinkedIn gives no usable counts "
        "either → return the drop through stock.py with gate "
        "{\"revelio_not_found\": true, \"linkedin_checked\": "
        "true} and code records the drop. Never go from a "
        "not-found Revelio result to LinkedIn on your own, "
        "never decide a verdict yourself, and never write a "
        "not-on-Revelio company off in notes alone.",
        "Screen BEFORE opening any job link, in this order: "
        "(a) BLACKLIST first — a company on the blocked list is "
        "declined on sight, no other check, no gate run; "
        "(b) DUPLICATION second — a company on applied_companies "
        "is dropped, no gate run; (c) REVELIO third — the gate "
        "AT IDENTIFICATION: look the company up on Revelio and "
        "run the gate packet; the India count is Revelio's South "
        "Asia count. PASS / PASS_ALERT proceeds; a hard pass is "
        "out. Not on Revelio → return the not-found result to "
        "code and follow the order code hands back (the LinkedIn "
        "fallback gate above — the LinkedIn check happens only "
        "on code's order, never self-directed), then stock with "
        "the packet that sequence produces; if LinkedIn gives "
        "no usable counts either, drop the job (record via "
        "stock.py with gate {\"revelio_not_found\": true, "
        "\"linkedin_checked\": true}). Never look the numbers up "
        "anywhere else. A job killed by any screen never gets "
        "its link opened.",
        "For each job that passes all three screens: OPEN it at "
        "its EXTERNAL source (the company / ATS posting) and vet "
        "the description itself — full-time direct/permanent "
        "hire only (contract or contract-to-hire is OUT); "
        "green-card eligible (citizenship-only or "
        "clearance-required is OUT); the work is technical "
        "(modeling / ML / coding — analytics, BI or "
        "dashboard-only work is OUT); not consulting or "
        "staff-augmentation (client placement / timesheet work "
        "is OUT). Do the pay check there too. Fail any one → "
        "skip the job; pass them all → it is stocked to the "
        "bench.",
        "Apply by the posting's own route — external / ATS, or "
        "LinkedIn Easy Apply: Easy Apply IS okay for these alert "
        "jobs; never skip a posting for being Easy-Apply-only. "
        "Standing application rules apply either way (tailored "
        "resume, humanizer, every field, verification).",
        "Stock every passing job through stock.py, source "
        "LINKEDIN_ALERT, with its gate packet — the LinkedIn "
        "fallback packet when Revelio had no listing (gate "
        "timing is at identification — no verdict, no stocking).",
        "LinkedIn warning or checkpoint at any point: STOP and "
        "alert the user — do not push through.",
        "Every job in this email vetted → record it: spine.py "
        "inbox jobalert-record {gmail_id, outcome: screened} "
        "(outcome: skipped only when the email could not be "
        "worked at all).",
        "Name EVERY company this pass found not on Revelio in "
        "the daily-finish summary's \"alerts_not_on_revelio\" "
        "list — {\"company\": ..., \"resolution\": "
        "\"linkedin_packet\"} when its fallback gate packet "
        "was recorded through stock.py, or {\"company\": ..., "
        "\"resolution\": \"linkedin_no_counts\"} when the "
        "linkedin_checked drop was recorded. The field is "
        "required (an empty list is fine) whenever alert "
        "emails were found, and the finish is REFUSED for any "
        "named company whose fallback record is not in the "
        "log — and while any fallback order code opened during "
        "this pass is still open (code tracks those itself; "
        "an owed LinkedIn check must be run on code's order "
        "and recorded before the day can close).",
    ]


JOBALERT_OUTCOMES = ("screened", "skipped")


def _no_extractable_material(cand: dict) -> bool:
    """True when a job-alert candidate carries nothing the link
    extractor can work on: no html, no usable links, and a body
    with no LinkedIn URL in it. A real alert email always carries
    its job links (a full Gmail read returns body + links +
    html), so a candidate with none of them was fed without
    reading the email in full — the Nov 13, 2026 failure, where
    an intake fed minimal fields came back with empty job lists
    and the emails screened as nothing. Intake refuses such a
    candidate WITHOUT marking it processed, so the run can
    re-read the email in full and re-feed it."""
    if (cand.get("html") or "").strip():
        return False
    links = cand.get("links") or []
    if isinstance(links, (str, bytes)):
        links = [links]
    for link in links:
        if isinstance(link, dict):
            if (link.get("href") or link.get("url")
                    or "").strip():
                return False
        elif str(link).strip():
            return False
    if "linkedin.com" in (cand.get("body") or "").lower():
        return False
    return True


def jobalert_intake(candidates, now: datetime | None = None,
                    state_path: Path = STATE_PATH,
                    rules_path: Path = RULES_PATH,
                    md_path: Path = WATCH_MD_PATH) -> dict:
    """Validate the run's job-alert-email finds (the daily alert
    emails, from the run's sender-only Gmail search — rules.yaml
    inbox.jobalert_search: from jobalerts-noreply@linkedin.com,
    past 12 hours, NO subject terms, ever).

    IDENTIFICATION IS SENDER-ONLY (the user, Nov 12, 2026): alert emails
    arrive in many subject formats — LinkedIn builds the subject
    from the first company on the list, in a shape like
    "<role> job at <company> for you", and formats vary) — so the
    subject is NEVER consulted here, for acceptance or refusal: no
    subject patterns, no shared digest/marketing triage, no
    content classification of any kind. The sender <-> alerts
    correspondence is ONE-TO-ONE AND CLOSED (the user, Nov 12, 2026:
    "only job alerts will come from that job alert email, and then
    the job alert email will only be the job alert I set up — so
    it's one to one… very tight."): NOTHING else arrives from the
    pinned sender, and every email from it is necessarily one of
    the alerts the user herself set up. So ANY email from the pinned
    sender, inside the window and not already consumed by THIS
    flow, is actionable, full stop — there is no matching against
    the configured alert definitions (context for humans, never a
    filter) and no "unknown alert" refusal path. The only gates
    are: the pinned sender, the 24-hour window, and the shared
    processed pool (consumer scope "jobalert").

    Actionable items are NOT marked processed here — jobalert-
    record marks them, after the run has screened the email's
    jobs. Refusals ARE marked processed (jobalert consumer) in the
    same call — with ONE exception (Nov 13, 2026): a candidate
    carrying no extractable material at all (no links, no html,
    no LinkedIn URL in its body) was never read in full; it is
    refused with "consumed": false and NOT marked processed, so
    the run can re-read the email and re-feed it. Raises
    ValueError on a malformed batch (nothing written)."""
    if isinstance(candidates, dict):
        candidates = candidates.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("jobalert-intake needs a non-empty JSON "
                         "list of candidate job-alert emails")
    now = now or datetime.now(CT)
    cfg = _inbox_cfg(rules_path)
    search = cfg.get("jobalert_search") or {}
    window = timedelta(minutes=int(search.get("window_minutes")
                                   or 720))
    skew = timedelta(minutes=int(cfg.get("future_skew_minutes", 5)))
    state = load_state(state_path, md_path)
    processed = state["processed"]
    instructions = _jobalert_instructions(cfg)
    applied_companies = _applied_companies(rules_path)

    actionable, refused = [], []
    seen_in_batch: set = set()
    dirty = False
    for cand in candidates:
        if not isinstance(cand, dict):
            refused.append({"gmail_id": None,
                            "reason": "candidate is not a JSON object"})
            continue
        mid = cand.get("gmail_id") or ""
        label = {"gmail_id": mid or None}
        reason = None
        no_consume = False
        if not _GMAIL_ID_RE.fullmatch(mid or ""):
            reason = f"bad gmail_id: {mid!r}"
        elif _consumed(processed, mid, "jobalert"):
            reason = ("already processed for the job-alert flow "
                      "(duplicate Gmail ID)")
        elif mid in seen_in_batch:
            reason = "duplicate within this intake batch"
        else:
            received = parse_dt(cand.get("date"))
            if received is None:
                reason = f"unparseable date: {cand.get('date')!r}"
            elif received < now - window:
                reason = (f"stale: received {_ct_stamp(received)}, "
                          f"older than the past-"
                          f"{int(window.total_seconds() // 60)}-minute "
                          f"window (cutoff {_ct_stamp(now - window)})")
            elif received > now + skew:
                reason = (f"dated in the future: {_ct_stamp(received)} "
                          f"(beyond the {int(skew.total_seconds() // 60)}"
                          f"-minute skew allowance)")
            elif not _job_alert_sender(cand, cfg):
                pinned = ((cfg.get("job_alert_sender") or {})
                          .get("from_address")
                          or "jobalerts-noreply@linkedin.com")
                reason = ("not from the pinned job-alert sender "
                          f"({pinned} is the only job-alert sender — "
                          "identification is sender-only, the subject "
                          "is never consulted; got "
                          f"{_sender_address(cand.get('sender') or '')!r})")
            if reason is None and _no_extractable_material(cand):
                reason = ("candidate carries no links and no html "
                          "and no LinkedIn URL in its body — the "
                          "email was not read in full, so no job "
                          "links can be extracted from it; re-read "
                          "the email in full (body, links, html) "
                          "and re-feed it")
                no_consume = True
        if mid:
            seen_in_batch.add(mid)
        if reason:
            refused_entry = dict(label, reason=reason)
            if no_consume:
                refused_entry["consumed"] = False
            refused.append(refused_entry)
            if not no_consume and \
                    _GMAIL_ID_RE.fullmatch(mid or "") and \
                    not _consumed(processed, mid, "jobalert"):
                _mark_processed(state, mid,
                                {"at": now.isoformat(),
                                 "via": "jobalert-intake",
                                 "outcome": "refused", "reason": reason},
                                consumer="jobalert")
                dirty = True
            continue
        jobs, see_all = extract_job_links(cand)
        entry = {"gmail_id": mid,
                 "received_at": parse_dt(cand.get("date"))
                 .astimezone(CT).isoformat(),
                 "jobs": jobs, "see_all_url": see_all,
                 "instructions": instructions,
                 "applied_companies": applied_companies}
        if not jobs and see_all is None:
            entry["jobs_note"] = (
                "no LinkedIn job links and no 'See all jobs' link "
                "were extracted from this email — open the email's "
                "own links manually. The alert-email format is only "
                "partly sampled (one sample, Nov 12, 2026): check "
                "the first real samples against this extractor.")
        elif not jobs:
            entry["jobs_note"] = (
                "no individual job links extracted — work the "
                "See-all-jobs list (see_all_url) under the "
                "instructions")
        elif see_all is None:
            entry["see_all_note"] = (
                "no 'See all jobs' link extracted — work the "
                "individual job links above")
        actionable.append(entry)
    if dirty:
        save_state(state, state_path)
    return {"generated_at": now.isoformat(),
            "window_minutes": int(window.total_seconds() // 60),
            "cutoff": (now - window).astimezone(CT).isoformat(),
            "actionable": actionable, "refused": refused}


def jobalert_record(results, now: datetime | None = None,
                    state_path: Path = STATE_PATH,
                    md_path: Path = WATCH_MD_PATH) -> dict:
    """Record job-alert screening outcomes: per result, validate
    and mark the Gmail ID processed in the shared pool under the
    JOBALERT consumer stamp (the inbox flows' stamps are untouched
    — neither flow can starve the other). No claims-ledger lines
    and no outreach-log lines: the jobs the run found are recorded
    through stock.py as usual; this record only closes the email.
    A replay (already consumed by the alert flow) is refused —
    nothing is written twice."""
    if isinstance(results, dict):
        results = results.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("jobalert-record needs a non-empty JSON "
                         "list of results")
    now = now or datetime.now(CT)
    state = load_state(state_path, md_path)

    recorded, refused = [], []
    for res in results:
        label = {"gmail_id": res.get("gmail_id")
                 if isinstance(res, dict) else None}
        if not isinstance(res, dict):
            refused.append(dict(label,
                                reason="result is not a JSON object"))
            continue
        outcome = res.get("outcome") or ""
        mid = res.get("gmail_id") or ""
        problem = None
        if outcome not in JOBALERT_OUTCOMES:
            problem = (f"outcome must be one of {JOBALERT_OUTCOMES}; "
                       f"got {outcome!r}")
        elif not _GMAIL_ID_RE.fullmatch(mid or ""):
            problem = f"bad gmail_id: {mid!r}"
        elif _consumed(state["processed"], mid, "jobalert"):
            problem = (f"gmail_id {mid} is already processed for the "
                       f"job-alert flow — a replay records nothing "
                       f"twice")
        if problem:
            refused.append(dict(label, reason=problem))
            continue
        _mark_processed(state, mid,
                        {"at": now.isoformat(),
                         "via": "jobalert-record", "outcome": outcome},
                        consumer="jobalert")
        save_state(state, state_path)
        landed_state = load_state(state_path, md_path)
        landed = {"processed": _consumed(landed_state["processed"],
                                         mid, "jobalert")}
        problems = [f"the {k} did not land on read-back"
                    for k, v in landed.items() if v is False]
        entry_out = dict(label, outcome=outcome, landed=landed,
                         verified=not problems)
        if problems:
            entry_out["problems"] = problems
        recorded.append(entry_out)
    return {"recorded": recorded, "refused": refused}


# -------------------------------------------------------------- watch intake

def watch_intake(candidates, now: datetime | None = None,
                 state_path: Path = STATE_PATH,
                 rules_path: Path = RULES_PATH,
                 md_path: Path = WATCH_MD_PATH) -> dict:
    """Validate the watch's Gmail finds. Returns {actionable,
    refused} — refusals are recorded processed in the same call;
    actionable items are NOT (watch-record marks them, after the run
    has handled them). Raises ValueError on a malformed batch
    (nothing written)."""
    if isinstance(candidates, dict):
        candidates = candidates.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("intake needs a non-empty JSON list of "
                         "candidate notification emails")
    now = now or datetime.now(CT)
    cfg = _inbox_cfg(rules_path)
    window = timedelta(minutes=int(cfg.get("past_hour_window_minutes",
                                           60)))
    skew = timedelta(minutes=int(cfg.get("future_skew_minutes", 5)))
    state = load_state(state_path, md_path)
    processed = state["processed"]

    actionable, refused = [], []
    seen_in_batch: set[str] = set()
    dirty = False
    for cand in candidates:
        if not isinstance(cand, dict):
            refused.append({"gmail_id": None,
                            "reason": "candidate is not a JSON object"})
            continue
        mid = cand.get("gmail_id") or ""
        label = {"gmail_id": mid or None,
                 "subject": cand.get("subject") or ""}
        reason = None
        if not _GMAIL_ID_RE.fullmatch(mid or ""):
            reason = f"bad gmail_id: {mid!r}"
        elif _consumed(processed, mid, "inbox"):
            reason = "already processed (duplicate Gmail ID)"
        elif mid in seen_in_batch:
            reason = "duplicate within this intake batch"
        else:
            received = parse_dt(cand.get("date"))
            if received is None:
                reason = f"unparseable date: {cand.get('date')!r}"
            elif received < now - window:
                reason = (f"stale: received {_ct_stamp(received)}, "
                          f"older than the past-"
                          f"{int(window.total_seconds() // 60)}-minute "
                          f"window (cutoff {_ct_stamp(now - window)})")
            elif received > now + skew:
                reason = (f"dated in the future: {_ct_stamp(received)} "
                          f"(beyond the {int(skew.total_seconds() // 60)}"
                          f"-minute skew allowance)")
            else:
                reason = _triage(cand, cfg)
        if mid:
            seen_in_batch.add(mid)
        if reason:
            entry = dict(label, reason=reason)
            refused.append(entry)
            # Refusals are recorded processed NOW (they never
            # resurface) — but a bad-ID entry has no ID to record.
            if _GMAIL_ID_RE.fullmatch(mid or "") and \
                    not _consumed(processed, mid, "inbox"):
                _entry = {"at": now.isoformat(),
                          "via": "watch-intake",
                          "outcome": "refused", "reason": reason}
                if _job_alert_sender(cand, cfg):
                    _entry["classification"] = "job_alert"
                _mark_processed(state, mid, _entry, consumer="inbox")
                dirty = True
            continue
        person, parsed = _parse_person(cand.get("subject") or "",
                                       cand.get("sender") or "", cfg)
        entry = {"gmail_id": mid, "person": person,
                 "person_parsed": parsed,
                 "received_at": parse_dt(cand.get("date"))
                 .astimezone(CT).isoformat(),
                 "thread_url": extract_thread_url(cand)}
        if entry["thread_url"] is None:
            entry["thread_url_note"] = (
                "no 'View message' link found in this email — locate "
                "the conversation in LinkedIn Messaging by the "
                "person's name")
        actionable.append(entry)
    if dirty:
        save_state(state, state_path)
    return {"generated_at": now.isoformat(),
            "window_minutes": int(window.total_seconds() // 60),
            "cutoff": (now - window).astimezone(CT).isoformat(),
            "actionable": actionable, "refused": refused}


# ------------------------------------------------------------------- record

def _record_results(results, job: str, with_gmail: bool,
                    now: datetime | None = None,
                    log_path: Path = LOG_PATH,
                    claims_path: Path = CLAIMS_PATH,
                    state_path: Path = STATE_PATH,
                    md_path: Path = WATCH_MD_PATH) -> dict:
    """Shared record step for both jobs: per result, validate, write
    the claims-ledger line, mark the Gmail ID processed (watch
    only), write the outreach-log skeleton, and verify by read-back.
    A per-entry refusal writes nothing for that entry."""
    if isinstance(results, dict):
        results = results.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("record needs a non-empty JSON list of results")
    now = now or datetime.now(CT)
    state = load_state(state_path, md_path)
    claims_text = Path(claims_path).read_text(encoding="utf-8") \
        if Path(claims_path).exists() else ""

    recorded, refused = [], []
    for res in results:
        label = {"gmail_id": res.get("gmail_id") if isinstance(res, dict)
                 else None,
                 "person": res.get("person") if isinstance(res, dict)
                 else None}
        if not isinstance(res, dict):
            refused.append(dict(label, reason="result is not a JSON object"))
            continue
        person = (res.get("person") or "").strip()
        outcome = res.get("outcome") or ""
        mid = res.get("gmail_id") or ""
        problem = None
        if not person:
            problem = "missing required field: person"
        elif outcome not in OUTCOMES:
            problem = f"outcome must be one of {OUTCOMES}; got {outcome!r}"
        elif with_gmail and not _GMAIL_ID_RE.fullmatch(mid or ""):
            problem = f"bad gmail_id: {mid!r}"
        elif with_gmail and _consumed(state["processed"], mid, "inbox"):
            problem = (f"gmail_id {mid} is already processed — a replay "
                       f"records nothing twice")
        key = _build_claim_key(res) if not problem else ""
        if not problem and _norm(key) in _norm(claims_text):
            problem = ("this thread action is already in the claims "
                       "ledger — the first claim owns it; nothing "
                       "written")
        if problem:
            refused.append(dict(label, reason=problem))
            continue

        status = _STATUS_BY_OUTCOME[outcome]
        claim_line = _append_claim(claims_path, key, job, status, now)
        claims_text = Path(claims_path).read_text(encoding="utf-8")
        scope_txt = "email watch" if with_gmail else "daily check"
        id_txt = f" — Gmail {mid}" if with_gmail else ""
        log_line = log_writer.append_entry(
            str(log_path),
            f"LINKEDIN INBOX ({scope_txt}) — {person} — outcome: "
            f"{outcome}{id_txt} — claim recorded in "
            f"inbox-action-claims.md by {job}. {MARKER}", when=now)
        handled = {"person": person, "outcome": outcome, "job": job,
                   "claim_key": key, "at": now.isoformat(),
                   "message_ts": res.get("message_ts")}
        if with_gmail:
            _mark_processed(state, mid,
                            {"at": now.isoformat(), "via": "watch-record",
                             "outcome": outcome, "person": person},
                            consumer="inbox")
            handled["gmail_id"] = mid
        state["handled"].append(handled)
        save_state(state, state_path)

        # THE HANDOFF CHECK: read all three records back fresh.
        landed_claims = Path(claims_path).read_text(encoding="utf-8")
        landed_state = load_state(state_path, md_path)
        landed_log = Path(log_path).read_text(encoding="utf-8") \
            if Path(log_path).exists() else ""
        landed = {"claim": claim_line in landed_claims,
                  "log_entry": log_line in landed_log,
                  "processed": (mid in landed_state["processed"])
                  if with_gmail else None}
        problems = [f"the {k} did not land on read-back"
                    for k, v in landed.items() if v is False]
        entry_out = dict(label, outcome=outcome, claim_key=key,
                         status=status, claim_line=claim_line,
                         log_line=log_line, landed=landed,
                         verified=not problems)
        if problems:
            entry_out["problems"] = problems
        recorded.append(entry_out)
    return {"recorded": recorded, "refused": refused}


def watch_record(results, **kw) -> dict:
    return _record_results(results, WATCH_JOB, with_gmail=True, **kw)


def daily_record(results, **kw) -> dict:
    return _record_results(results, DAILY_JOB, with_gmail=False, **kw)


# -------------------------------------------------------------- daily scope

def daily_scope(now: datetime | None = None,
                claims_path: Path = CLAIMS_PATH,
                state_path: Path = STATE_PATH,
                rules_path: Path = RULES_PATH,
                md_path: Path = WATCH_MD_PATH) -> dict:
    """The daily check's scope as data: the 24-hour cutoff plus the
    stand_down list — every thread already claimed in the ledger or
    handled by the email watch whose message sits inside the
    window. The run works only conversations at/after the cutoff
    and stands down on the listed threads."""
    now = now or datetime.now(CT)
    cfg = _inbox_cfg(rules_path)
    hours = int(cfg.get("daily_check_window_hours", 12))
    cutoff = now - timedelta(hours=hours)
    stand_down = []
    for entry in _claim_entries(claims_path):
        if entry["ts"] and entry["ts"] >= cutoff:
            stand_down.append({"person": entry["person"],
                               "claim_key": entry["line"],
                               "status": entry["status"],
                               "source": "claims_ledger"})
    state = load_state(state_path, md_path)
    seen_persons = {_norm(s["person"]) for s in stand_down}
    for h in state.get("handled", []):
        ts = parse_dt(h.get("message_ts")) or parse_dt(h.get("at"))
        if ts and ts >= cutoff and \
                _norm(h.get("person") or "") not in seen_persons:
            stand_down.append({"person": h.get("person"),
                               "claim_key": h.get("claim_key"),
                               "status": h.get("outcome"),
                               "source": "email_watch"})
            seen_persons.add(_norm(h.get("person") or ""))
    return {"generated_at": now.astimezone(CT).isoformat(),
            "cutoff": cutoff.astimezone(CT).isoformat(),
            "window_hours": hours, "stand_down": stand_down}


# ------------------------------------------------------------ daily finish

_DAILY_FINISH_SPEC = {
    "conversations": ("in_scope", "replied", "no_reply", "wu_decision"),
    "invitations": ("found", "accepted", "skipped"),
    "alerts": ("found", "screened"),
}

# NOT-ON-REVELIO FALLBACK LEDGER (the user, Nov 13, 2026 — "when a
# company cannot be found on Revelio, vet through LinkedIn
# company profile: headcount, Indian employee count. Burn this
# in code."): the daily run must name every company the alert
# pass wrote off as not on Revelio in the summary's
# "alerts_not_on_revelio" list, with the resolution of the
# mandatory LinkedIn fallback — and daily_finish VERIFIES each
# named company's fallback against the parsed outreach log
# before writing anything. Before this existed, the alert run
# could write such a company off in its own notes (AZX, Evlo
# AI, FDE Times, Superworq — Nov 13, 2026) without ever running
# the fallback or recording anything through stock.py; no code
# checkpoint fired because those candidates never reached
# stock.py. Now the finish itself is the checkpoint.
_FALLBACK_RESOLUTIONS = ("linkedin_packet", "linkedin_no_counts")
_NO_REVELIO_DROP_PHRASE = ("not found on Revelio and the LinkedIn "
                           "fallback check gave no usable counts")


def _company_mentioned(text: str, company_norm: str) -> bool:
    """True when the company name appears in text as a whole
    phrase (both sides normalized with state.normalize_company,
    so case and punctuation never matter)."""
    if not company_norm:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(company_norm)
                     + r"(?![a-z0-9])",
                     state_mod.normalize_company(text)) is not None


def _fallback_on_record(log_state, company: str,
                        resolution: str) -> bool:
    """Is the LinkedIn fallback for a not-on-Revelio company on
    record in the parsed outreach log?

    "linkedin_packet": stock.py's gate entries for a fallback
    packet name the source — "GATE PASS — #id Company —
    LinkedIn People: #id Company total / india (pct%)" on a
    pass, "... per LinkedIn People" on a hard pass — and a
    hard-pass block also lands in the Blocked companies
    section as a note carrying the same counts. Any log entry
    naming both the company and "LinkedIn People" is that
    record.

    "linkedin_no_counts": stock.py's DROPPED_NO_REVELIO record
    — the item's SKIPPED entry carrying the drop phrase
    ("... not found on Revelio and the LinkedIn fallback
    check gave no usable counts — dropped ...")."""
    norm = state_mod.normalize_company(company)
    if not norm:
        return False
    if resolution == "linkedin_packet":
        for entry in log_state.entries:
            text = f"{entry.head} {entry.body}"
            if "LinkedIn People" in text and \
                    _company_mentioned(text, norm):
                return True
        return False
    for item in log_state.items.values():
        if not item.company or \
                state_mod.normalize_company(item.company) != norm:
            continue
        for ev in item.events:
            if ev[2] == "skipped" and \
                    _NO_REVELIO_DROP_PHRASE in (ev[3] or ""):
                return True
    for entry in log_state.entries:
        if entry.body.startswith("SKIPPED") and \
                _NO_REVELIO_DROP_PHRASE in entry.body and \
                _company_mentioned(entry.body, norm):
            return True
    return False


def _validate_not_on_revelio(summary: dict, alerts_found: int,
                             log_path) -> tuple[list, list]:
    """(clean entries, problems) for the summary's
    "alerts_not_on_revelio" ledger. The field is REQUIRED (an
    empty list is fine) whenever alert emails were found; each
    entry is {"company": str, "resolution":
    "linkedin_packet" | "linkedin_no_counts"}, and every named
    company is verified against the parsed outreach log — a
    fallback that exists only in the run's notes is not a
    fallback, and the finish is refused until the packet (or
    the linkedin_checked drop) is recorded through stock.py."""
    raw = summary.get("alerts_not_on_revelio")
    if raw is None:
        if alerts_found > 0:
            return [], [(
                "alerts_not_on_revelio is required when alert "
                "emails were found: list every company the "
                "alert pass wrote off as not on Revelio as "
                "{\"company\": ..., \"resolution\": "
                "\"linkedin_packet\" | \"linkedin_no_counts\"} "
                "(an empty list when none were)")]
        return [], []
    if not isinstance(raw, list):
        return [], [f"alerts_not_on_revelio must be a list; "
                    f"got {type(raw).__name__}"]
    problems: list = []
    clean: list = []
    for ent in raw:
        if not isinstance(ent, dict):
            problems.append(
                "alerts_not_on_revelio entries must be objects "
                f"with company + resolution; got {ent!r}")
            continue
        company = ent.get("company")
        resolution = ent.get("resolution")
        if not isinstance(company, str) or not company.strip():
            problems.append(
                "alerts_not_on_revelio entry needs a non-empty "
                f"\"company\"; got {ent!r}")
            continue
        if resolution not in _FALLBACK_RESOLUTIONS:
            problems.append(
                f"alerts_not_on_revelio[{company.strip()!r}]: "
                f"resolution must be one of "
                f"{list(_FALLBACK_RESOLUTIONS)}; got "
                f"{resolution!r}")
            continue
        clean.append({"company": company.strip(),
                      "resolution": resolution})
    if problems or not clean:
        return clean, problems
    log_state = state_mod.parse_log(str(log_path)) \
        if Path(log_path).exists() else None
    missing = [ent["company"] for ent in clean
               if log_state is None
               or not _fallback_on_record(log_state,
                                          ent["company"],
                                          ent["resolution"])]
    if missing:
        problems.append(
            "not-on-Revelio fallback NOT on record for: "
            + ", ".join(missing)
            + " — for each one, run the LinkedIn fallback "
            "(open the company's LinkedIn People page; read "
            "the TOTAL headcount first, then the India-"
            "location employee count) and record it through "
            "stock.py — the fallback gate packet (source "
            "\"LinkedIn People\", revelio_not_found: true) "
            "when LinkedIn gives usable counts, or the drop "
            "with gate {\"revelio_not_found\": true, "
            "\"linkedin_checked\": true} when it does not — "
            "then finish again (the user, Nov 13, 2026: a company "
            "not on Revelio is vetted on LinkedIn, in code — "
            "never written off in run notes)")
    return clean, problems


def daily_finish(summary, now: datetime | None = None,
                 log_path: Path = LOG_PATH,
                 fallback_state_path=None) -> dict:
    """The daily check's completion record, in code (the user, Nov 13,
    2026 — "fix these in code"): the run hands in its counts as
    data and THIS function writes the run line to the outreach
    log. The summary must account for ALL THREE parts of the job
    — conversations, invitations, AND job alerts — with every
    count present, and no handled count above its found /
    in-scope count; anything missing or inconsistent refuses the
    whole summary (ValueError, nothing written), so a run cannot
    finish, or silently skip a part, without the record showing
    it. Before this existed, the outreach log only ever learned
    about handled items (via the record steps), so a clean run
    left no trace and the daily watchdog could not tell "ran,
    found nothing" from "never ran".

    The summary also carries the not-on-Revelio fallback ledger
    (the user, Nov 13, 2026): "alerts_not_on_revelio" names every
    company the alert pass wrote off as not on Revelio, with
    the resolution of its mandatory LinkedIn fallback
    ("linkedin_packet" / "linkedin_no_counts"). The field is
    required whenever alert emails were found, and each named
    company is verified against the parsed outreach log (see
    _validate_not_on_revelio) — an unverified name refuses the
    whole summary, so the daily run cannot close over an
    unvetted not-on-Revelio company. The finish also consults
    the tracked fallback state (gate_fallback): a fallback
    order code opened the same day that is still open refuses
    the finish outright — the tracked state is the stronger
    source, and the two checks must agree before the run line
    is written."""
    if isinstance(summary, dict) and isinstance(
            summary.get("summary"), dict):
        summary = summary["summary"]
    if not isinstance(summary, dict):
        raise ValueError("daily-finish needs a JSON object with "
                         "conversations, invitations and alerts "
                         "sections")
    problems: list = []
    clean: dict = {}
    for section, fields in _DAILY_FINISH_SPEC.items():
        part = summary.get(section)
        if not isinstance(part, dict):
            problems.append(f"missing section: {section}")
            continue
        clean[section] = {}
        for field in fields:
            value = part.get(field)
            if isinstance(value, bool) or not isinstance(value, int):
                problems.append(
                    f"{section}.{field} must be an integer count; "
                    f"got {value!r}")
            elif value < 0:
                problems.append(
                    f"{section}.{field} must be >= 0; got {value}")
            else:
                clean[section][field] = value
    if not problems:
        conv = clean["conversations"]
        if (conv["replied"] + conv["no_reply"] + conv["wu_decision"]
                > conv["in_scope"]):
            problems.append(
                "conversations: replied + no_reply + wu_decision "
                "exceeds in_scope")
        inv = clean["invitations"]
        if inv["accepted"] + inv["skipped"] > inv["found"]:
            problems.append(
                "invitations: accepted + skipped exceeds found")
        if clean["alerts"]["screened"] > clean["alerts"]["found"]:
            problems.append("alerts: screened exceeds found")
    not_on_revelio: list = []
    if not problems:
        not_on_revelio, nr_problems = _validate_not_on_revelio(
            summary, clean["alerts"]["found"], log_path)
        problems.extend(nr_problems)
    if not problems:
        # THE TRACKED STATE IS THE STRONGER SOURCE (the user,
        # Nov 13, 2026 — the code step between Revelio and
        # LinkedIn): any fallback order code opened during this
        # run's alert pass (same America/Chicago date) that is
        # still open means a LinkedIn check was ordered and
        # never recorded — the day cannot close over it, even
        # when the summary's own naming is clean.
        finish_now = now or datetime.now(CT)
        owed = gate_fallback_mod.pending_opened_on(
            finish_now.date(), state_path=fallback_state_path)
        if owed:
            problems.append(
                "LinkedIn fallback still owed for: "
                + ", ".join(rec["company"] for rec in owed)
                + " — code opened a fallback order for each "
                "during this run's alert pass and no LinkedIn "
                "packet or linkedin_checked drop has been "
                "recorded through stock.py; run the check on "
                "code's order (LinkedIn People page: total "
                "headcount first, then the India count), record "
                "it, then finish")
    if problems:
        raise ValueError("daily-finish summary refused — "
                         + "; ".join(problems))
    now = now or datetime.now(CT)
    conv, inv, al = (clean["conversations"], clean["invitations"],
                     clean["alerts"])
    note = summary.get("note")
    note = note.strip() if isinstance(note, str) else ""
    handled = (conv["replied"] + conv["wu_decision"]
               + inv["accepted"] + al["screened"])
    if note:
        tail = note
    elif handled == 0:
        tail = "nothing handled"
    else:
        tail = "run complete"
    line = log_writer.append_entry(
        str(log_path),
        f"Daily inbox check ({DAILY_JOB}) — in-scope conversations "
        f"{conv['in_scope']} (replied {conv['replied']}, no-reply "
        f"{conv['no_reply']}, the user-decision {conv['wu_decision']}); "
        f"invitation emails {inv['found']} (accepted "
        f"{inv['accepted']}, skipped {inv['skipped']}); alert "
        f"emails {al['found']} (screened {al['screened']}) — "
        f"{tail}. {MARKER}", when=now)
    landed_log = Path(log_path).read_text(encoding="utf-8") \
        if Path(log_path).exists() else ""
    return {"line": line, "verified": line in landed_log,
            "summary": clean,
            "alerts_not_on_revelio": not_on_revelio}


# ---------------------------------------------------------------------- CLI

def _load_json_file(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(prog="inbox.py")
    ap.add_argument("command", choices=["format", "watch-intake",
                                        "watch-record", "daily-scope",
                                        "daily-record", "daily-finish",
                                        "check-claim",
                                        "invite-intake", "invite-record",
                                        "jobalert-intake",
                                        "jobalert-record"])
    ap.add_argument("file", nargs="?", help="JSON file (intake/record)")
    ap.add_argument("--person", default=None)
    ap.add_argument("--message-ts", default=None)
    ap.add_argument("--claim-key", default="")
    ap.add_argument("--now", default=None,
                    help="ISO timestamp to use as 'now' (testing)")
    ap.add_argument("--log", default=None)
    ap.add_argument("--claims", default=None)
    ap.add_argument("--state", default=None)
    args = ap.parse_args()
    log_path = Path(args.log) if args.log else LOG_PATH
    claims_path = Path(args.claims) if args.claims else CLAIMS_PATH
    state_path = Path(args.state) if args.state else STATE_PATH
    now = parse_dt(args.now) if args.now else None
    if args.now and now is None:
        print(json.dumps({"ok": False,
                          "refused": f"unparseable --now: {args.now!r}"}))
        return 2
    try:
        if args.command == "format":
            print(FORMAT_TEXT)
            return 0
        if args.command == "watch-intake":
            if not args.file:
                print("watch-intake needs a candidates JSON file",
                      file=sys.stderr)
                return 1
            out = watch_intake(_load_json_file(args.file), now=now,
                               state_path=state_path)
            print(json.dumps(out, indent=1))
            return 0
        if args.command == "watch-record":
            if not args.file:
                print("watch-record needs a results JSON file",
                      file=sys.stderr)
                return 1
            out = watch_record(_load_json_file(args.file), now=now,
                               log_path=log_path, claims_path=claims_path,
                               state_path=state_path)
            print(json.dumps(out, indent=1))
            return 0
        if args.command == "daily-scope":
            out = daily_scope(now=now, claims_path=claims_path,
                              state_path=state_path)
            print(json.dumps(out, indent=1))
            return 0
        if args.command == "daily-record":
            if not args.file:
                print("daily-record needs a results JSON file",
                      file=sys.stderr)
                return 1
            out = daily_record(_load_json_file(args.file), now=now,
                               log_path=log_path, claims_path=claims_path,
                               state_path=state_path)
            print(json.dumps(out, indent=1))
            return 0
        if args.command == "daily-finish":
            if not args.file:
                print("daily-finish needs a summary JSON file",
                      file=sys.stderr)
                return 1
            out = daily_finish(_load_json_file(args.file), now=now,
                               log_path=log_path)
            print(json.dumps(out, indent=1))
            return 0
        if args.command == "check-claim":
            if not args.person:
                print("check-claim needs --person", file=sys.stderr)
                return 1
            out = check_claim(args.person, args.message_ts,
                              args.claim_key, claims_path)
            print(json.dumps(out, indent=1))
            return 0
        if args.command == "invite-intake":
            if not args.file:
                print("invite-intake needs a candidates JSON file",
                      file=sys.stderr)
                return 1
            out = invite_intake(_load_json_file(args.file), now=now,
                                state_path=state_path)
            print(json.dumps(out, indent=1))
            return 0
        if args.command == "invite-record":
            if not args.file:
                print("invite-record needs a results JSON file",
                      file=sys.stderr)
                return 1
            out = invite_record(_load_json_file(args.file), now=now,
                                log_path=log_path, state_path=state_path)
            print(json.dumps(out, indent=1))
            return 0
        if args.command == "jobalert-intake":
            if not args.file:
                print("jobalert-intake needs a candidates JSON file",
                      file=sys.stderr)
                return 1
            out = jobalert_intake(_load_json_file(args.file), now=now,
                                  state_path=state_path)
            print(json.dumps(out, indent=1))
            return 0
        if args.command == "jobalert-record":
            if not args.file:
                print("jobalert-record needs a results JSON file",
                      file=sys.stderr)
                return 1
            out = jobalert_record(_load_json_file(args.file), now=now,
                                  state_path=state_path)
            print(json.dumps(out, indent=1))
            return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "refused": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
