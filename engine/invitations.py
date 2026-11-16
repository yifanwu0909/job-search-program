"""invitations.py — connection-invitation tracking in code.

the user, Nov 10, 2026: "handle the tracking in the code." Until now the
daily invitation count lived only in the prose outreach log and in
LinkedIn's own Sent-People counter — which is flaky (Nov 10, 2026: the
counter started the run at 1,174 although the Nov 9 run had ended at
1,178; the day's 30 sends were real, verified one by one in the Sent
list, and the discrepancy survived only as unexplained prose).

This module gives invitations the same discipline applications have:
  * the RUN judges (it saw the send verify as Pending) and hands code
    a small structured packet — never prose for code to parse;
  * code validates the packet and appends ONE event to the event book
    (events.append_invite_event; invite_sent / invite_backfill /
    invite_counter — no `item` key, so the application fold never
    sees them);
  * every count a report quotes — sent today, all-time total,
    remaining quota vs rules.yaml invitations.daily_target — is
    COMPUTED here from the book, never re-derived by a run;
  * the Sent-People counter is data, not truth: a run records its
    start and end readings as invite_counter snapshots, and
    compute_status exposes the arithmetic — within-day discrepancy
    (counter delta minus recorded sends) and cross-day drift (today's
    start reading minus the latest earlier end reading) — as numbers.

DUPLICATE GUARD (in the spirit of pipeline.record's, Nov 7, 2026): a
second invite_sent for the same normalized person name on the same CT
date is REFUSED before anything is written, as is a second counter
snapshot for the same day+phase and a second backfill for a date that
already has one. A replayed record call therefore cannot inflate the
count of record.

Dates are America/Chicago dates (the `day` key on every event); a
send's day comes from its own timestamp, never from the reader's
clock, so a backfill and a live run can never disagree about which
day a send belongs to.
"""
from __future__ import annotations

import re
from datetime import datetime, time as dtime
from pathlib import Path

import events as events_mod
from state import CT

DEFAULT_DAILY_TARGET = 30
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _valid_date(day) -> str:
    day = str(day or "")
    if not _DATE_RE.fullmatch(day):
        raise ValueError(f"REFUSED — day must be YYYY-MM-DD, got: {day!r}. "
                         f"Nothing was written.")
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"REFUSED — not a real calendar date: {day!r}. "
                         f"Nothing was written.")
    return day


def normalize_person(name) -> str:
    """Name identity for the duplicate guard: casefolded, whitespace
    collapsed. Deliberately nothing cleverer — two different people
    who share a name on the same day are the run's problem to
    disambiguate (it can record the second under a fuller name), and
    a too-clever normalizer would merge strangers."""
    return " ".join(str(name or "").split()).casefold()


def _ct_day(ts_iso: str) -> str:
    dt = events_mod._parse_ts(ts_iso)
    if dt is None:
        raise ValueError(f"REFUSED — unparseable timestamp: {ts_iso!r}. "
                         f"Nothing was written.")
    return dt.astimezone(CT).strftime("%Y-%m-%d")


def _noon_ct(day: str) -> str:
    """A deterministic stamp for a backfilled day: noon CT that date
    (zoneinfo resolves CDT/CST). Backfilled events are aggregates;
    their position inside the day carries no meaning."""
    dt = datetime.combine(datetime.strptime(day, "%Y-%m-%d").date(),
                          dtime(12, 0), tzinfo=CT)
    return dt.isoformat()


def invite_events(events_path) -> list[dict]:
    """The invitation slice of the event book, in file order."""
    return [e for e in events_mod.read_events(events_path)
            if str(e.get("type", "")).startswith("invite_")]


def _sent_index(events: list[dict]) -> set[tuple[str, str]]:
    return {(normalize_person(e.get("who")), str(e.get("day")))
            for e in events if e.get("type") == "invite_sent"}


