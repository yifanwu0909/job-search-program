#!/usr/bin/env python3
"""Inbox packet tests (the user, Nov 12, 2026 — inbox scope in code, not
in the run). All writes go to temp copies: a throwaway claims
ledger, outreach log, watch state, and watch .md. No live file is
touched; no Gmail or LinkedIn access happens here (intake consumes
candidate dicts the run would hand it).

Run: python3 tests/run_inbox_tests.py

Coverage:
  (a) intake: a genuine notification inside the past hour passes,
      with the person parsed from the subject.
  (b) intake: a stale (>1h) notification is refused with the reason
      AND recorded processed, so it never resurfaces.
  (c) intake: an already-processed Gmail ID is refused (duplicate).
  (d) intake triage: digest subject refused; marketing sender
      refused; a connection-accepted notice with NO message body
      refused; the same notice WITH a message body passes.
  (e) intake: the person falls back to the sender display name;
      a duplicate inside one batch is refused.
  (f) watch-record: claim line lands in the ledger (house format),
      the Gmail ID is marked processed, the log skeleton lands,
      verified on read-back; a replayed record is refused.
  (g) check-claim: CLAIMED for a claimed person + timestamp,
      CLEAR for an unclaimed one.
  (h) daily-scope: the cutoff is exactly now − 24h; a thread
      claimed inside the window is in stand_down; an old claim is
      not; a watch-handled thread inside the window is.
  (i) daily-record: writes its claim for the daily job.
  (j) state: the one-time seed reads IDs from the watch .md.
  (k) malformed batches raise (nothing written).
  (l) the REAL notification format (the user's sample, Nov 12, 2026):
      sender "Pruthvi Desai via LinkedIn", subject "Pruthvi just
      messaged you", a "View message" button in the HTML — passes
      triage on the pass pattern, the person is the FULL name from
      the sender (not the subject's first name), and thread_url is
      the button's conversation URL. Without any link, thread_url
      is null (with a note) and the item still passes; a links-list
      URL is extracted too; an InMail subject passes via its slot.
  (m) the Gmail search lives in config (the user, Nov 12, 2026): the
      rules.yaml inbox.gmail_search block names the linkedin.com
      senders + the "messaged you" subject + the past-hour window,
      its subject regex accepts BOTH "just messaged you" and "has
      messaged you", and the intake pass pattern is aligned — a
      "has messaged you" notification passes intake with the full
      name parsed from the sender.
  (n) the PINNED sender (the user, Nov 12, 2026): the genuine address is
      messaging-digest-noreply@linkedin.com. Mail from it is never
      refused on a sender pattern (proven against a config whose
      sender patterns include a bare "digest"), while a digest
      SUBJECT from that same address is still refused on the
      subject patterns; the same sender pattern refuses the same
      subject from any other address.
  (o) CONNECTION-INVITATION emails (the user, Nov 12, 2026 — "Burn this
      into code. Just like message reply through email."): finder
      pattern pinned — From messages-noreply@linkedin.com (NOT the
      messaging-digest address), subject containing "invitation is
      waiting for your response". A genuine invitation passes with
      the FULL person name from the sender and accept_url from an
      Accept-anchor fixture; stale is refused + marked processed
      (and a retry is refused as already processed); a candidate
      from a non-pinned sender is refused; a group invitation is
      refused and NEVER logged; an ad/marketing subject is refused;
      no Accept link → accept_url null + note, still actionable.
      invite-record writes the by-name acceptance log line +
      processed state on throwaway state (verified), a replay is
      refused, and a skipped outcome marks processed with NO log
      line. The invitation_search config block is aligned with the
      intake pass patterns.
  (p) JOB-ALERT pinned sender (the user, Nov 12, 2026 — "for all email
      comes from 'jobalerts-noreply@linkedin.com' only... Burn
      this into code."): the watch list's third pinned sender. A
      candidate from that exact address is refused by BOTH intakes
      on the exact address — even when its subject would otherwise
      pass (a "just messaged you" subject at watch-intake, the
      invitation phrase at invite-intake) — and the refusal is
      marked processed. The job_alert_sender config entry exists
      and is the exact address.
  (r) STRIPPED job-alert candidates (the user, Nov 13, 2026 — "fix
      these in code"): a candidate with no html, no links and no
      LinkedIn URL in its body was never read in full — intake
      refuses it with consumed: false and does NOT mark it
      processed, so the run can re-read the email and re-feed it;
      the same email re-fed in full passes with its jobs.
  (s) DAILY FINISH (the user, Nov 13, 2026): the code writes the daily
      check's run line from a counts summary — all three sections
      (conversations, invitations, alerts) required, handled
      counts may not exceed found/in-scope; a bad summary raises
      and writes nothing.
  (t) DAILY FINISH — NOT-ON-REVELIO FALLBACK LEDGER (the user,
      Nov 13, 2026): whenever alerts were found, the summary
      must name every company written off as not on Revelio in
      "alerts_not_on_revelio" with the resolution of its
      mandatory LinkedIn fallback; the finish is refused when
      the field is missing, when a resolution is unknown, or
      when a named company's fallback is not on record in the
      log (the DROPPED_NO_REVELIO line for linkedin_no_counts,
      a GATE PASS line naming LinkedIn People for
      linkedin_packet) — and accepted when both are on record.
  (u) DAILY FINISH — TRACKED FALLBACK STATE (the user, Nov 13, 2026,
      the code step between Revelio and LinkedIn): a fallback
      order code opened the same day that is still open in
      gate_fallback's tracked state refuses the finish even
      when the summary itself is clean; clearing the record
      (the fallback recorded) lets the finish through.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "checks"))
import gate_fallback as gate_fallback_mod  # noqa: E402
import inbox as ib  # noqa: E402

CT = ib.CT
FAILS = []
NOW = datetime(2026, 11, 12, 15, 0, tzinfo=CT)

CLAIMS_FIXTURE = """# Inbox action claims — test fixture

## Claims

