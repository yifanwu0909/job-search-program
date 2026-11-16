"""state.py — parse the outreach log into structured state.

The outreach log REMAINS the authoritative record. This module is a pure,
deterministic reader: same log in -> same numbers out. It never writes.

Entry model (matched to the log's real shapes, sampled Nov 4, 2026):
  * An entry starts at a line beginning "- [<timestamp>] " or "Guardian [<ts>] ",
    plus the "- FINAL ACCOUNTING" / "- BATCH CLOSED" block lines. Any other line
    is a continuation of the previous entry.
  * Inside a multi-item entry, each item's SEGMENT runs from its "#NNN" mention
    to the next item's mention (or end of entry). Disposition keywords are read
    per segment; a single-item entry is one segment.
  * Summary heads (SEGMENT STATE/CLOSE/START, Guardian lines, hourly email
    scans, FINAL ACCOUNTING, audits) never create dispositions — they lag and
    sometimes contradict the per-item entries. Two summary lines are still mined
    for what only they carry: STARTING COUNTS (window attribution) and the
    READY BENCH / SEGMENT STATE bench hints (stocking + source).

PARSER CONTRACT (the user, Nov 5, 2026 — the #381/#49 fix; see README.md):
  * Outcomes are read ONLY from the canonical entry grammar the writers
    emit (log_writer / spine record / stock): either the entry HEAD begins
    with a token from the closed outcome vocabulary and binds that outcome
    to the entry's own subject item, or — in legacy multi-item entries —
    a segment that begins with the item's own "#NNN" carries the outcome
    token at the head of its first clause (right after the identity's
    " — " or ": " delimiter). Free text anywhere else (reasons, quotes,
    URLs, parentheticals, cross-references to other items, Guardian tally
    prose appended after an entry) is INERT: it never creates an outcome.
  * CORRECTION entries are annotations: never mined for outcomes, never
    create items — with ONE narrow exception for the log's own supersede
    mechanism: a correction that names a single subject in its head,
    explicitly supersedes a prior claim ("is superseded"), and asserts
    the corrected outcome as PAGE-CONFIRMED / EMAIL-VERIFIED binds that
    outcome for its subject (#198). A correction merely containing
    outcome words stays inert (#146).
  * SEGMENT STATE lines are hints only: they never create items,
    identities, or outcomes; a hint attaches only to an item a canonical
    entry already created.
  * An item has exactly ONE submission for window attribution: the FIRST
    submitted-format entry in the log owns the window; later ones never
    re-attribute it (EMAIL-VERIFIED catch-ups tie to that window).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")

# ---------------------------------------------------------------- timestamps
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def parse_ts(raw: str):
    """Best-effort parse of the log's timestamp shapes -> aware datetime in CT.

    HST- and UTC-stamped lines ARE parsed and converted (fix, Nov 5, 2026):
    the old None return let a summary entry's re-mention of an item become
    its last submitted event with no timestamp, and window_status requires
    a real ts — #250 Workday and #259 Anthropic silently dropped out of
    the prose verified count that way. Returns None only for stamps with
    no readable date or time."""
    if not raw:
        return None
    if "HST" in raw:
        src_tz = ZoneInfo("Pacific/Honolulu")
    elif "UTC" in raw:
        src_tz = ZoneInfo("UTC")
    else:
        src_tz = CT
    date = None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        date = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    else:
        m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+"
                      r"(\d{1,2}),\s+(\d{4})", raw)
        if m:
            date = (int(m.group(3)), _MONTHS[m.group(1)[:3]], int(m.group(2)))
    t = re.search(r"~?\s*(\d{1,2}):(\d{2})\s*([AP]M)", raw)
    if t:
        hour = int(t.group(1)) % 12 + (12 if t.group(3) == "PM" else 0)
        minute = int(t.group(2))
    elif src_tz is not CT:
        t = re.search(r"(\d{1,2}):(\d{2})", raw)  # 24h shape, e.g. 18:33 HST
        if not t:
            return None
        hour, minute = int(t.group(1)), int(t.group(2))
    else:
        return None
    if not date:
        return None
    try:
        return datetime(date[0], date[1], date[2], hour, minute,
                        tzinfo=src_tz).astimezone(CT)
    except ValueError:
        return None


def fmt_ts(dt: datetime) -> str:
    """House timestamp format: '2:36 PM CST, Wed Nov 4, 2026' (no zero-padding)."""
    dt = dt.astimezone(CT)
    return (f"{dt.strftime('%I:%M %p %Z').lstrip('0')}, "
            f"{dt.strftime('%a %b')} {dt.day}, {dt.year}")


# ------------------------------------------------------------------- entries
ENTRY_RE = re.compile(r"^- \[(?P<ts>[^\]]+)\]\s*(?P<body>.*)$")
GUARDIAN_RE = re.compile(r"^-?\s*Guardian \[(?P<ts>[^\]]+)\]\s*(?P<body>.*)$")
BLOCK_RE = re.compile(r"^- (?P<body>(FINAL ACCOUNTING|BATCH CLOSED).*)")
SECTION_RE = re.compile(
    r"^## (\d{4})-(\d{2})-(\d{2}) — LinkedIn Recommended applications batch — "
    r"(\d{4})-(\d{2})-(\d{2})")
ITEM_RE = re.compile(r"#(\d{2,4})\b")  # 4-digit ids from #1000 on (Nov 15, 2026: the {2,3} bound silently stopped segment mining at #999, so every stock from #1009 on collided on one number and never surfaced on the bench)


@dataclass
class Entry:
    line_no: int
    ts: datetime | None
    body: str
    guardian: bool = False   # Guardian lines are tallies/summaries, never evidence

    @property
    def head(self) -> str:
        return self.body[:90]


def split_entries(lines: list[str]) -> list[Entry]:
    entries: list[Entry] = []
    for i, raw in enumerate(lines, start=1):
        m = GUARDIAN_RE.match(raw)
        if m:
            entries.append(Entry(i, parse_ts(m.group("ts")), m.group("body"),
                                 guardian=True))
            continue
        m = ENTRY_RE.match(raw)
        if m:
            entries.append(Entry(i, parse_ts(m.group("ts")), m.group("body")))
            continue
        m = BLOCK_RE.match(raw)
        if m:
            entries.append(Entry(i, None, m.group("body")))
            continue
        if entries:  # continuation line
            entries[-1].body += "\n" + raw
    return entries


def _is_range_endpoint(body: str, pos: int) -> bool:
    """True when the #NNN mention at pos is part of a range like #164–#182
    (either the tail, checked before pos, or the head, checked after it)."""
    if re.search(r"#\d+\s*[–—-]\s*$", body[max(0, pos - 12):pos]):
        return True
    m = re.match(r"#\d+", body[pos:])
    if m and re.match(r"\s*[–—-]\s*#?\d", body[pos + m.end():pos + m.end() + 8]):
        return True
    return False


def segments(entry: Entry) -> list[tuple[int, str]]:
    """Split an entry into (item_id, segment_text) pairs.

    An item's segment runs from its FIRST mention to the next DISTINCT item's
    first mention (repeat mentions of the same item stay inside its segment).
    Range endpoints (#182 in '#164–#182') never open a segment."""
    first: dict[int, int] = {}
    for m in ITEM_RE.finditer(entry.body):
        iid = int(m.group(1))
        if iid not in first and not _is_range_endpoint(entry.body, m.start()):
            first[iid] = m.start()
    if not first:
        return []
    ordered = sorted(first.items(), key=lambda kv: kv[1])
    out = []
    for idx, (iid, pos) in enumerate(ordered):
        end = ordered[idx + 1][1] if idx + 1 < len(ordered) else len(entry.body)
        out.append((iid, entry.body[pos:end]))
    return out


def entry_prefix(entry: Entry) -> str:
    """Entry text before the first item mention — where the head keyword lives
    in shapes like 'SUBMITTED (page-confirmed) — #NNN ...'."""
    segs = segments(entry)
    if not segs:
        return entry.body
    first_pos = entry.body.find(f"#{segs[0][0]}")
    return entry.body[:first_pos] if first_pos >= 0 else ""


def _step_text(seg: str) -> str:
    """The 'step: ...' blocker text inside a segment ('' when absent)."""
    sm = re.search(r"step: ([^;]{3,180})", seg)
    return sm.group(1).strip() if sm else ""


# ------------------------------------------------------- outcome grammar
# The closed outcome vocabulary and the ONLY two positions it may be
# read from (parser contract, Nov 5, 2026):
#   HEAD — the entry body begins with the token; the outcome binds to
#          the entry's subject (defined per token below).
#   SEGMENT HEAD CLAUSE — in a legacy multi-item entry, a segment that
#          begins with the item's own "#NNN" carries the token at the
#          start of its first clause (right after the identity's
#          " — " or ": " delimiter).
# Anything else — reasons, quotes, URLs, parentheticals, tallies,
# cross-references — is inert text.

def _first_item_id(text: str):
    m = ITEM_RE.search(text)
    return int(m.group(1)) if m else None


def _submitted_detail(text: str) -> str:
    detail = []
    if "page-confirmed" in text.lower():
        detail.append("page-confirmed")
    if "EMAIL-VERIFIED" in text.upper():
        detail.append("email-verified")
    return "; ".join(detail) or "submitted"


def _head_outcome(entry: Entry):
    """(kind, subject_id, detail) when the entry HEAD carries an
    outcome token in its fixed position, else None.

    Subject rule: the writers put the identity immediately after the
    outcome clause, so the subject is the FIRST #id in the body — for
    SUBMITTED / EMAIL-VERIFIED / STAGED / AWAITING / UNSTAGED /
    IN LIMBO / POST-SUBMIT / CLAIM / SKIP heads. SKIPPED is the one
    exception: log_writer emits "SKIPPED — <reason> — #id Company,
    Role.", identity LAST, so the subject is the LAST "— #id" of the
    identity region (up to the spine marker, or the head zone)."""
    body = entry.body
    up = body.upper()
    first = _first_item_id(body)
    if first is None:
        return None
    prefix = body[:body.find(f"#{first}")] if f"#{first}" in body else ""

    def result(kind, detail=""):
        return (kind, first, detail)

    if up.startswith("AWAITING CAPTCHA TAKEOVER"):
        return result("captcha", _step_text(body)
                      or "awaiting captcha takeover (head)")
    if up.startswith("MANUAL PACKET"):
        return result("packet", _step_text(body)
                      or "manual packet handed to the user (head)")
    if up.startswith("STAGED FOR TAP SESSION"):
        if _captcha_step(body):
            return result("captcha", _step_text(body)
                          or "captcha at step (head)")
        return result("staged", "staged for tap session (head)")
    if up.startswith("POST-SUBMIT VALIDATION PENDING"):
        return result("post_submit_pending", "validation code demanded (head)")
    if up.startswith("EMAIL-VERIFIED"):
        return result("submitted", "email-verified")
    if up.startswith("SUBMITTED"):
        if "NOT SUBMITTED" in prefix.upper():
            return result("not_submitted", "entry states not submitted")
        detail = _submitted_detail(prefix)
        if "BY WU" in prefix.upper():
            detail += "; submitted by the user"
        return result("submitted", detail)
    if up.startswith("UNSTAGED"):
        return result("unstaged", "returned to bench (head)")
    if up.startswith("IN LIMBO"):
        return result("limbo", "uncertain outcome (head)")
    if up.startswith("SKIPPED"):
        marker = body.find("(Recorded by spine program.)")
        region = body[:marker] if marker >= 0 else body[:800]
        cands = re.findall(r"—\s*#(\d+)\b", region)
        subj = int(cands[-1]) if cands else first
        rm = re.search(r"SKIPPED\s*—\s*(.{3,200})", prefix or body)
        reason = (rm.group(1).strip().rstrip("—").strip()
                  if rm else "skipped")
        return ("skipped", subj, reason)
    if re.match(r"SKIP(\s|—|-)", up):
        return result("skipped", "skipped (head)")
    if up.startswith("CLAIM"):
        return result("claimed", entry.head[:60])
    return None


# Segment head-clause vocabulary, longest first so a token is never
# shadowed by its own prefix.
_SEGMENT_VOCAB = (
    ("NOT SUBMITTED", "not_submitted"),
    ("AWAITING CAPTCHA TAKEOVER", "captcha"),
    ("MANUAL PACKET", "packet"),
    ("STAGED FOR TAP SESSION", "staged"),
    ("POST-SUBMIT VALIDATION PENDING", "post_submit_pending"),
    ("EMAIL-VERIFIED", "submitted"),
    ("SUBMITTED", "submitted"),
    ("IN LIMBO", "limbo"),
    ("UNSTAGED", "unstaged"),
    ("SKIPPED", "skipped"),
)


def _segment_head_outcome(seg: str):
    """(kind, detail) when a segment that begins with the item's own
    "#NNN" carries an outcome token at the head of its first clause —
    the text right after the identity's first " — " or ": " delimiter
    (the first few delimiters are tried, so a label clause like
    "+10-MIN GMAIL CHECK (...): EMAIL-VERIFIED" still binds). Free text
    later in the segment is never consulted."""
    # The zone is TIGHT (Nov 13, 2026 — the #685 phantom): a legacy
    # segment disposition states its outcome immediately after the
    # identity; a "segment" that must travel hundreds of characters
    # of prose before reaching an outcome word is narrative about
    # other items, not this item's disposition.
    zone = seg[:160]
    delims = list(re.finditer(r" — |: ", zone))
    # Only the first TWO delimiter clauses are structural: the outcome
    # sits immediately after the identity (clause 1), or after one
    # short label clause (clause 2, e.g. "+10-MIN GMAIL CHECK (...):").
    # A token deeper in the segment is prose — session summary bullets
    # that carry an outcome word at clause 3+ have asserted submissions
    # the program's own audit entries contradict (#159, Nov 4, 2026).
    for m in delims[:2]:
        clause = zone[m.end():m.end() + 48].strip()
        up = clause.upper()
        for token, kind in _SEGMENT_VOCAB:
            if up.startswith(token):
                if kind == "submitted":
                    near = zone[m.start():m.end() + 120]
                    return (kind, _submitted_detail(near))
                if kind == "staged":
                    if _captcha_step(seg):
                        return ("captcha", _step_text(seg)
                                or "captcha at step")
                    return (kind, _step_text(seg)
                            or "staged for tap session")
                if kind == "captcha":
                    return (kind, _step_text(seg)
                            or "awaiting captcha takeover")
                return (kind, token.lower())
        # Plus-joined outcome idiom in the head clause: "#136 Zoom —
        # CREDENTIAL TEST PASSED + SUBMITTED (page-confirmed; ...)".
        pm = re.search(r"\+\s*(EMAIL-VERIFIED|SUBMITTED)\b",
                       zone[m.end():m.end() + 120])
        if pm:
            det = _submitted_detail(zone[m.start():m.end() + 120])
            return ("submitted",
                    "email-verified" if pm.group(1) == "EMAIL-VERIFIED"
                    else det)
    return None


def _captcha_step(seg: str) -> bool:
    """True when a segment's blocker is a CAPTCHA: the entry parks the item
    as AWAITING CAPTCHA TAKEOVER, or its step text names one (reCAPTCHA /
    hCaptcha at the step). A CAPTCHA is a bot-check the user solves by taking the
    browser — its own state, never a tap-session staging (the user, Nov 4, 2026:
    "Separate the tap situations and captcha")."""
    if "AWAITING CAPTCHA TAKEOVER" in seg.upper():
        return True
    return "CAPTCHA" in _step_text(seg).upper()


# --------------------------------------------------------------------- items
# Disposition precedence: a later claim never un-stages an item, and a
# submitted event always settles the item (Versa: SKIPPED then SUBMITTED via
# the the user-directed one-off -> submitted). Latest event within the winning kind.
# ONE TIME-AWARE EXCEPTION (fix (a), Nov 4, 2026): a limbo event LATER than
# the winning staged/captcha event supersedes the park — see Item.state and
# fold_events, which apply the rule identically on both sides.
KIND_RANK = {"submitted": 5, "skipped": 4, "staged": 3, "captcha": 3,
             "packet": 3, "unstaged": 3,
             "limbo": 2, "post_submit_pending": 2, "not_submitted": 1,
             "claimed": 0, "stocked": -1}

EXCLUDED_HEADS = (
    "SEGMENT STATE", "SEGMENT CLOSE", "SEGMENT START", "FINAL ACCOUNTING",
    "BATCH CLOSED", "DAILY FULL-SYSTEM AUDIT", "Hourly Gmail scan",
    "APPLICATION EMAIL SCAN", "Guardian", "STARTING COUNTS",
    "Hourly sweep", "Quick check", "QUICK CHECK", "NIGHTLY AUDIT",
    "CLOSEOUT SEGMENT START", "RULE ", "RULE CHANGE", "RULE ACKNOWLEDGED",
    "NOTE —", "COMPANY DIVERSIFICATION", "TRACK 1", "TRACK 3",
    "CORRECTION / LESSON",
)


@dataclass
class Item:
    id: int
    company: str = ""
    role: str = ""
    source: str = ""               # LINKEDIN | JOBRIGHT | INDEED | LINKEDIN_ALERT | ""
    events: list = field(default_factory=list)   # (line_no, ts, kind, detail)
    gate: str = ""                 # pass | alert | fail | ""
    resume_file: str = ""
    linkedin_job_id: str = ""
    counts_all_time_only: bool = False
    counts_toward_window: bool = False
    # The window(s) a "counts toward this window" flag was recorded in:
    # the flag is scoped to its own entry's window (Nov 5, 2026) — as a
    # bare boolean it leaked into every window's status view.
    counts_toward_windows: set = field(default_factory=set)

    def events_of(self, *kinds):
        return [e for e in self.events if e[2] in kinds]

    @property
    def state(self) -> str:
        best_kind, best = "", None
        for e in self.events:
            kind = e[2]
            if kind in ("gate", "resume", "source"):
                continue
            if best is None or KIND_RANK.get(kind, -2) > KIND_RANK.get(best_kind, -2) \
                    or (KIND_RANK.get(kind, -2) == KIND_RANK.get(best_kind, -2)
                        and e[0] > best[0]):
                best_kind, best = kind, e
        # LIMBO SUPERSEDES AN EARLIER PARK (fix (a), Nov 4, 2026): the
        # ranks alone let an earlier staged/captcha (3) shadow a LATER
        # limbo (2) forever — Fetch #180 read "staged" although the
        # submit click came after the park and its outcome was never
        # observed. When the winning event is a park and a limbo event
        # sits at or after it, the item is limbo. The >= matters: a
        # bookkeeping note ABOUT the limbo (e.g. the session-guard
        # entry) can mine a phantom same-line staged segment from its
        # own wording; on a same-entry tie, limbo is the fail-safe
        # label (it blocks re-presentation and re-application; staged
        # invites a click). The legitimate return path — proof, then
        # the guarded unstage, then work — puts a later unstaged/staged
        # after the limbo, so it is not affected. fold_events applies
        # the same rule on the event side; the two must never drift.
        if best_kind in ("staged", "captcha", "packet") and best is not None:
            if any(e[2] == "limbo" and e[0] >= best[0] for e in self.events):
                return "limbo"
        return best_kind or ("stocked" if self.events else "")

    @property
    def submitted_event(self):
        ev = self.events_of("submitted")
        return ev[-1] if ev else None

    @property
    def first_submitted_event(self):
        """The item's ONE submission for window attribution (parser
        contract, Nov 5, 2026): the FIRST submitted-format entry in log
        order owns the window; later submitted/EMAIL-VERIFIED entries
        for the same item are catch-ups and never re-attribute it —
        the prose twin of the event model's "win" key."""
        ev = self.events_of("submitted")
        return ev[0] if ev else None


COMPANY_ROLE_RE = re.compile(
    r"^#\d+\s+(?P<company>[^\W\d_][\w.&/'’\- ]{0,44}?),\s+"
    r"(?P<role>(?:Senior|Sr\.|Staff|Lead)?[^,()]{2,64}?)(?:,| \(| —|$)")
COMPANY_ROLE_DASH_RE = re.compile(
    r"^#\d+\s+(?P<company>[^\W\d_][\w.&/'’\- ]{0,44}?)\s+—\s+"
    r"(?P<role>[^,()]{2,64}?)(?:,| \(| —|$)")


def normalize_company(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", name.lower())).strip()


# Company legal suffixes: in "Smith, Inc., Data Scientist" the first
# comma ends the company NAME's first fragment, not the company — the
# suffix token that follows it belongs to the company, and the role
# starts after the suffix. (A blind last-comma split is NOT used: this
# log's roles legitimately contain commas — "Senior Data Scientist -
# Digital Intelligence, Device Signals, SF" — so the split stays at the
# first comma except where a closed suffix token follows it.)
_COMPANY_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co",
                     "gmbh", "ag", "bv", "pty", "kk", "srl"}


def _identity_from_match(seg: str, cr) -> tuple[str, str]:
    """(company, role) from a COMPANY_ROLE match, with company-suffix
    shift: while the captured role is exactly a legal suffix token,
    move it onto the company and re-read the role that follows it."""
    company = cr.group("company").strip()
    role = cr.group("role").strip()
    pos = cr.end()
    while role.rstrip(".").lower() in _COMPANY_SUFFIXES:
        rm = re.match(r"\s*(?P<role>[^,()]{2,64}?)(?:,| \(| —|$)",
                      seg[pos:])
        if not rm:
            break
        company = f"{company}, {role}"
        role = rm.group("role").strip()
        pos += rm.end()
    # The writers' stocked format ends the identity with ". SOURCE
    # TAG: ..." — a role captured past that sentence boundary is
    # trailing prose, not role text. (Applied after the suffix shift,
    # which needs the raw token, "Inc." included.)
    role = role.split(". SOURCE TAG")[0].rstrip(". ").strip()
    return company, role


# ------------------------------------------------------------- log state
SUBMITTED_RE = re.compile(r"SUBMITTED\s*(?:\(|BY\b|by\b|in\b|—|–|-)|is now SUBMITTED")

# Heads whose segments are identity-bearing for the generic metadata
# miner: the canonical stocking / prep / outcome entry shapes.
IDENTITY_HEADS = (
    "STOCKED", "PREP", "READY", "CLAIM", "GATE PASS", "SUBMITTED",
    "EMAIL-VERIFIED", "SKIPPED", "SKIP", "STAGED", "AWAITING",
    "UNSTAGED", "IN LIMBO", "POST-SUBMIT", "PRESENTED TO WU",
    "TAP SESSION", "CAPTCHA SESSION", "LIVE SESSION",
    "MAIN-CHAT LIVE SESSION", "AD-HOC TAP SESSION",
)
RANGE_RE = re.compile(r"#(\d{2,3})\s*[–—-]\s*#?(\d{2,3})")
PDF_RE = re.compile(r"([\w][\w.\-]*\.pdf)")
LINKEDIN_ID_RE = re.compile(r"LinkedIn(?: job)? (\d{10})|jobs/view/(\d{10})")
SOURCE_TAG_RE = re.compile(r"SOURCE TAG: (LINKEDIN_ALERT|LINKEDIN|JOBRIGHT|INDEED)")


def expand_ranges(text: str) -> set[int]:
    out = set()
    for m in RANGE_RE.finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        if 0 < b - a < 60:
            out.update(range(a, b + 1))
    return out


@dataclass
class Window:
    date: str            # "2026-11-04"
    open_dt: datetime
    close_dt: datetime
    section_line: int


class LogState:
    def __init__(self, path: str):
        self.path = path
        with open(path, encoding="utf-8") as f:
            self.raw = f.read()
        self.lines = self.raw.splitlines()
        self.entries = split_entries(self.lines)
        self.items: dict[int, Item] = {}
        self.windows: list[Window] = []
        self.attributed: dict[str, dict[int, str]] = {}
        self._segment_hints: list = []   # deferred SEGMENT STATE hints
        self._parse_sections()
        self._parse_entries()
        self.blocked_total = self._blocked_total()
        self.blocked_companies = self._blocked_companies()

    # ---------------------------------------------------------- structure
    def _parse_sections(self):
        for i, raw in enumerate(self.lines, start=1):
            m = SECTION_RE.match(raw)
            if m:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                open_dt = datetime(y, mo, d, 8, 23, tzinfo=CT)
                wdate = f"{y:04d}-{mo:02d}-{d:02d}"
                self.windows.append(Window(wdate, open_dt,
                                           open_dt + timedelta(hours=24), i))

    def window_for(self, wdate: str | None) -> Window:
        if wdate is None:
            if not self.windows:
                raise ValueError(
                    "no batch window sections in the log yet")
            return self.windows[-1]
        for w in self.windows:
            if w.date == wdate:
                return w
        raise ValueError(f"no batch window section for {wdate}")

    def _blocked_total(self):
        hits = re.findall(r"Blocked list total: (\d+) companies", self.raw)
        return int(hits[-1]) if hits else None

    def _blocked_companies(self):
        """The blocked-company set (normalize_company keys), parsed
        from the log's Blocked companies section — the DEAD-NO-GO
        ZONE list. That section is the ONE canonical blacklist
        (rules.yaml reads even its total from the log; there is no
        second copy). stock.py's blacklist screen — screen 1 of
        the user's screening order (Nov 13, 2026) — matches against this
        set. A bullet's name is its text up to the first " (" or
        " — " annotation."""
        names = set()
        in_section = False
        for raw in self.lines:
            line = raw.rstrip("\n")
            if line.startswith("#"):
                if not in_section and "Blocked companies" in line:
                    in_section = True
                    continue
                if in_section:
                    break
            if in_section and line.startswith("- "):
                text = line[2:].strip()
                text = re.split(r"\s+\(|\s+—\s+|\s+–\s+",
                                text, maxsplit=1)[0]
                text = text.strip().rstrip(".")
                if text:
                    names.add(normalize_company(text))
        return names

    def item(self, iid: int) -> Item:
        if iid not in self.items:
            self.items[iid] = Item(iid)
        return self.items[iid]

    def _set_source(self, iid: int, source: str, priority: int):
        it = self.item(iid)
        cur = getattr(it, "_source_pri", 0)
        if priority >= cur and source:
            it.source, it._source_pri = source, priority

    def _add(self, iid: int, entry: Entry, kind: str, detail: str = ""):
        self.item(iid).events.append((entry.line_no, entry.ts, kind, detail))

    # ------------------------------------------------------------- mining
    def _parse_entries(self):
        current_window = None
        for entry in self.entries:
            for w in self.windows:  # section headings are not entries; track by line
                if w.section_line < entry.line_no:
                    current_window = w
            if entry.guardian:  # tallies/summaries only — never evidence
                continue
            head = entry.head
            body = entry.body

            # --- window attribution (the only summary line that carries it)
            if head.startswith("STARTING COUNTS") and current_window:
                for m in re.finditer(
                        r"(LinkedIn|Jobright)-sourced VERIFIED \d+ of \d+ — "
                        r"(#\d+ [^;]+)", body):
                    src = m.group(1).upper()
                    for iid in (int(x) for x in re.findall(r"#(\d+)", m.group(2))):
                        self.attributed.setdefault(current_window.date, {})[iid] = src
                        self._set_source(iid, src, 1)

            self._mine_stock_and_gate(
                entry, current_window.date if current_window else None)

            if head.startswith(EXCLUDED_HEADS):
                continue
            self._mine_segments(entry)

        # SEGMENT STATE hints attach ONLY to items a canonical entry
        # already created (parser contract, Nov 5, 2026): a shorthand
        # segment line can never mint an item, an identity, or an
        # outcome — it may only add a source/gate hint to a real item.
        for iid, source, gate_hint in self._segment_hints:
            if iid in self.items:
                if source:
                    self._set_source(iid, source, 1)
                if gate_hint and not self.items[iid].gate:
                    self.items[iid].gate = "pass"

        self._map_resumes_by_linkedin_id()

    def _mine_stock_and_gate(self, entry: Entry,
                             window_date: str | None = None):
        head, body = entry.head, entry.body
        # READY BENCH CARRIED line: explicit per-source lists.
        if head.startswith("READY BENCH CARRIED"):
            jr = re.search(r"JOBRIGHT-tagged.*?(?=LINKEDIN-tagged|$)", body, re.S)
            if jr:
                for iid in (int(x) for x in re.findall(r"#(\d+)", jr.group(0))):
                    self._set_source(iid, "JOBRIGHT", 2)
                    self._add(iid, entry, "stocked", "ready bench carried")
            li = re.search(r"LINKEDIN-tagged.*$", body, re.S)
            if li:
                for iid in (int(x) for x in re.findall(r"#(\d+)", li.group(0))):
                    self._set_source(iid, "LINKEDIN", 2)
                    self._add(iid, entry, "stocked", "ready bench carried")
        # Discovery passes: "STOCKED (all SOURCE TAG: LINKEDIN" — tag ONLY the
        # stocked enumeration (the "(#a–#b" range + "#NNN Name —" list items),
        # never every id mentioned in the pass's dedupe prose.
        if "STOCKED (all SOURCE TAG: LINKEDIN" in body:
            ids = set()
            m = re.search(r"STOCKED \(#(\d+)[–—-]#?(\d+)", body)
            if m:
                ids |= expand_ranges(m.group(0))
            ids |= {int(x) for x in re.findall(r"#(\d+) [A-Z][\w.]+ —", body)}
            for iid in ids:
                self._set_source(iid, "LINKEDIN", 2)
                self._add(iid, entry, "stocked", "discovery pass")
        if "JOBRIGHT DISCOVERY PASS" in head or "JOBRIGHT" in head and "STOCKED AS" in body:
            for iid in expand_ranges(body):
                self._set_source(iid, "JOBRIGHT", 2)
                self._add(iid, entry, "stocked", "jobright discovery pass")
        # SEGMENT STATE bench hints (ranges + explicit gate-passed
        # items) — DEFERRED, hints only (parser contract, Nov 5, 2026):
        # collected here, applied in _parse_entries only to items a
        # canonical entry already created. A shorthand line naming an
        # otherwise-unknown item creates nothing.
        if head.startswith("SEGMENT STATE"):
            m = re.search(r"Jobright application-ready.*?—(.*?);", body, re.S)
            if m:
                for iid in (int(x) for x in re.findall(r"#(\d+)", m.group(1))):
                    self._segment_hints.append((iid, "JOBRIGHT", True))
            m = re.search(r"LinkedIn bench in PREP.*?—(.*?);", body, re.S)
            if m:
                ids = {int(x) for x in re.findall(r"#(\d+)", m.group(1))}
                ids |= expand_ranges(m.group(1))
                for iid in ids:
                    self._segment_hints.append((iid, "LINKEDIN", False))
            for m in re.finditer(r"gate-passed — (#\d+)", body):
                iid = int(m.group(1)[1:])
                self._segment_hints.append((iid, "LINKEDIN", True))
        # GATE DEFERRED lines (the user, Nov 11, 2026): the company check
        # ran at forward movement, not at stocking, under that timing.
        # Historical lines only since the Nov 12, 2026 reversal
        # (gate timing is on_identification again — new stocks carry
        # a real verdict); they still parse exactly as before.
        if head.startswith("GATE DEFERRED"):
            deferred_ids = set(expand_ranges(head))
            # stock.py writes ONE line per item ("GATE DEFERRED —
            # #NNN Company — company check deferred …") — bind that
            # subject too (fix, Nov 12, 2026: the ranges-only read
            # left every real single-item line unparsed, so backlog
            # items never carried gate="deferred"). The canonical
            # em-dash shape keeps prose mentions ("GATE DEFERRED IN
            # CODE: …") from binding anything.
            if head.startswith("GATE DEFERRED —"):
                first = re.search(r"#(\d+)", head)
                if first:
                    deferred_ids.add(int(first.group(1)))
            for iid in deferred_ids:
                if not self.item(iid).gate:
                    self.item(iid).gate = "deferred"
        # Group gate lines: GATE PASS — ... (ranges in head, tiers in chunks).
        # A real verdict supersedes the "deferred" placeholder (the user,
        # Nov 12, 2026): the deferred check, once run at forward
        # movement and recorded by gate_intake.py in this same format,
        # replaces "deferred" — every other existing gate value still
        # wins over a later line, exactly as before.
        if head.startswith("GATE PASS"):
            for iid in expand_ranges(head):
                if self.item(iid).gate in ("", "deferred"):
                    self.item(iid).gate = "pass"
            tier = "pass"
            for chunk in body.split(";"):
                if re.search(r"HARD PASS|hard-pass|BLOCKED", chunk):
                    tier = "fail"
                elif re.search(r"ALERT BAND|alert band", chunk):
                    tier = "alert"
                elif "PASS" in chunk:
                    tier = "pass"
                # Only count-bearing mentions ("#200 176 / 1 (0.6%)") take the
                # tier — recap lists of gate-passed ids later in the entry
                # must not inherit a trailing HARD PASS tier.
                for cm in re.finditer(r"#(\d+) [^;]{0,44}?\d[\d,]* / \d", chunk):
                    iid = int(cm.group(1))
                    it = self.item(iid)
                    if tier == "fail":
                        it.gate = "fail"
                    elif it.gate in ("", "deferred"):
                        it.gate = tier
        # Forward-movement hard passes (gate_intake.py, the user, Nov 12,
        # 2026): GATE HARD PASS — #id Company — Source: #id Company
        # total / india (pct%) → verdict HARD_PASS_... — the deferred
        # check's verdict on an ALREADY-SUBMITTED item. It mines as
        # gate=fail ONLY: unlike a stocking-time SKIPPED entry it
        # binds no outcome, so the item's recorded state (submitted)
        # is untouched.
        if head.startswith("GATE HARD PASS"):
            for cm in re.finditer(r"#(\d+) [^;]{0,44}?\d[\d,]* / \d",
                                  body):
                self.item(int(cm.group(1))).gate = "fail"
        # Generic per-segment metadata (identity, source tags, gate,
        # resume, counts flags) — mined ONLY from identity-bearing
        # segments (parser contract, Nov 5, 2026): segments of canonical
        # stocking/outcome entries, of discovery passes (the legacy
        # stocking enumeration), or segments that themselves bind an
        # outcome. Summary/correction/screening prose never contributes
        # identity — a screening line like "#49 PASS — Nuro" must not
        # name the item "PASS" when its canonical SUBMITTED entry
        # ("#49 Nuro, ...") carries the real identity.
        if head.startswith(EXCLUDED_HEADS) or head.startswith("CORRECTION"):
            return
        identity_head = head.startswith(IDENTITY_HEADS) \
            or "DISCOVERY PASS" in head
        # Explicit source tags: a tag anywhere in an entry belongs to the
        # entry's SUBJECT (first-mentioned item) at top priority — entries put
        # the tag at the end, after dedupe prose mentioning other items.
        # Per-segment tags still apply at mining priority.
        segs = segments(entry)
        tag_anywhere = SOURCE_TAG_RE.search(body)
        if tag_anywhere and segs:
            self._set_source(segs[0][0], tag_anywhere.group(1), 3)
        for iid, seg in segs:
            if not identity_head and _segment_head_outcome(seg) is None:
                continue
            it = self.item(iid)
            m = SOURCE_TAG_RE.search(seg)
            if m:
                self._set_source(iid, m.group(1), 2)
            if "GATE PASS" in seg and not it.gate:
                it.gate = "pass"
            for pm in PDF_RE.finditer(seg):
                if it.resume_file:
                    continue
                token = pm.group(1)
                after = seg[pm.end():pm.end() + 10]
                slug = re.sub(r"[^a-z0-9]+", "-",
                              it.company.lower()).strip("-") if it.company else ""
                if after.strip().startswith(f"(#{iid})") \
                        or (slug and slug in token) \
                        or (it.linkedin_job_id and it.linkedin_job_id in token):
                    it.resume_file = token
            for lm in LINKEDIN_ID_RE.finditer(seg):
                if not it.linkedin_job_id:
                    it.linkedin_job_id = lm.group(1) or lm.group(2)
            cr = COMPANY_ROLE_RE.search(seg) or COMPANY_ROLE_DASH_RE.search(seg)
            if cr is not None and cr.re is COMPANY_ROLE_DASH_RE \
                    and cr.group("company").strip().upper() in (
                        "PASS", "SKIP", "HOLD"):
                # Screening shape, not an identity: "#49 PASS — Nuro"
                # puts a verdict word in the dash pattern's company
                # slot. A verdict is never a company name here — the
                # item's canonical entry carries its real identity.
                cr = None
            if cr and not it.company:
                it.company, it.role = _identity_from_match(seg, cr)
            if not it.company and head.startswith(("STOCKED", "PREP")):
                # stock.py's dash format: "#NNN — Company — Role — …"
                # (no comma after the head word, dashes between fields).
                dm = re.match(
                    r"#\d+\s+—\s+(.+?)\s+—\s+(.+?)(?=\s+—|\s*$)", seg)
                if dm:
                    it.company, it.role = dm.group(1).strip(), \
                        dm.group(2).strip()
            if re.search(r"[Cc]ounts toward this window", seg):
                it.counts_toward_window = True
                if window_date:
                    it.counts_toward_windows.add(window_date)
            if "counts all-time only" in seg and ("SUBMITTED" in seg or "submitted" in seg):
                it.counts_all_time_only = True

    def _mine_segments(self, entry: Entry):
        """Canonical outcome mining (parser contract, Nov 5, 2026).

        An outcome binds ONLY from the two structural positions:
        the entry HEAD (closed vocabulary, the entry's own subject) or
        a segment's HEAD CLAUSE (legacy multi-item entries). CORRECTION
        entries are annotations and are never mined. All other text —
        reasons, tallies, dedupe notes, cross-references — is inert,
        however many outcome words it contains."""
        head = entry.head
        if head.startswith("CORRECTION"):
            self._mine_correction(entry)
            return
        # Summary heads (Guardian tallies, segment closes, sweeps,
        # audits, accounting) never create dispositions — not even via
        # a segment whose head clause happens to carry an outcome word.
        # WORKER NOTEs join this set (Nov 13, 2026 — the #685 phantom):
        # a worker note is a run summary, never an outcome record; in
        # driver mode every outcome is its own canonical entry written
        # by the program. A note mentioning a dropped item (#685,
        # dropped by the duplication screen) and later describing a
        # sibling's submission without repeating that sibling's #id
        # minted a phantom "submitted" for the dropped item, because
        # its segment ran on into the sibling's flight prose.
        if head.startswith(EXCLUDED_HEADS) or head.startswith("Guardian") \
                or head.startswith("WORKER NOTE"):
            return
        if head.startswith("STOCKED"):
            subj = _first_item_id(entry.body)
            if subj is not None:
                self._add(subj, entry, "stocked", "stocked")
            return
        ho = _head_outcome(entry)
        if ho is not None:
            kind, subj, detail = ho
            self._add(subj, entry, kind, detail)
            # A head-bound entry may carry one secondary state in its
            # own prefix (e.g. a limbo note on a staged entry).
            prefix = entry_prefix(entry).upper()
            if kind not in ("limbo",) and "IN LIMBO" in prefix:
                self._add(subj, entry, "limbo", "uncertain outcome (head)")
            if kind not in ("post_submit_pending",) \
                    and "POST-SUBMIT VALIDATION PENDING" in prefix:
                self._add(subj, entry, "post_submit_pending",
                          "validation code demanded (head)")
            return
        for iid, seg in segments(entry):
            so = _segment_head_outcome(seg)
            if so is not None:
                self._add(iid, entry, so[0], so[1])

    def _mine_correction(self, entry: Entry):
        """A CORRECTION entry is an annotation and binds NOTHING —
        with one narrow exception (parser contract, Nov 5, 2026): the
        log's own supersede mechanism. When a correction (a) names a
        single subject in its head ("CORRECTION — #NNN ..."), (b)
        explicitly supersedes a prior claim ("was WRONG and is
        superseded" / "is superseded"), and (c) asserts the corrected
        outcome in canonical form (PAGE-CONFIRMED / EMAIL-VERIFIED),
        it binds that outcome for its subject — it is the record's
        designated repair for a wrongly written outcome entry (#198
        Navan, Nov 4, 2026, whose only submission record this is).
        A correction merely CONTAINING outcome words — a verification
        note, a count reconciliation — stays fully inert (#146)."""
        m = re.match(r"CORRECTION\s+[/—–-]*\s*#(\d+)\b", entry.head)
        if not m:
            return
        body = entry.body
        if "is superseded" not in body and "IS SUPERSEDED" not in body:
            return
        if "PAGE-CONFIRMED" in body:
            self._add(int(m.group(1)), entry, "submitted",
                      "page-confirmed (correction, superseding)")
        elif "EMAIL-VERIFIED" in body:
            self._add(int(m.group(1)), entry, "submitted",
                      "email-verified (correction, superseding)")

    def _map_resumes_by_linkedin_id(self):
        files = set()
        for m in PDF_RE.finditer(self.raw):
            files.add(m.group(1))
        for it in self.items.values():
            if it.resume_file or not it.linkedin_job_id:
                continue
            for fn in files:
                if it.linkedin_job_id in fn:
                    it.resume_file = fn
                    break

    # ------------------------------------------------------------- status
    def window_status(self, wdate: str | None = None) -> dict:
        w = self.window_for(wdate)
        attributed = self.attributed.get(w.date, {})
        verified, staged, captcha, limbo, bench, claimed = [], [], [], [], [], []
        packets = []
        slots: set[str] = set()
        for it in sorted(self.items.values(), key=lambda x: x.id):
            # Window attribution follows the FIRST submitted-format
            # entry (parser contract, Nov 5, 2026): one submission per
            # item; a later re-mention in a newer section never moves
            # it into that section's window.
            sub = it.first_submitted_event
            if sub and sub[0] >= w.section_line and sub[1] \
                    and w.open_dt <= sub[1] < w.close_dt:
                slots.add(normalize_company(it.company))
            if sub:
                member = False
                if it.counts_all_time_only:
                    member = False
                elif it.id in attributed \
                        or w.date in it.counts_toward_windows \
                        or (it.counts_toward_window
                            and not it.counts_toward_windows):
                    member = True
                elif sub[0] >= w.section_line and sub[1] \
                        and w.open_dt <= sub[1] < w.close_dt:
                    member = True
                if member:
                    verified.append(it)
                    slots.add(normalize_company(it.company))
            st = it.state
            staged_ev = it.events_of("staged")
            if st == "staged" and staged_ev and staged_ev[-1][0] >= w.section_line:
                staged.append(it)
            captcha_ev = it.events_of("captcha")
            if st == "captcha" and captcha_ev \
                    and captcha_ev[-1][0] >= w.section_line:
                captcha.append(it)
            packet_ev = it.events_of("packet")
            if st == "packet" and packet_ev \
                    and packet_ev[-1][0] >= w.section_line:
                packets.append(it)
            if st == "limbo":
                limbo.append(it)
            stocked_here = any(e[0] >= w.section_line and e[2] == "stocked"
                               for e in it.events) or it.id in attributed
            if stocked_here and st in ("stocked", "unstaged"):
                bench.append(it)
            if stocked_here and st == "claimed":
                claimed.append(it)
        by_source: dict[str, list] = {}
        for it in verified:
            by_source.setdefault(it.source or attributed.get(it.id, "") or "UNKNOWN",
                                 []).append(it)
        all_time: dict[str, int] = {}
        for it in self.items.values():
            if it.submitted_event:
                key = normalize_company(it.company)
                all_time[key] = all_time.get(key, 0) + 1
        return {
            "window": {"date": w.date, "opens": w.open_dt.isoformat(),
                       "closes": w.close_dt.isoformat(),
                       "section_line": w.section_line},
            "verified": verified,
            "verified_by_source": by_source,
            "verified_total": len(verified),
            "staged": staged,
            "captcha": captcha,
            "packet": packets,
            "limbo": limbo,
            "bench": bench,
            "claimed": claimed,
            "company_slots_used": sorted(s for s in slots if s),
            "all_time_verified_by_company": all_time,
            "blocked_total_in_log": self.blocked_total,
            "log_lines": len(self.lines),
        }


def parse_log(path: str) -> LogState:
    return LogState(path)


# Event types that SETTLE or PARK an item in prose (the disposition
# kinds of KIND_RANK at rank >= limbo): stocked / claimed are
# pre-outcome and not_submitted settles nothing. post_submit_pending
# IS rank 2 but has no event-book type (it is prose-only by design),
# so it is excluded here — EVENT_DISPOSITION has no entry for it and
# the duplicate guard could never match it anyway (a live check hit
# exactly that KeyError, Nov 7, 2026). EVENT_DISPOSITION itself is
# defined below (the functional-log section); Python resolves the
# name when this runs, so the literal set is spelled out here.
_PROSE_OUTCOME_KINDS = frozenset(
    k for k, r in KIND_RANK.items()
    if r >= 2 and k not in ("post_submit_pending",))


def prose_event_kinds(log_path) -> dict[int, set[str]]:
    """Map each item id to the set of EVENT-BOOK outcome types its
    prose entries prove — read with the exact disposition binding the
    state check uses (classify_divergence's per-item rule): the
    event dispositions of ALL the item's prose events (any kind
    reaching rank >= limbo in KIND_RANK), so an item submitted then
    limbo carries both, and a benign prose-only catch-up is "real"
    here exactly as there. Kinds are translated to event types via
    EVENT_DISPOSITION (verified cannot appear — prose binds e-mail
    confirmation as a submitted event with the email-verified
    detail). Caller: pipeline.record's duplicate guard (the user, Nov 7,
    2026), which must judge prose with the same eyes as the state
    check or the two disagree on what is already recorded."""
    st = parse_log(str(log_path))
    out: dict[int, set[str]] = {}
    for iid, it in st.items.items():
        kinds = {EVENT_DISPOSITION[e[2]] for e in it.events
                 if e[2] in _PROSE_OUTCOME_KINDS}
        if kinds:
            out[iid] = kinds
    return out


def prose_outcome_ts(log_path) -> dict[int, dict[str, object]]:
    """Map each item id to {event type: LATEST prose timestamp} for
    the same outcome set prose_event_kinds reports (same binding,
    same translation). Caller: pipeline.record's duplicate guard,
    which compares the prose moment against the event book's latest
    write for the item: a prose outcome AT OR AFTER the book's
    latest write landed while the book was already current — its
    event twin never arrived (a half-completed write); a prose
    outcome BEFORE it is pre-book history the book later caught up
    past (migration), never a replay."""
    st = parse_log(str(log_path))
    out: dict[int, dict[str, object]] = {}
    for iid, it in st.items.items():
        per: dict[str, object] = {}
        for e in it.events:
            if e[2] not in _PROSE_OUTCOME_KINDS or e[1] is None:
                continue
            t = EVENT_DISPOSITION[e[2]]
            if t not in per or e[1] > per[t]:
                per[t] = e[1]
        if per:
            out[iid] = per
    return out


# ------------------------------------------------- functional-log state
# state.py prefers events when present (design, "The functional log"):
# the event stream folded in file order must reproduce the state the prose
# parser computes. Disposition precedence mirrors KIND_RANK above; on a tie
# the LATER event wins, except that "submitted"/"verified" settle an item.
EVENT_DISPOSITION = {
    "stocked": "stocked", "claimed": "claimed", "limbo": "limbo",
    "staged": "staged", "unstaged": "unstaged", "captcha": "captcha",
    "packet": "packet",
    "skipped": "skipped", "submitted": "submitted", "verified": "submitted",
}
EVENT_RANK = {"stocked": -1, "claimed": 0, "limbo": 2, "unstaged": 3,
              "staged": 3, "captcha": 3, "packet": 3, "skipped": 4,
              "submitted": 5}


def _event_ts(ev: dict):
    raw = ev.get("ts")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=CT)