def _validate_send(packet) -> dict:
    """One send packet -> the event fields, or a REFUSED ValueError.
    Packet shape (data only): {"person": str (required),
    "note": bool (required — was a note attached), "company": str
    (optional), "role": str (optional), "ts": ISO str (optional,
    defaults to now), "source": str (required — the user, Nov 14, 2026:
    ALL outreach comes from contacto, burned into code; a send whose
    source is missing or is not contacto is REFUSED, so a
    LinkedIn-found invitation can never enter the count of record)}."""
    if not isinstance(packet, dict):
        raise ValueError("REFUSED — an invite packet must be a JSON "
                         "object. Nothing was written.")
    who = " ".join(str(packet.get("person") or "").split())
    if not who:
        raise ValueError("REFUSED — an invite record must name the "
                         "person (packet key 'person'). Nothing was "
                         "written.")
    if len(who) > 160:
        raise ValueError("REFUSED — person name is implausibly long "
                         f"({len(who)} chars). Nothing was written.")
    note = packet.get("note")
    if not isinstance(note, bool):
        raise ValueError("REFUSED — packet key 'note' must be true or "
                         "false (was a note attached to the "
                         "invitation?). Nothing was written.")
    # CONTACTO ONLY (the user, Nov 14, 2026 — burned into code): every
    # recorded send must name its source, and the only accepted source
    # is contacto (a saved-contacts hit from contacto step 0 counts —
    # it is part of contacto). A missing or non-contacto source means
    # the person was found on LinkedIn, which is not an outreach
    # source at all anymore; the send is refused and never counted.
    src = " ".join(str(packet.get("source") or "").split()).lower()
    if not src:
        raise ValueError("REFUSED — packet key 'source' is required "
                         "and must be 'contacto' (the user, Nov 14, 2026: "
                         "all outreach comes from contacto). Nothing "
                         "was written.")
    if not any(k in src for k in
               ("contacto", "saved_contact", "saved contact")):
        raise ValueError("REFUSED — source is not contacto "
                         f"({src!r}); LinkedIn-found people are not "
                         "an outreach source (the user, Nov 14, 2026). "
                         "Nothing was written.")
    fields: dict = {"who": who, "note": note, "source": src}
    for key in ("company", "role"):
        val = packet.get(key)
        if val is not None:
            val = " ".join(str(val).split())
            if val:
                fields[key] = val[:160]
    ts = packet.get("ts")
    ts = str(ts) if ts else events_mod.now_iso()
    fields["day"] = _ct_day(ts)
    fields["_ts"] = ts
    return fields


def record_invites(events_path, packet) -> dict:
    """Record one send (a single packet) or several ({"invites":
    [packet, ...]}) — the outreach run calls this after each batch of
    verified sends. Each send is validated and duplicate-checked
    BEFORE its line is written; a refused send writes nothing and is
    reported back in the result, never raised over the sends that
    landed. A wholly malformed packet raises (nothing written)."""
    if isinstance(packet, dict) and isinstance(packet.get("invites"), list):
        packets = packet["invites"]
    elif isinstance(packet, dict):
        packets = [packet]
    else:
        raise ValueError("REFUSED — invite packet must be a JSON object "
                         "or {\"invites\": [...]}. Nothing was written.")
    events = invite_events(events_path)
    seen = _sent_index(events)
    recorded, refused = [], []
    for pkt in packets:
        try:
            fields = _validate_send(pkt)
        except ValueError as exc:
            refused.append({"packet": pkt, "error": str(exc)})
            continue
        key = (normalize_person(fields["who"]), fields["day"])
        if key in seen:
            refused.append({
                "packet": pkt,
                "error": f"REFUSED — duplicate: an invitation to "
                         f"{fields['who']} is already recorded for "
                         f"{fields['day']} in the event book "
                         f"(invitations duplicate guard). Nothing was "
                         f"written for this send."})
            continue
        ts = fields.pop("_ts")
        recorded.append(events_mod.append_invite_event(
            events_path, "invite_sent", fields, ts=ts))
        seen.add(key)
    return {"recorded": recorded, "refused": refused}


def record_counter(events_path, phase, value, day=None,
                   mark=None, ts=None) -> dict:
    """Record one reading of LinkedIn's Sent-People counter
    (phase: "start" | "end" of a day's run). One reading per
    day+phase: a second is a replay and is refused."""
    if phase not in ("start", "end"):
        raise ValueError(f"REFUSED — counter phase must be 'start' or "
                         f"'end', got: {phase!r}. Nothing was written.")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"REFUSED — counter value must be a "
                         f"non-negative integer, got: {value!r}. "
                         f"Nothing was written.")
    ts = str(ts) if ts else events_mod.now_iso()
    day = _valid_date(day) if day else _ct_day(ts)
    for e in invite_events(events_path):
        if (e.get("type") == "invite_counter" and e.get("day") == day
                and e.get("phase") == phase):
            raise ValueError(
                f"REFUSED — a {phase} counter snapshot for {day} is "
                f"already recorded ({e.get('counter')}); a second "
                f"reading is a replay. Nothing was written.")
    fields: dict = {"day": day, "phase": phase, "counter": value}
    if mark:
        fields["mark"] = str(mark)
    return events_mod.append_invite_event(
        events_path, "invite_counter", fields, ts=ts)