- CLAIM 2026-11-12 15:07 CT — Ian Fay (Next Insurance), latest incoming 2026-11-12 14:58 CT "Hi Alex, Thank you for the note" + linkedin-reply — claimed by main chat — status: SENT (reply sent and verified in the thread)
- CLAIM 2026-11-02 11:36 CT — Mercedez Hernandez (Knightscope), latest incoming 2026-11-02 7:30 AM page time + gmail-resume-send + mrh@knightscope.com — claimed by linkedin-inbox-quick-check — status: SENT (Gmail message ID 1a19d8c20c1a886b)
"""

LOG_FIXTURE = "# Outreach log (test fixture)\n"


class Env:
    def __init__(self, md_text: str = ""):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        self.log = root / "outreach-log.md"
        self.claims = root / "inbox-action-claims.md"
        self.state = root / "inbox.json"
        self.md = root / "linkedin-message-watch-state.md"
        self.log.write_text(LOG_FIXTURE, encoding="utf-8")
        self.claims.write_text(CLAIMS_FIXTURE, encoding="utf-8")
        self.md.write_text(md_text, encoding="utf-8")

    def cleanup(self):
        self.td.cleanup()

    def kw(self) -> dict:
        return {"state_path": self.state, "md_path": self.md}

    def record_kw(self) -> dict:
        return {"log_path": self.log, "claims_path": self.claims,
                "state_path": self.state, "md_path": self.md}


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name
          + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def cand(gmail_id: str, minutes_ago: int, subject: str,
         sender: str = "Jane Doe via LinkedIn <notifications-noreply@linkedin.com>",
         body: str = "") -> dict:
    dt = NOW - timedelta(minutes=minutes_ago)
    return {"gmail_id": gmail_id, "sender": sender, "subject": subject,
            "date": dt.isoformat(), "snippet": "", "body": body}


def test_intake_genuine_and_stale() -> None:
    env = Env()
    out = ib.watch_intake(
        [cand("aaaaaaaaaaaaaaaa", 30, "Jane Doe sent you a message"),
         cand("bbbbbbbbbbbbbbbb", 130, "Old Person sent you a message")],
        now=NOW, **env.kw())
    check("a1 genuine passes", len(out["actionable"]) == 1
          and out["actionable"][0]["gmail_id"] == "aaaaaaaaaaaaaaaa",
          str(out))
    check("a2 person parsed from subject",
          out["actionable"][0]["person"] == "Jane Doe"
          and out["actionable"][0]["person_parsed"] is True, str(out))
    check("a3 received_at stamped",
          out["actionable"][0]["received_at"].startswith("2026-11-12T14:30"),
          str(out))
    check("b1 stale refused", len(out["refused"]) == 1
          and "stale" in out["refused"][0]["reason"], str(out))
    state = ib.load_state(env.state, env.md)
    check("b2 stale refusal recorded processed",
          "bbbbbbbbbbbbbbbb" in state["processed"]
          and state["processed"]["bbbbbbbbbbbbbbbb"]["outcome"] == "refused",
          str(state))
    check("b3 actionable NOT marked processed at intake",
          "aaaaaaaaaaaaaaaa" not in state["processed"], str(state))
    out2 = ib.watch_intake(
        [cand("bbbbbbbbbbbbbbbb", 130, "Old Person sent you a message")],
        now=NOW, **env.kw())
    check("c1 already-processed ID refused as duplicate",
          len(out2["actionable"]) == 0
          and "already processed" in out2["refused"][0]["reason"],
          str(out2))
    env.cleanup()


def test_intake_triage() -> None:
    env = Env()
    out = ib.watch_intake(
        [cand("cccccccccccccccc", 10, "Your LinkedIn weekly summary digest"),
         cand("dddddddddddddddd", 10, "A message about premium deals",
              sender="LinkedIn Marketing <marketing@linkedin.com>"),
         cand("eeeeeeeeeeeeeeee", 10, "John Smith accepted your invitation"),
         cand("ffffffffffffffff", 10, "John Smith accepted your invitation",
              body="Hi Alex — thanks for connecting, are you open to a call?")],
        now=NOW, **env.kw())
    reasons = {r["gmail_id"]: r["reason"] for r in out["refused"]}
    check("d1 digest refused by pattern",
          "cccccccccccccccc" in reasons
          and "subject pattern" in reasons["cccccccccccccccc"], str(out))
    check("d2 marketing sender refused by pattern",
          "dddddddddddddddd" in reasons
          and "sender pattern" in reasons["dddddddddddddddd"], str(out))
    check("d3 connection-accepted with no message refused",
          "eeeeeeeeeeeeeeee" in reasons
          and "connection-accepted" in reasons["eeeeeeeeeeeeeeee"], str(out))
    check("d4 connection-accepted WITH a message body passes",
          [a["gmail_id"] for a in out["actionable"]] == ["ffffffffffffffff"],
          str(out))
    env.cleanup()


def test_intake_person_fallback_and_batch_dup() -> None:
    env = Env()
    odd = cand("1111111111111111", 5, "You have a new message waiting",
               sender="Priya Nair via LinkedIn <notifications-noreply@linkedin.com>")
    out = ib.watch_intake([odd, dict(odd)], now=NOW, **env.kw())
    check("e1 person falls back to sender display name",
          len(out["actionable"]) == 1
          and out["actionable"][0]["person"] == "Priya Nair", str(out))
    check("e2 duplicate within one batch refused",
          len(out["refused"]) == 1
          and "within this intake batch" in out["refused"][0]["reason"],
          str(out))
    env.cleanup()


def _record_jane(env: Env) -> dict:
    return ib.watch_record(
        [{"gmail_id": "aaaaaaaaaaaaaaaa", "person": "Jane Doe",
          "outcome": "replied", "message_ts": "2026-11-12T14:30:00-06:00",
          "first_words": "Hi Alex, thanks for connecting"}],
        now=NOW, **env.record_kw())


def test_watch_record() -> None:
    env = Env()
    res = _record_jane(env)
    check("f1 record lands", len(res["recorded"]) == 1
          and res["recorded"][0]["verified"] is True, str(res))
    claims = env.claims.read_text(encoding="utf-8")
    check("f2 claim line in the ledger, house format",
          "Jane Doe, latest incoming 2026-11-12 14:30 CT" in claims
          and "+ linkedin-reply" in claims
          and "claimed by linkedin-message-email-watch" in claims
          and "status: SENT" in claims, claims[-400:])
    state = ib.load_state(env.state, env.md)
    check("f3 Gmail ID marked processed by record",
          state["processed"]["aaaaaaaaaaaaaaaa"]["outcome"] == "replied",
          str(state))
    check("f4 log skeleton landed",
          "LINKEDIN INBOX (email watch) — Jane Doe — outcome: replied"
          in env.log.read_text(encoding="utf-8"))
    res2 = _record_jane(env)
    check("f5 replayed record refused, nothing written twice",
          res2["recorded"] == [] and len(res2["refused"]) == 1
          and env.claims.read_text(encoding="utf-8").count("Jane Doe") == 1,
          str(res2))
    env.cleanup()


def test_check_claim() -> None:
    env = Env()
    hit = ib.check_claim("Ian Fay", "2026-11-12T14:58:00-06:00",
                         claims_path=env.claims)
    check("g1 claimed person + timestamp is CLAIMED",
          hit["verdict"] == "CLAIMED" and len(hit["matches"]) == 1, str(hit))
    miss = ib.check_claim("Nobody New", "2026-11-12T14:00:00-06:00",
                          claims_path=env.claims)
    check("g2 unclaimed person is CLEAR", miss["verdict"] == "CLEAR",
          str(miss))
    env.cleanup()


def test_daily_scope() -> None:
    env = Env()
    _record_jane(env)  # a watch-handled thread inside the window
    out = ib.daily_scope(now=NOW, claims_path=env.claims,
                         state_path=env.state, md_path=env.md)
    check("h1 cutoff is exactly now - 24h",
          out["cutoff"] == (NOW - timedelta(hours=24)).isoformat()
          and out["window_hours"] == 24, str(out))
    persons = {s["person"] for s in out["stand_down"]}
    check("h2 recent claim in stand_down", "Ian Fay" in persons, str(out))
    check("h3 old claim NOT in stand_down",
          "Mercedez Hernandez" not in persons, str(out))
    check("h4 watch-handled thread in stand_down, listed once",
          "Jane Doe" in persons
          and sum(1 for s in out["stand_down"]
                  if s["person"] == "Jane Doe") == 1, str(out))
    env.cleanup()


def test_daily_record() -> None:
    env = Env()
    res = ib.daily_record(
        [{"person": "Tom Lee", "outcome": "no_reply_needed",
          "message_ts": "2026-11-12T09:15:00-06:00",
          "first_words": "Thanks anyway"}],
        now=NOW, **env.record_kw())
    check("i1 daily record lands + verified",
          len(res["recorded"]) == 1
          and res["recorded"][0]["verified"] is True, str(res))
    claims = env.claims.read_text(encoding="utf-8")
    check("i2 daily claim names the daily job",
          "claimed by linkedin-inbox-replies" in claims
          and "status: DONE (no reply needed)" in claims, claims[-400:])
    env.cleanup()


def test_seed_and_malformed() -> None:
    md = ("# LinkedIn message email watch — state\n"
          "Processed Gmail message IDs:\n"
          "- 9999999999999999 — a handled notification\n")
    env = Env(md_text=md)
    state = ib.load_state(env.state, env.md)
    check("j1 one-time seed reads IDs from the watch .md",
          "9999999999999999" in state["processed"]
          and state["processed"]["9999999999999999"]["via"] == "seed",
          str(state))
    env.cleanup()
    env = Env()
    raised = False
    try:
        ib.watch_intake({"not": "a list"}, now=NOW, **env.kw())
    except ValueError:
        raised = True
    check("k1 malformed batch raises (nothing written)", raised
          and not env.state.exists())
    env.cleanup()


REAL_THREAD_URL = ("https://www.linkedin.com/messaging/thread/"
                   "2-YmZhN2QwYzEtMDAwMC0wMDAwLTAwMDAtMDAwMDAwMDAwMDAwXzEwMA==/")
REAL_HTML = f"""<html><body>
<p>1 new message awaits your response</p>
<p><strong>Pruthvi Desai</strong> — Director of Engineering | AI-Native, Platform &amp; OEM | Technical Leader</p>
<p><a href="{REAL_THREAD_URL}" style="background:#0a66c2;color:#ffffff">View message</a></p>
</body></html>"""


def test_real_format() -> None:
    env = Env()
    real = cand("1212121212121212", 10, "Pruthvi just messaged you",
                sender="Pruthvi Desai via LinkedIn "
                       "<messaging-digest-noreply@linkedin.com>")
    real["html"] = REAL_HTML
    real["body"] = "1 new message awaits your response — Pruthvi Desai"
    out = ib.watch_intake([real], now=NOW, **env.kw())
    check("l1 real format passes triage", len(out["actionable"]) == 1
          and out["refused"] == [], str(out))
    got = out["actionable"][0] if out["actionable"] else {}
    check("l2 person is the FULL name from the sender",
          got.get("person") == "Pruthvi Desai", str(out))
    check("l3 thread_url is the View message button's URL",
          got.get("thread_url") == REAL_THREAD_URL, str(out))

    bare = cand("3434343434343434", 10, "Pruthvi just messaged you",
                sender="Pruthvi Desai via LinkedIn "
                       "<messaging-digest-noreply@linkedin.com>")
    out2 = ib.watch_intake([bare], now=NOW, **env.kw())
    got2 = out2["actionable"][0] if out2["actionable"] else {}
    check("l4 no link: thread_url null + note, still actionable",
          len(out2["actionable"]) == 1
          and got2.get("thread_url") is None
          and "thread_url_note" in got2, str(out2))

    linked = cand("5656565656565656", 10, "Pruthvi just messaged you",
                  sender="Pruthvi Desai via LinkedIn "
                         "<messaging-digest-noreply@linkedin.com>")
    linked["links"] = ["https://www.linkedin.com/feed/",
                       REAL_THREAD_URL]
    out3 = ib.watch_intake([linked], now=NOW, **env.kw())
    got3 = out3["actionable"][0] if out3["actionable"] else {}
    check("l5 thread_url extracted from a links list",
          got3.get("thread_url") == REAL_THREAD_URL, str(out3))

    inmail = cand("7878787878787878", 10, "New InMail from Sara Kim",
                  sender="Sara Kim via LinkedIn "
                         "<inmail-hit-reply@linkedin.com>")
    out4 = ib.watch_intake([inmail], now=NOW, **env.kw())
    got4 = out4["actionable"][0] if out4["actionable"] else {}
    check("l6 InMail subject passes via its pattern slot",
          len(out4["actionable"]) == 1
          and got4.get("person") == "Sara Kim", str(out4))
    env.cleanup()


def test_gmail_search_config() -> None:
    import re as _re

    import yaml
    rules = yaml.safe_load(ib.RULES_PATH.read_text(encoding="utf-8"))
    gs = (rules.get("inbox") or {}).get("gmail_search") or {}
    check("m1 gmail_search block: pinned sender + subject + window",
          gs.get("from_address") == "messaging-digest-noreply@linkedin.com"
          and gs.get("subject_contains") == "messaged you"
          and gs.get("window_minutes") == 60
          and "messaging-digest-noreply@linkedin.com"
          in (gs.get("query") or ""), str(gs))
    rx = _re.compile(gs.get("subject_regex") or "", _re.IGNORECASE)
    check("m2 search subject regex accepts both variants",
          bool(rx.search("Pruthvi just messaged you"))
          and bool(rx.search("Pruthvi has messaged you")), str(gs))
    env = Env()
    out = ib.watch_intake(
        [cand("9090909090909090", 10, "Pruthvi has messaged you",
              sender="Pruthvi Desai via LinkedIn "
                     "<messaging-digest-noreply@linkedin.com>")],
        now=NOW, **env.kw())
    got = out["actionable"][0] if out["actionable"] else {}
    check("m3 'has messaged you' passes intake, full name parsed",
          len(out["actionable"]) == 1
          and got.get("person") == "Pruthvi Desai", str(out))
    env.cleanup()


def test_pinned_sender() -> None:
    import yaml
    cfg = yaml.safe_load(ib.RULES_PATH.read_text(encoding="utf-8"))["inbox"]
    # A config whose sender patterns WOULD trip on the pinned
    # address (a bare "digest") — the guard must still pass it.
    cfg = dict(cfg, non_message_sender_patterns=["digest"])
    pinned = {"sender": "Pruthvi Desai via LinkedIn "
                        "<messaging-digest-noreply@linkedin.com>",
              "subject": "A note about your profile", "body": ""}
    check("n1 pinned sender never refused on a sender pattern",
          ib._triage(pinned, cfg) is None
          and ib._pinned_sender(pinned, cfg) is True)
    other = {"sender": "Someone <weekly-digest@example.com>",
             "subject": "A note about your profile", "body": ""}
    check("n2 the same sender pattern refuses other addresses",
          (ib._triage(other, cfg) or "").startswith(
              "non-message sender pattern"), str(ib._triage(other, cfg)))
    digest_mail = {"sender": pinned["sender"],
                   "subject": "Your messaging digest for this week",
                   "body": ""}
    check("n3 a digest SUBJECT from the pinned address still refused",
          (ib._triage(digest_mail, cfg) or "").startswith(
              "non-message subject pattern"),
          str(ib._triage(digest_mail, cfg)))


INVITE_ACCEPT_URL = ("https://www.linkedin.com/e/v2?e=inv123"
                     "&midToken=AQGx&trk=invite-accept")
INVITE_HTML = f"""<html><body>
<p><strong>Sara Kim</strong> is waiting for your response</p>
<p><a href="{INVITE_ACCEPT_URL}" style="background:#0a66c2;color:#ffffff">Accept</a>
<a href="https://www.linkedin.com/in/sara-kim/">View profile</a></p>
</body></html>"""
INVITE_SENDER = "Sara Kim via LinkedIn <messages-noreply@linkedin.com>"
INVITE_SUBJECT = "Sara's invitation is waiting for your response"


def icand(gmail_id: str, minutes_ago: int, subject: str = INVITE_SUBJECT,
          sender: str = INVITE_SENDER, html: str = "") -> dict:
    c = cand(gmail_id, minutes_ago, subject, sender=sender)
    if html:
        c["html"] = html
    return c


def test_invite_intake() -> None:
    env = Env()
    out = ib.invite_intake([icand("a0a0a0a0a0a0a0a0", 10, html=INVITE_HTML)],
                           now=NOW, **env.kw())
    check("o1 genuine invitation passes", len(out["actionable"]) == 1
          and out["refused"] == [], str(out))
    got = out["actionable"][0] if out["actionable"] else {}
    check("o2 person is the FULL name from the sender",
          got.get("person") == "Sara Kim"
          and got.get("person_parsed") is True, str(out))
    check("o3 accept_url is the Accept anchor's href",
          got.get("accept_url") == INVITE_ACCEPT_URL, str(out))

    # CADENCE (the user, Nov 12, 2026 — "invitation watch you can do
    # daily"): the invitation window is 24 HOURS (1440 minutes in
    # rules.yaml) — an invitation several hours old is actionable;
    # only over-24h is stale.
    out_h = ib.invite_intake(
        [icand("c0c0c0c0c0c0c0c0", 300, html=INVITE_HTML)],
        now=NOW, **env.kw())
    check("o4a invitation 5h old is actionable under the daily "
          "window", len(out_h["actionable"]) == 1, str(out_h))
    out2 = ib.invite_intake([icand("b0b0b0b0b0b0b0b0", 1500)],
                            now=NOW, **env.kw())
    check("o4 stale invitation (>24h) refused",
          len(out2["refused"]) == 1
          and "stale" in out2["refused"][0]["reason"], str(out2))
    state = ib.load_state(env.state, env.md)
    check("o5 stale refusal recorded processed (shared pool)",
          "b0b0b0b0b0b0b0b0" in state["processed"]
          and state["processed"]["b0b0b0b0b0b0b0b0"]["via"]
          == "invite-intake", str(state))
    out3 = ib.invite_intake([icand("b0b0b0b0b0b0b0b0", 5)],
                            now=NOW, **env.kw())
    check("o6 already-processed ID refused as duplicate",
          len(out3["actionable"]) == 0
          and "already processed" in out3["refused"][0]["reason"],
          str(out3))

    out4 = ib.invite_intake(
        [icand("c0c0c0c0c0c0c0c0", 10,
               sender="Sara Kim via LinkedIn "
                      "<messaging-digest-noreply@linkedin.com>")],
        now=NOW, **env.kw())
    check("o7 non-pinned sender refused (the digest address is not it)",
          len(out4["actionable"]) == 0
          and "pinned invitation sender" in out4["refused"][0]["reason"],
          str(out4))

    log_before = env.log.read_text(encoding="utf-8")
    out5 = ib.invite_intake(
        [icand("d0d0d0d0d0d0d0d0", 10,
               subject="Houston ML Group group invitation is waiting "
                       "for your response",
               sender="Houston ML Group via LinkedIn "
                      "<messages-noreply@linkedin.com>")],
        now=NOW, **env.kw())
    check("o8 group invitation refused", len(out5["actionable"]) == 0
          and "group invitation" in out5["refused"][0]["reason"],
          str(out5))
    check("o9 group invitation NOT logged",
          env.log.read_text(encoding="utf-8") == log_before
          and "Houston ML Group" not in log_before)

    out6 = ib.invite_intake(
        [icand("e0e0e0e0e0e0e0e0", 10,
               subject="Sara's invitation is waiting for your "
                       "response — sponsored")],
        now=NOW, **env.kw())
    check("o10 ad/marketing invitation refused",
          len(out6["actionable"]) == 0
          and "subject pattern" in out6["refused"][0]["reason"],
          str(out6))

    bare = icand("f0f0f0f0f0f0f0f0", 10)
    out7 = ib.invite_intake([bare], now=NOW, **env.kw())
    got7 = out7["actionable"][0] if out7["actionable"] else {}
    check("o11 no Accept link: accept_url null + note, still actionable",
          len(out7["actionable"]) == 1
          and got7.get("accept_url") is None
          and "accept_url_note" in got7, str(out7))
    env.cleanup()


def test_invite_record() -> None:
    env = Env()
    res = ib.invite_record(
        [{"gmail_id": "a0a0a0a0a0a0a0a0", "person": "Sara Kim",
          "outcome": "accepted"}], now=NOW,
        log_path=env.log, state_path=env.state, md_path=env.md)
    check("o12 invite-record lands + verified",
          len(res["recorded"]) == 1
          and res["recorded"][0]["verified"] is True, str(res))
    log_text = env.log.read_text(encoding="utf-8")
    check("o13 acceptance logged BY NAME in the log's style",
          "LINKEDIN INVITATION ACCEPTED" in log_text
          and "Sara Kim" in log_text, log_text)
    state = ib.load_state(env.state, env.md)
    check("o14 Gmail ID marked processed by invite-record",
          state["processed"]["a0a0a0a0a0a0a0a0"]["outcome"] == "accepted",
          str(state))
    check("o15 invite-record writes NO claims-ledger line",
          env.claims.read_text(encoding="utf-8") == CLAIMS_FIXTURE)
    res2 = ib.invite_record(
        [{"gmail_id": "a0a0a0a0a0a0a0a0", "person": "Sara Kim",
          "outcome": "accepted"}], now=NOW,
        log_path=env.log, state_path=env.state, md_path=env.md)
    check("o16 replayed invite-record refused, nothing written twice",
          res2["recorded"] == [] and len(res2["refused"]) == 1
          and env.log.read_text(encoding="utf-8").count("Sara Kim") == 1,
          str(res2))
    res3 = ib.invite_record(
        [{"gmail_id": "a1a1a1a1a1a1a1a1", "person": "Some Newsletter",
          "outcome": "skipped"}], now=NOW,
        log_path=env.log, state_path=env.state, md_path=env.md)
    state = ib.load_state(env.state, env.md)
    check("o17 skipped marks processed with NO log line naming it",
          len(res3["recorded"]) == 1
          and res3["recorded"][0]["verified"] is True
          and "a1a1a1a1a1a1a1a1" in state["processed"]
          and "Some Newsletter"
          not in env.log.read_text(encoding="utf-8"), str(res3))
    env.cleanup()


def test_invite_config() -> None:
    import re as _re

    import yaml
    rules = yaml.safe_load(ib.RULES_PATH.read_text(encoding="utf-8"))
    cfg = rules.get("inbox") or {}
    gs = cfg.get("invitation_search") or {}
    check("o18 invitation_search block: pinned sender + subject + window",
          gs.get("from_address") == "messages-noreply@linkedin.com"
          and gs.get("subject_contains")
          == "invitation is waiting for your response"
          and gs.get("window_minutes") == 1440
          and "messages-noreply@linkedin.com" in (gs.get("query") or "")
          and "invitation is waiting for your response"
          in (gs.get("query") or ""), str(gs))
    pats = cfg.get("invitation_subject_patterns") or []
    check("o19 intake pass patterns aligned with the search subject",
          any(_re.search(p, INVITE_SUBJECT, _re.IGNORECASE) for p in pats)
          and any(_re.search(p, gs.get("subject_contains") or "",
                             _re.IGNORECASE) for p in pats), str(pats))
    rx = _re.compile(gs.get("subject_regex") or "", _re.IGNORECASE)
    check("o20 search subject regex matches the real subject form",
          bool(rx.search(INVITE_SUBJECT)), str(gs))


JOB_ALERT_SENDER = ("LinkedIn Job Alerts "
                    "<jobalerts-noreply@linkedin.com>")


def test_job_alert_sender() -> None:
    import yaml
    rules = yaml.safe_load(ib.RULES_PATH.read_text(encoding="utf-8"))
    ja = (rules.get("inbox") or {}).get("job_alert_sender") or {}
    check("p1 job_alert_sender config is the exact pinned address",
          ja.get("from_address") == "jobalerts-noreply@linkedin.com",
          str(ja))
    env = Env()
    out = ib.watch_intake(
        [cand("a2a2a2a2a2a2a2a2", 10, "Jamie just messaged you",
              sender=JOB_ALERT_SENDER)], now=NOW, **env.kw())
    check("p2 watch-intake refuses job-alert mail on the exact address",
          len(out["actionable"]) == 0
          and "job-alert" in out["refused"][0]["reason"]
          and "jobalerts-noreply@linkedin.com"
          in out["refused"][0]["reason"], str(out))
    state = ib.load_state(env.state, env.md)
    check("p3 watch refusal marked processed",
          "a2a2a2a2a2a2a2a2" in state["processed"], str(state))
    out2 = ib.invite_intake(
        [icand("b2b2b2b2b2b2b2b2", 10, sender=JOB_ALERT_SENDER)],
        now=NOW, **env.kw())
    check("p4 invite-intake refuses job-alert mail on the exact address",
          len(out2["actionable"]) == 0
          and "job-alert" in out2["refused"][0]["reason"]
          and "jobalerts-noreply@linkedin.com"
          in out2["refused"][0]["reason"], str(out2))
    state = ib.load_state(env.state, env.md)
    check("p5 invite refusal marked processed (shared pool)",
          "b2b2b2b2b2b2b2b2" in state["processed"], str(state))
    env.cleanup()


ALERT_HTML = """<html><body>
<p>Your job alert for Machine Learning Engineer</p>
<p>New jobs in United States match your preferences</p>
<p><a href="https://www.linkedin.com/jobs/view/4371000001/">Applied Data Scientist</a><br/>Varonis<br/>United States (Hybrid)<br/>Actively recruiting</p>
<p><a href="https://www.linkedin.com/comm/jobs/view/4371000002/?trackingId=abc">Senior Applied ML Scientist</a><br/>SentiLink<br/>New York, NY (Remote)</p>
<p><a href="https://www.linkedin.com/slink?code=xyz&url=https%3A%2F%2Fwww.linkedin.com%2Fjobs%2Fview%2F4371000003%2F">Senior Data Scientist</a><br/>PPG<br/>Pittsburgh, PA (Hybrid)</p>
<p><a href="https://www.linkedin.com/jobs/search/?keywords=Machine%20Learning">See all jobs</a></p>
</body></html>"""


def jcand(gmail_id: str, minutes_ago: int, subject: str,
          sender: str = JOB_ALERT_SENDER, html: str = "",
          links=None, body: str = "") -> dict:
    c = cand(gmail_id, minutes_ago, subject, sender=sender, body=body)
    if html:
        c["html"] = html
    if links is not None:
        c["links"] = links
    return c


def test_jobalert_intake() -> None:
    env = Env()
    # (q1) a genuine alert email shaped like the sampled one passes,
    # with the individual job links AND the See-all link extracted.
    out = ib.jobalert_intake(
        [jcand("c1c1c1c1c1c1c1c1", 120,
               "Your job alert for Machine Learning Engineer",
               html=ALERT_HTML)], now=NOW, **env.kw())
    act = out["actionable"]
    check("q1 sample-shaped alert email passes with extracted jobs",
          len(act) == 1 and len(act[0]["jobs"]) == 3
          and [j["label"] for j in act[0]["jobs"]] ==
          ["Applied Data Scientist", "Senior Applied ML Scientist",
           "Senior Data Scientist"]
          and act[0]["jobs"][0]["job_url"] ==
          "https://www.linkedin.com/jobs/view/4371000001/"
          and act[0]["jobs"][2]["job_url"] ==
          "https://www.linkedin.com/jobs/view/4371000003/",
          str(out))
    check("q2 see_all_url extracted as its own field",
          act and act[0]["see_all_url"] ==
          "https://www.linkedin.com/jobs/search/?keywords=Machine%20Learning"
          and all(act[0]["see_all_url"] != j["job_url"]
                  for j in act[0]["jobs"]), str(out))
    ins = act[0]["instructions"] if act else []
    joined = " ".join(ins)
    check("q3 packet carries the code's fixed instructions",
          len(ins) >= 8 and "pages 1-5" in joined
          and "STOP at page 5" in joined
          and "never open page 6" in joined
          and "Easy Apply IS okay" in joined
          and "Revelio" in joined and "AT IDENTIFICATION" in joined
          and "LINKEDIN_ALERT" in joined
          and "jobalert-record" in joined, joined)
    check("q3b company name comes from the email; gate vets before "
          "any link opens (the user, Nov 12, 2026)",
          "company name is basic information in the email" in joined
          and "Do NOT open a job's link just to" in joined
          and "BEFORE opening any job link" in joined
          and "never gets its link opened" in joined
          and joined.index("AT IDENTIFICATION")
          < joined.index("EXTERNAL source"), joined)
    check("q3c list-scan partition: names off the aggregated list, "
          "brand-new companies first, packet carries the program's "
          "applied-companies record (the user, Nov 12, 2026)",
          "WITHOUT opening any posting" in joined
          and "keep each job tied to its place" in joined
          and "BRAND-NEW: work those first" in joined
          and "applied_companies" in joined
          and isinstance(act[0].get("applied_companies"), list)
          and joined.index("BRAND-NEW")
          < joined.index("EXTERNAL source"), joined)
    check("q3d alert-lane title screen: Senior MLE passes on alert "
          "jobs only; Staff/Lead/Principal/Consultant stay out "
          "(the user, Nov 12, 2026; Consultant added Nov 13, 2026)",
          "SENIOR Machine Learning Engineer titles PASS on alert"
          in joined
          and "Staff, Lead, Principal and Consultant titles are "
          "OUT" in joined
          and "LinkedIn alert jobs ONLY" in joined
          and "Jobright and Indeed keep" in joined, joined)
    import yaml as _yaml
    _rules = _yaml.safe_load(ib.RULES_PATH.read_text(encoding="utf-8"))
    _rf = (_rules or {}).get("role_filter") or {}
    check("q3e rules.yaml carries the Senior-MLE carve-out as data: "
          "senior_mle_allowed_sources == [LINKEDIN_ALERT], banned "
          "keywords include Consultant (the user, Nov 13, 2026)",
          _rf.get("senior_mle_allowed_sources") == ["LINKEDIN_ALERT"]
          and _rf.get("banned_title_keywords")
          == ["Staff", "Lead", "Principal", "Consultant"]
          and "Senior MLE is ALLOWED on the LinkedIn-alert lane"
          in str(_rf.get("mle")), str(_rf))
    check("q3f screening order in the fixed instructions: "
          "blacklist, then duplication (a repeat is dropped, "
          "never fill-in), then Revelio with the LinkedIn "
          "fallback; description vetting at the external posting "
          "(the user, Nov 13, 2026)",
          "BLACKLIST first" in joined
          and "DUPLICATION second" in joined
          and "REVELIO third" in joined
          and "dropped on sight" in joined
          and "never fill-in" in joined
          and joined.index("BLACKLIST first")
          < joined.index("DUPLICATION second")
          < joined.index("REVELIO third")
          < joined.index("EXTERNAL source")
          and "LinkedIn fallback gate" in joined
          and "linkedin_checked" in joined
          and "full-time direct/permanent" in joined
          and "green-card eligible" in joined
          and "not consulting" in joined
          and "stocked to the bench" in joined, joined)
    _scr = (_rules or {}).get("screening") or {}
    check("q3g rules.yaml carries the screening order as data: "
          "[blacklist, duplicate_company, revelio_gate], drop "
          "action, wu_directed exemption; gate fallback source "
          "is LinkedIn People (the user, Nov 13, 2026)",
          _scr.get("order") == ["blacklist", "duplicate_company",
                                "revelio_gate"]
          and _scr.get("duplicate_company_action") == "drop"
          and _scr.get("duplicate_company_exemption")
          == "wu_directed"
          and ((_rules or {}).get("gate") or {}).get(
              "fallback_source") == "LinkedIn People", str(_scr))
    check("q4 actionable alert email NOT marked processed at intake",
          "c1c1c1c1c1c1c1c1" not in ib.load_state(
              env.state, env.md)["processed"]
          or not ib._consumed(ib.load_state(
              env.state, env.md)["processed"],
              "c1c1c1c1c1c1c1c1", "jobalert"), "")
    env.cleanup()

    # (q5) SENDER-ONLY identification: the subject is never consulted
    # — a subject in the role-at-company shape passes, and so does a
    # subject that would trip the shared digest/marketing triage.
    env = Env()
    out = ib.jobalert_intake(
        [jcand("c2c2c2c2c2c2c2c2", 60,
               "Data Scientist job at Northwind Labs for you",
               html=ALERT_HTML),
         jcand("c3c3c3c3c3c3c3c3", 60,
               "Your weekly digest — sponsored premium summary",
               html=ALERT_HTML)], now=NOW, **env.kw())
    check("q5 any subject from the pinned sender is actionable",
          len(out["actionable"]) == 2 and not out["refused"], str(out))

    # (q6) a non-alert sender is never picked up, alert-like subject
    # or not; the refusal is consumed for the alert flow.
    out = ib.jobalert_intake(
        [jcand("c4c4c4c4c4c4c4c4", 60,
               "Your job alert for Machine Learning Engineer",
               sender="Jobs Person via LinkedIn "
                      "<notifications-noreply@linkedin.com>",
               html=ALERT_HTML)], now=NOW, **env.kw())
    check("q6 wrong sender refused despite the alert-like subject",
          len(out["actionable"]) == 0
          and "pinned job-alert sender" in out["refused"][0]["reason"]
          and "subject is never consulted"
          in out["refused"][0]["reason"], str(out))
    state = ib.load_state(env.state, env.md)
    check("q7 wrong-sender refusal consumed for the alert flow",
          ib._consumed(state["processed"], "c4c4c4c4c4c4c4c4",
                       "jobalert")
          and not ib._consumed(state["processed"], "c4c4c4c4c4c4c4c4",
                               "inbox"), str(state))

    # (q8) stale (>24h) refused; a re-intake reports the alert-flow
    # consumption, not a fresh refusal.
    out = ib.jobalert_intake(
        [jcand("c5c5c5c5c5c5c5c5", 1500, "Your job alert",
               html=ALERT_HTML)], now=NOW, **env.kw())
    check("q8 stale (>24h) alert email refused",
          len(out["actionable"]) == 0
          and "stale" in out["refused"][0]["reason"], str(out))
    out = ib.jobalert_intake(
        [jcand("c5c5c5c5c5c5c5c5", 1500, "Your job alert",
               html=ALERT_HTML)], now=NOW, **env.kw())
    check("q9 the stale refusal consumed the ID for the alert flow",
          "already processed for the job-alert flow"
          in out["refused"][0]["reason"], str(out))

    # (q10) no-links email: still actionable, empty jobs + note.
    # The body carries a LinkedIn URL (an alert email read in full
    # always carries LinkedIn URLs, footer links at minimum) but
    # no extractable job link — the note path. A candidate with NO
    # LinkedIn URL anywhere was never read in full and is refused
    # instead — see (r), Nov 13, 2026.
    out = ib.jobalert_intake(
        [jcand("c6c6c6c6c6c6c6c6", 30, "Your job alert",
               body="New jobs match your preferences. Manage this "
                    "alert: https://www.linkedin.com/jobs/alerts")],
        now=NOW, **env.kw())
    check("q10 no-links alert email still actionable with a note",
          len(out["actionable"]) == 1
          and out["actionable"][0]["jobs"] == []
          and out["actionable"][0]["see_all_url"] is None
          and "jobs_note" in out["actionable"][0], str(out))
    env.cleanup()


def test_jobalert_consumer_scopes() -> None:
    # (q11) a watch-intake job-alert refusal consumes the ID for the
    # INBOX flow only — the alert flow still takes the same email.
    env = Env()
    same = cand("d1d1d1d1d1d1d1d1", 10, "Jamie just messaged you",
                sender=JOB_ALERT_SENDER)
    out = ib.watch_intake([same], now=NOW, **env.kw())
    check("q11 watch refusal lands (job-alert mail, inbox flow)",
          len(out["refused"]) == 1
          and "job-alert" in out["refused"][0]["reason"], str(out))
    alert_cand = jcand("d1d1d1d1d1d1d1d1", 10, "Jamie just messaged you",
                       html=ALERT_HTML)
    out = ib.jobalert_intake([alert_cand], now=NOW, **env.kw())
    check("q12 the watch refusal does NOT block the alert flow",
          len(out["actionable"]) == 1, str(out))
    state = ib.load_state(env.state, env.md)
    check("q13 the stamp carries the inbox consumer only",
          set(state["processed"]["d1d1d1d1d1d1d1d1"]["consumers"])
          == {"inbox"}, str(state))
    env.cleanup()

    # (q14) reverse: a jobalert record does NOT block the watch —
    # the watch still reaches its own job-alert refusal for the ID,
    # and the merged stamp then carries both consumers.
    env = Env()
    out = ib.jobalert_record(
        [{"gmail_id": "d2d2d2d2d2d2d2d2", "outcome": "screened"}],
        now=NOW, **env.kw())
    check("q14 jobalert-record screens + verifies",
          len(out["recorded"]) == 1
          and out["recorded"][0]["verified"] is True, str(out))
    out = ib.jobalert_record(
        [{"gmail_id": "d2d2d2d2d2d2d2d2", "outcome": "screened"}],
        now=NOW, **env.kw())
    check("q15 jobalert-record replay refused",
          len(out["recorded"]) == 0
          and "already processed for the job-alert flow"
          in out["refused"][0]["reason"], str(out))
    out = ib.watch_intake(
        [cand("d2d2d2d2d2d2d2d2", 10, "Jamie just messaged you",
              sender=JOB_ALERT_SENDER)], now=NOW, **env.kw())
    check("q16 the alert stamp does NOT block the watch's refusal",
          len(out["refused"]) == 1
          and "job-alert" in out["refused"][0]["reason"]
          and "already processed" not in out["refused"][0]["reason"],
          str(out))
    state = ib.load_state(env.state, env.md)
    check("q17 merged stamp carries both consumers",
          set(state["processed"]["d2d2d2d2d2d2d2d2"]["consumers"])
          == {"inbox", "jobalert"}, str(state))
    out = ib.jobalert_record(
        [{"gmail_id": "d3d3d3d3d3d3d3d3", "outcome": "bogus"}],
        now=NOW, **env.kw())
    check("q18 bad jobalert outcome refused",
          len(out["refused"]) == 1
          and "outcome must be one of" in out["refused"][0]["reason"],
          str(out))
    env.cleanup()


def test_jobalert_config_and_other_filters() -> None:
    import yaml
    rules = yaml.safe_load(ib.RULES_PATH.read_text(encoding="utf-8"))
    js = (rules.get("inbox") or {}).get("jobalert_search") or {}
    check("q19 jobalert search is sender-only FROM config",
          js.get("from_address") == "jobalerts-noreply@linkedin.com"
          and js.get("window_minutes") == 1440
          and js.get("query") == "from:jobalerts-noreply@linkedin.com"
          and "subject:" not in (js.get("query") or "")
          and not any("subject" in str(k) for k in js), str(js))
    check("q20 gate timing is on_identification",
          (rules.get("gate") or {}).get("timing") == "on_identification",
          str((rules.get("gate") or {}).get("timing")))
    disc = rules.get("discovery") or {}
    tg = (rules.get("window") or {}).get("targets") or {}
    check("q21 alert source config: 5-page cap, total still 60",
          disc.get("linkedin_alert_max_pages") == 5
          and disc.get("linkedin_alert_easy_apply_allowed") is True
          and tg.get("linkedin_alert") == 60 and tg.get("total") == 60,
          str(tg))
    # (q22) the OTHER two intakes keep BOTH filters (the user, Nov 12,
    # 2026 scope confirmation): the pinned message sender with a
    # non-message subject is still refused on the subject, and the
    # pinned invitation sender without the invitation subject is
    # still refused on the missing pass pattern.
    env = Env()
    out = ib.watch_intake(
        [cand("e1e1e1e1e1e1e1e1", 10, "Your weekly summary",
              sender="Pruthvi Desai via LinkedIn "
                     "<messaging-digest-noreply@linkedin.com>")],
        now=NOW, **env.kw())
    check("q22 message intake still refuses on subject mismatch",
          len(out["actionable"]) == 0
          and "subject" in out["refused"][0]["reason"], str(out))
    out = ib.invite_intake(
        [icand("e2e2e2e2e2e2e2e2", 10,
               subject="Sara Kim sent you a message")],
        now=NOW, **env.kw())
    check("q23 invitation intake still requires its subject pattern",
          len(out["actionable"]) == 0
          and "does not match an invitation pass pattern"
          in out["refused"][0]["reason"], str(out))
    env.cleanup()


def test_jobalert_stripped_candidate() -> None:
    env = Env()
    # (r1) no html, no links, no LinkedIn URL in the body: the
    # email was never read in full — refused, not actionable.
    out = ib.jobalert_intake(
        [jcand("d1d1d1d1d1d1d1d1", 120,
               "Your job alert for Machine Learning Engineer")],
        now=NOW, **env.kw())
    check("r1 stripped jobalert candidate refused, not actionable",
          len(out["actionable"]) == 0 and len(out["refused"]) == 1
          and out["refused"][0].get("consumed") is False
          and "not read in full" in out["refused"][0]["reason"],
          str(out))
    state = ib.load_state(env.state, env.md)
    check("r2 stripped candidate NOT marked processed",
          "d1d1d1d1d1d1d1d1" not in state["processed"], str(state))
    # (r3) the same email re-fed in full passes with its jobs.
    out = ib.jobalert_intake(
        [jcand("d1d1d1d1d1d1d1d1", 120,
               "Your job alert for Machine Learning Engineer",
               html=ALERT_HTML)], now=NOW, **env.kw())
    check("r3 same email re-fed in full passes with jobs",
          len(out["actionable"]) == 1
          and len(out["actionable"][0]["jobs"]) == 3, str(out))
    env.cleanup()


def test_daily_finish() -> None:
    env = Env()
    ok = {"conversations": {"in_scope": 2, "replied": 1,
                            "no_reply": 1, "wu_decision": 0},
          "invitations": {"found": 1, "accepted": 1, "skipped": 0},
          "alerts": {"found": 3, "screened": 2},
          "alerts_not_on_revelio": [],
          "note": "one alert email left for the next run"}
    out = ib.daily_finish(ok, now=NOW, log_path=env.log)
    check("s1 daily-finish writes the run line, verified",
          out["verified"] and "Daily inbox check" in out["line"]
          and "alert emails 3 (screened 2)" in out["line"]
          and "one alert email left" in out["line"], str(out))
    check("s2 run line landed in the log",
          out["line"] in env.log.read_text(encoding="utf-8"))
    before = env.log.read_text(encoding="utf-8")
    bad_cases = (
        ("s3 missing alerts section refused whole",
         {"conversations": {"in_scope": 0, "replied": 0,
                            "no_reply": 0, "wu_decision": 0},
          "invitations": {"found": 0, "accepted": 0,
                          "skipped": 0}}),
        ("s4 screened > found refused",
         {"conversations": {"in_scope": 0, "replied": 0,
                            "no_reply": 0, "wu_decision": 0},
          "invitations": {"found": 0, "accepted": 0,
                          "skipped": 0},
          "alerts": {"found": 1, "screened": 2}}),
        ("s5 handled > in_scope refused",
         {"conversations": {"in_scope": 1, "replied": 2,
                            "no_reply": 0, "wu_decision": 0},
          "invitations": {"found": 0, "accepted": 0,
                          "skipped": 0},
          "alerts": {"found": 0, "screened": 0}}))
    for name, bad in bad_cases:
        try:
            ib.daily_finish(bad, now=NOW, log_path=env.log)
            raised = False
        except ValueError:
            raised = True
        check(name, raised
              and env.log.read_text(encoding="utf-8") == before)
    env.cleanup()


def test_daily_finish_not_on_revelio() -> None:
    env = Env()
    with env.log.open("a", encoding="utf-8") as fh:
        fh.write(
            "\n## 2026-11-12 — LinkedIn Recommended applications"
            " batch — 2026-11-12\n\n"
            "- [8:14 AM CST, Thu Nov 12, 2026] STOCKED — #740 "
            "Azx, Data Scientist — Remote — apply: https://"
            "example.com/azx/apply. SOURCE TAG: LINKEDIN_ALERT. "
            "(Recorded by stock program.)\n"
            "- [8:15 AM CST, Thu Nov 12, 2026] SKIPPED — company "
            "not found on Revelio and the LinkedIn fallback "
            "check gave no usable counts — dropped (the user, Nov 13, "
            "2026); not a merits verdict — the company is NOT "
            "blocked and a later posting is checked fresh — "
            "#740 Azx, Data Scientist. (Recorded by stock "
            "program.)\n"
            "- [8:16 AM CST, Thu Nov 12, 2026] GATE PASS — #741 "
            "Evlo AI — LinkedIn People: #741 Evlo AI 240 / 12 "
            "(5.0%) → verdict PASS. (Recorded by stock "
            "program.)\n")
    base = {"conversations": {"in_scope": 0, "replied": 0,
                              "no_reply": 0, "wu_decision": 0},
            "invitations": {"found": 0, "accepted": 0,
                            "skipped": 0},
            "alerts": {"found": 2, "screened": 2}}

    def refused(summary) -> bool:
        before = env.log.read_text(encoding="utf-8")
        try:
            ib.daily_finish(summary, now=NOW, log_path=env.log)
        except ValueError:
            return env.log.read_text(encoding="utf-8") == before
        return False

    check("t1 named not-on-Revelio company with NO fallback "
          "record refused (linkedin_no_counts)",
          refused(dict(base, alerts_not_on_revelio=[
              {"company": "FDE Times",
               "resolution": "linkedin_no_counts"}])))
    check("t2 named not-on-Revelio company with NO fallback "
          "record refused (linkedin_packet)",
          refused(dict(base, alerts_not_on_revelio=[
              {"company": "Superworq",
               "resolution": "linkedin_packet"}])))
    check("t3 field missing while alerts.found > 0 refused",
          refused(base))
    check("t4 wrong resolution refused: Azx has only the "
          "no-counts drop on record, not a packet",
          refused(dict(base, alerts_not_on_revelio=[
              {"company": "Azx",
               "resolution": "linkedin_packet"}])))
    check("t5 unknown resolution refused",
          refused(dict(base, alerts_not_on_revelio=[
              {"company": "Azx", "resolution": "dropped"}])))
    ok = dict(base, alerts_not_on_revelio=[
        {"company": "Azx", "resolution": "linkedin_no_counts"},
        {"company": "Evlo AI", "resolution": "linkedin_packet"}])
    out = ib.daily_finish(ok, now=NOW, log_path=env.log)
    check("t6 finish accepted when both resolutions are on "
          "record (DROPPED_NO_REVELIO line + GATE PASS naming "
          "LinkedIn People)",
          out["verified"]
          and out["alerts_not_on_revelio"]
          == ok["alerts_not_on_revelio"], str(out))
    no_alerts = {"conversations": base["conversations"],
                 "invitations": base["invitations"],
                 "alerts": {"found": 0, "screened": 0}}
    out = ib.daily_finish(no_alerts, now=NOW, log_path=env.log)
    check("t7 field not required when no alert emails found",
          out["verified"] and out["alerts_not_on_revelio"] == [],
          str(out))
    env.cleanup()


def test_daily_finish_pending_fallback() -> None:
    env = Env()
    fb = Path(env.td.name) / "gate_fallback.json"
    gate_fallback_mod.open_pending("Owedco", run_label="test run",
                                   now=NOW, state_path=fb)
    summary = {"conversations": {"in_scope": 0, "replied": 0,
                                 "no_reply": 0, "wu_decision": 0},
               "invitations": {"found": 0, "accepted": 0,
                               "skipped": 0},
               "alerts": {"found": 1, "screened": 1},
               "alerts_not_on_revelio": []}
    before = env.log.read_text(encoding="utf-8")
    refused = False
    try:
        ib.daily_finish(summary, now=NOW, log_path=env.log,
                        fallback_state_path=fb)
    except ValueError:
        refused = True
    check("u1 finish refused while a fallback order opened "
          "today is still open — the tracked state is the "
          "stronger source, even with a clean summary",
          refused
          and env.log.read_text(encoding="utf-8") == before)
    gate_fallback_mod.clear_pending("Owedco", state_path=fb)
    out = ib.daily_finish(summary, now=NOW, log_path=env.log,
                          fallback_state_path=fb)
    check("u2 finish accepted once the owed fallback is "
          "resolved", out["verified"], str(out))
    env.cleanup()


def main() -> int:
    test_intake_genuine_and_stale()
    test_intake_triage()
    test_intake_person_fallback_and_batch_dup()
    test_watch_record()
    test_check_claim()
    test_daily_scope()
    test_daily_record()
    test_seed_and_malformed()
    test_real_format()
    test_gmail_search_config()
    test_pinned_sender()
    test_invite_intake()
    test_invite_record()
    test_invite_config()
    test_job_alert_sender()
    test_jobalert_intake()
    test_jobalert_consumer_scopes()
    test_jobalert_config_and_other_filters()
    test_jobalert_stripped_candidate()
    test_daily_finish()
    test_daily_finish_not_on_revelio()
    test_daily_finish_pending_fallback()
    if FAILS:
        print(f"\n{len(FAILS)} FAILURE(S): {FAILS}")
        return 1
    print("\nALL INBOX TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