def _window_relevant(ev: dict, window: Window | None) -> bool:
    """An event belongs to a window when its "win" key names the window
    (backfills and one-offs like Turo, whose submit predates the open) or
    its timestamp falls inside [open, close)."""
    if window is None:
        return True
    if ev.get("win") == window.date:
        return True
    ts = _event_ts(ev)
    return bool(ts and window.open_dt <= ts < window.close_dt)


def fold_events(events: list[dict], window: Window | None = None) -> dict:
    """Fold an event stream into per-item state + window tallies.

    Events are the minimal shape ({ts, type, item, src, win[, why]}):
    no company (callers resolve names from the prose parse) and no payload,
    so a correction event is a marker only — the prose log carries its
    substance — and never moves an item. Window membership comes from the
    "win" key (see _window_relevant); source from the "src" key.

    Returns {"items": {iid: {"state", "company", "source"}},
             "verified": set(iid), "verified_by_source": {SRC: set(iid)},
             "staged": set(iid), "captcha": set(iid), "packet": set(iid),
             "limbo": set(iid)}.
    Captcha items are their own list, never part of staged: a captcha is a
    bot-check the user solves by taking the browser, not a tap. It holds the same
    rank as staged, so a later submitted / staged event for the same item
    supersedes it (and a later captcha supersedes an earlier staged).
    Non-disposition events (verification_missed, friction_*, rule_changed,
    correction) never move an item."""
    items: dict[int, dict] = {}
    verified: dict[int, str] = {}
    staged_win: set[int] = set()
    captcha_win: set[int] = set()
    packet_win: set[int] = set()
    limbo_win: set[int] = set()
    for pos, ev in enumerate(events):
        iid = ev.get("item")
        if iid is None:
            continue
        iid = int(iid)
        rec = items.setdefault(iid, {"state": "", "company": "",
                                     "source": "", "_rank": -99,
                                     "_pos": -1, "_limbo_pos": -1})
        if ev.get("src"):
            rec["source"] = str(ev["src"]).upper()
        etype = ev.get("type")
        kind = EVENT_DISPOSITION.get(etype, "")
        if not kind:
            continue
        rank = EVENT_RANK.get(kind, -2)
        if rank >= rec["_rank"]:
            rec["state"], rec["_rank"], rec["_pos"] = kind, rank, pos
        if kind == "limbo":
            rec["_limbo_pos"] = pos
        if kind == "submitted" and _window_relevant(ev, window):
            verified[iid] = rec["source"] or verified.get(iid, "")
        if kind == "staged" and _window_relevant(ev, window):
            staged_win.add(iid)
        if kind == "captcha" and _window_relevant(ev, window):
            captcha_win.add(iid)
        if kind == "packet" and _window_relevant(ev, window):
            packet_win.add(iid)
        if kind == "limbo" and _window_relevant(ev, window):
            limbo_win.add(iid)
    # LIMBO SUPERSEDES AN EARLIER PARK (fix (a), Nov 4, 2026 — the same
    # rule Item.state applies on the prose side): if the folded winner
    # is a park but the item's latest limbo event sits after the event
    # that set that state, the item is limbo.
    for rec in items.values():
        if rec["state"] in ("staged", "captcha", "packet") \
                and rec["_limbo_pos"] > rec["_pos"]:
            rec["state"] = "limbo"
    by_source: dict[str, set] = {}
    for iid, src in verified.items():
        if items[iid]["state"] == "submitted":
            by_source.setdefault(src or "UNKNOWN", set()).add(iid)
    return {
        "items": {iid: {"state": r["state"], "company": r["company"],
                        "source": r["source"]} for iid, r in items.items()},
        "verified": {iid for iid in verified
                     if items[iid]["state"] == "submitted"},
        "verified_by_source": by_source,
        "staged": {iid for iid in staged_win
                   if items[iid]["state"] == "staged"},
        "captcha": {iid for iid in captcha_win
                    if items[iid]["state"] == "captcha"},
        "packet": {iid for iid in packet_win
                   if items[iid]["state"] == "packet"},
        "limbo": {iid for iid in limbo_win
                  if items[iid]["state"] == "limbo"},
    }