def record_backfill(events_path, days, counters=()) -> dict:
    """THE RECONCILIATION / BACKFILL PATH (one-time, by hand — the
    #182/#187 precedent): seed aggregate history that predates code
    tracking. `days`: [{"date": "YYYY-MM-DD", "count": int}, ...] —
    one invite_backfill event per day, NO person names (the history
    is counts only; inventing names would corrupt the record).
    `counters`: [{"date", "phase", "counter"}, ...] — seeded
    Sent-People readings, marked "backfill". Idempotent per day: a
    day (or day+phase) already seeded is SKIPPED and reported, never
    double-counted. Returns {appended, skipped, counters_appended,
    counters_skipped}."""
    events = invite_events(events_path)
    done_days = {str(e.get("day")) for e in events
                 if e.get("type") == "invite_backfill"}
    done_snaps = {(str(e.get("day")), str(e.get("phase")))
                  for e in events if e.get("type") == "invite_counter"}
    appended, skipped = [], []
    for row in days:
        if not isinstance(row, dict):
            raise ValueError("REFUSED — backfill days must be objects "
                             "{\"date\": ..., \"count\": ...}. Nothing "
                             "further was written.")
        day = _valid_date(row.get("date"))
        n = row.get("count")
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0 \
                or n > 1000:
            raise ValueError(f"REFUSED — backfill count for {day} must "
                             f"be a positive integer, got: {n!r}. "
                             f"Nothing further was written.")
        if day in done_days:
            skipped.append({"date": day, "count": n,
                            "reason": "already backfilled"})
            continue
        appended.append(events_mod.append_invite_event(
            events_path, "invite_backfill",
            {"day": day, "n": n, "mark": "backfill"}, ts=_noon_ct(day)))
        done_days.add(day)
    c_appended, c_skipped = [], []
    for row in counters or ():
        day = _valid_date(row.get("date"))
        phase = row.get("phase")
        if phase not in ("start", "end"):
            raise ValueError(f"REFUSED — backfill counter phase for "
                             f"{day} must be 'start' or 'end'. Nothing "
                             f"further was written.")
        value = row.get("counter")
        if isinstance(value, bool) or not isinstance(value, int) \
                or value < 0:
            raise ValueError(f"REFUSED — backfill counter for {day} "
                             f"must be a non-negative integer. Nothing "
                             f"further was written.")
        if (day, phase) in done_snaps:
            c_skipped.append({"date": day, "phase": phase,
                              "reason": "already recorded"})
            continue
        c_appended.append(events_mod.append_invite_event(
            events_path, "invite_counter",
            {"day": day, "phase": phase, "counter": value,
             "mark": "backfill"}, ts=_noon_ct(day)))
        done_snaps.add((day, phase))
    return {"appended": appended, "skipped": skipped,
            "counters_appended": c_appended,
            "counters_skipped": c_skipped}


def compute_status(events_path, date=None,
                   target: int = DEFAULT_DAILY_TARGET) -> dict:
    """Fold the invitation slice of the book into the numbers every
    consumer quotes. Pure read; no writes.

    Returns {date, target, sent_on_date, remaining_today, all_time,
    by_day {date: {sent, backfill, total}},
    counter: {date, start, end, counter_delta, recorded_that_day,
              discrepancy, reconciled, prior_end, drift_from_prior_end}}
    where discrepancy = counter_delta - recorded_that_day (None when
    the day has no start+end snapshot pair; reconciled is then None
    too), and drift_from_prior_end = today's start reading minus the
    latest end reading on any earlier day (the Nov 10, 2026 flake:
    start 1,174 vs the Nov 9 end 1,178 -> drift -4)."""
    events = invite_events(events_path)
    by_day: dict[str, dict] = {}

    def _slot(day: str) -> dict:
        return by_day.setdefault(day, {"sent": 0, "backfill": 0,
                                       "total": 0})

    snaps: dict[tuple[str, str], int] = {}
    for e in events:
        etype = e.get("type")
        day = str(e.get("day") or "")
        if not day:
            continue
        if etype == "invite_sent":
            _slot(day)["sent"] += 1
        elif etype == "invite_backfill":
            _slot(day)["backfill"] += int(e.get("n") or 0)
        elif etype == "invite_counter":
            snaps[(day, str(e.get("phase")))] = int(e.get("counter") or 0)
    all_time = 0
    for slot in by_day.values():
        slot["total"] = slot["sent"] + slot["backfill"]
        all_time += slot["total"]
    date = _valid_date(date) if date else datetime.now(CT).strftime("%Y-%m-%d")
    sent_on_date = by_day.get(date, {"total": 0})["total"]
    start = snaps.get((date, "start"))
    end = snaps.get((date, "end"))
    counter_delta = (end - start) if (start is not None
                                      and end is not None) else None
    discrepancy = (counter_delta - sent_on_date
                   if counter_delta is not None else None)
    prior_end = None
    for (d, phase), val in sorted(snaps.items()):
        if phase == "end" and d < date:
            prior_end = val  # sorted by day: the latest earlier end wins
    drift = (start - prior_end) if (start is not None
                                    and prior_end is not None) else None
    return {
        "date": date,
        "target": int(target),
        "sent_on_date": sent_on_date,
        "remaining_today": max(0, int(target) - sent_on_date),
        "all_time": all_time,
        "by_day": dict(sorted(by_day.items())),
        "counter": {
            "date": date, "start": start, "end": end,
            "counter_delta": counter_delta,
            "recorded_that_day": sent_on_date,
            "discrepancy": discrepancy,
            "reconciled": (discrepancy == 0
                           if discrepancy is not None else None),
            "prior_end": prior_end,
            "drift_from_prior_end": drift,
        },
    }
