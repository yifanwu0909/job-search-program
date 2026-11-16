"""events.py — the functional log: append-only structured events.

One compact dictionary per line in events.jsonl — ONLY the most important
info (the user, Nov 4, 2026: "Don't make the log wordy or complicated. Think
dictionary or tuple. Only store the most important info."):

    {"ts": <CT ISO>, "type": <event>, "item": <item #>,
     "src": <LINKEDIN|JOBRIGHT|INDEED|LINKEDIN_ALERT>, "win": <window date YYYY-MM-DD>}

Those are the only keys, ever: no actor, no company, no payload, no prose.
`src` is omitted on events with no source (e.g. friction_set); `item` and
`win` are omitted when they don't apply. The single allowed optional key
is "why" — a short code, ONLY on skipped / staged events. Anything richer
belongs in the prose outreach log, which stays the human record.

A CAPTCHA is its own event type (`captcha`) — a bot-check the user solves by
taking the browser, never a tap she grants — so it never rides inside
`staged` and never carries a `why`: the type says it all (the user, Nov 4,
2026: "Separate the tap situations and captcha").

A MANUAL PACKET is its own event type too (`packet`, the user, Nov 6, 2026):
an application Muse's browser cannot finish at all (Lever, Gem, an
IP-blocked captcha) that was handed to the user as a packet — apply link,
tailored resume, field values — for her to submit from her own device.
It supersedes a captcha/staged park at the same rank; a later submitted
event (recorded when the user reports her submission) settles it.

Principle (the user, Nov 4, 2026): when something happens, it is appended ONCE,
at the moment it happens, and every workflow reads from there. Notification
is a write, not a message. Writers append a single line and fsync; existing
lines are never edited or deleted. Readers fold the stream (see
state.fold_events) or page through it with a watermark (`since`).

INVITATION EVENTS (the user, Nov 10, 2026 — "handle the tracking in the
code"): connection invitations join the same book under their own
vocabulary (invite_sent / invite_backfill / invite_counter), written
ONLY through append_invite_event below, which validates each type's
own key set (INVITE_EVENT_KEYS). An invitation is not an application
item, so these events carry NO `item` key — state.fold_events skips
them by construction, and the application counts can never see them.
The prose outreach log remains the human record of who was invited;
the book is the count of record (see invitations.py).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from state import CT

EVENT_TYPES = (
    "stocked", "claimed", "submitted", "verified", "verification_missed",
    "limbo", "staged", "unstaged", "captcha", "packet", "skipped",
    "friction_set",
    "friction_cleared", "rule_changed", "correction",
    "invite_sent", "invite_backfill", "invite_counter",
)

# Invitation events (Nov 10, 2026): each type's OWN allowed keys, on top
# of {ts, type}. append_event (the application writer) never writes
# these types; append_invite_event is their only door, and it refuses
# any key outside the type's set.
INVITE_EVENT_KEYS = {
    # one verified send: who (person name), day (CT date of the send),
    # note (was a note attached); company / role when known; source —
    # required since Nov 14, 2026 (the user: ALL outreach comes from
    # contacto, burned into code; invitations._validate_send refuses
    # any send whose source is missing or not contacto).
    "invite_sent": {"who", "day", "note", "company", "role", "source"},
    # one aggregate day seeded by the backfill path: n sends on day,
    # marked as backfilled history (no person names exist for these).
    "invite_backfill": {"day", "n", "mark"},
    # one reading of LinkedIn's Sent-People counter: phase start|end of
    # a day's outreach run; mark == "backfill" on seeded readings.
    "invite_counter": {"day", "phase", "counter", "mark"},
}
INVITE_REQUIRED_KEYS = {
    "invite_sent": {"who", "day", "note", "source"},
    "invite_backfill": {"day", "n", "mark"},
    "invite_counter": {"day", "phase", "counter"},
}

SOURCES = ("LINKEDIN", "JOBRIGHT", "INDEED", "LINKEDIN_ALERT")
WHY_CODES = ("pay", "role", "gate", "dup", "closed", "card",
             "code", "id_doc", "other")
WHY_TYPES = ("skipped", "staged")
ALLOWED_KEYS = {"ts", "type", "item", "src", "win", "why"}

# Free text (a prose skip reason / staged blocker) -> compact why code.
# Ordered: the first rule whose keywords appear wins. The blocker-specific
# codes (id_doc / code / card) outrank pay / gate because staged prose
# often trails gate and pay notes after the actual blocker sentence;
# only the head of the text is examined for the same reason. There is NO
# captcha rule: a captcha blocker is recorded as a `captcha` event by the
# pipeline, never as a staged/skipped why.
_WHY_RULES = (
    ("id_doc", ("photo id", "government-issued", "government issued",
                "identity document", "driver's license", "drivers license",
                "passport upload")),
    ("code", ("code",)),
    ("card", ("card", "approval", "first-touch", "first touch")),
    ("pay", ("pay", "salary", "compensation", "cost-of-living",
             "cost of living", "equivalent")),
    ("gate", ("gate", "india")),
    ("dup", ("duplicat", "already applied", "already submitted")),
    ("closed", ("closed", "no longer", "not live", "expired", "filled",
                "posting gone", "removed")),
    ("role", ("role",)),
)


def why_code(text: str) -> str:
    """Map free-text detail to the closest compact why code ('other' when
    nothing matches). Used for skipped / staged events only. Only the
    first 160 chars are read: in staged prose the blocker is stated first
    and the gate / pay bookkeeping trails after it."""
    t = (text or "").lower()[:160]
    for code, keys in _WHY_RULES:
        if any(k in t for k in keys):
            return code
    return "other"


def stocked_path_for(events_path) -> Path:
    """The stocked-items data file for an event book (STOCKING AS
    DATA, the user, Nov 6, 2026): events.jsonl -> events.stocked.json;
    <stem>.events.jsonl -> <stem>.stocked.json. One rule, shared by
    stock.py (the writer) and pipeline.py (the reader), so the two
    can never derive different files."""
    p = Path(events_path)
    if p.name == "events.jsonl":
        return p.parent / "events.stocked.json"
    if p.name.endswith(".events.jsonl"):
        return p.parent / (p.name[: -len(".events.jsonl")]
                           + ".stocked.json")
    return p.parent / (p.stem + ".stocked.json")


def now_iso() -> str:
    return datetime.now(CT).isoformat()


def append_event(events_path, etype: str, item: int | None = None,
                 src: str | None = None, win: str | None = None,
                 why: str | None = None, ts: str | None = None) -> dict:
    """Append ONE minimal event line (write + flush + fsync). Returns it.

    The line carries exactly {ts, type} plus whichever of item / src / win
    apply, plus why on skipped / staged events. ts is injectable for
    backfills/tests; live writers leave it None so the stamp is the moment
    of the write."""
    if etype not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {etype}")
    if etype in INVITE_EVENT_KEYS:
        raise ValueError(f"{etype} is written by append_invite_event, "
                         f"not append_event")
    ev: dict = {"ts": ts or now_iso(), "type": etype}
    if item is not None:
        ev["item"] = int(item)
    if src:
        s = str(src).upper()
        if s not in SOURCES:
            raise ValueError(f"unknown event source: {src}")
        ev["src"] = s
    if win is not None:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(win)):
            raise ValueError(f"win must be YYYY-MM-DD, got: {win}")
        ev["win"] = str(win)
    if why is not None:
        if etype not in WHY_TYPES:
            raise ValueError(f"why is only allowed on {WHY_TYPES}, not {etype}")
        if why not in WHY_CODES:
            raise ValueError(f"unknown why code: {why}")
        ev["why"] = why
    p = Path(events_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return ev


def append_invite_event(events_path, etype: str, fields: dict,
                        ts: str | None = None) -> dict:
    """Append ONE invitation event line (write + flush + fsync) — the
    only writer for the invite_* types. `fields` must carry exactly the
    type's required keys plus any of its optional keys (INVITE_EVENT_KEYS
    / INVITE_REQUIRED_KEYS); anything else is refused before writing.
    The event carries no `item`, so state.fold_events ignores it."""
    if etype not in INVITE_EVENT_KEYS:
        raise ValueError(f"not an invitation event type: {etype}")
    fields = dict(fields or {})
    extra = set(fields) - INVITE_EVENT_KEYS[etype]
    if extra:
        raise ValueError(
            f"{etype} may not carry keys {sorted(extra)} "
            f"(allowed: {sorted(INVITE_EVENT_KEYS[etype])})")
    missing = INVITE_REQUIRED_KEYS[etype] - set(fields)
    if missing:
        raise ValueError(f"{etype} is missing required keys "
                         f"{sorted(missing)}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(fields["day"])):
        raise ValueError(f"day must be YYYY-MM-DD, got: {fields['day']}")
    ev: dict = {"ts": ts or now_iso(), "type": etype}
    ev.update(fields)
    p = Path(events_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return ev


def _parse_ts(raw) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=CT)


def read_events(events_path, since=None) -> list[dict]:
    """All events in file order. With `since` (ISO string or datetime),
    only events STRICTLY AFTER the watermark — the guardian-style read:
    a consumer stores the last ts it saw and asks for what is newer."""
    p = Path(events_path)
    if not p.exists():
        return []
    since_dt = _parse_ts(since) if since is not None else None
    out = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue  # a torn final line must never kill a reader
        if since_dt is not None:
            ets = _parse_ts(ev.get("ts"))
            if ets is None or ets <= since_dt:
                continue
        out.append(ev)
    return out
