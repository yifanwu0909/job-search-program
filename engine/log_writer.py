"""log_writer.py — the ONE writer for outreach-log entries.

Append-only, house format: "- [H:MM AM CST, Wed Nov 4, 2026] <ENTRY>".
Entries carry a "(spine)" marker so program-written lines are distinguishable
from agent-written ones during shadow mode. The writer never edits or deletes.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from state import CT, fmt_ts


def now_ct() -> datetime:
    return datetime.now(CT)


def append_entry(log_path: str, text: str, when: datetime | None = None) -> str:
    """Append one entry; returns the exact line written."""
    when = when or now_ct()
    line = f"- [{fmt_ts(when)}] {text.strip()}"
    p = Path(log_path)
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    prefix = "" if (not existing or existing.endswith("\n")) else "\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(prefix + line + "\n")
    return line


def _who(item) -> str:
    return f"#{item['id']} {item['company']}, {item['role']}"


def claim(item, actor: str) -> str:
    return f"CLAIM — {_who(item)} claimed by {actor} (spine program)."


def submitted(item, portal: str, confirmation: str, source: str,
              submitted_by: str = "") -> str:
    by = f" BY {submitted_by}" if submitted_by else ""
    src = f" SOURCE TAG: {source}." if source else ""
    return (f"SUBMITTED{by} (page-confirmed) — {_who(item)} ({portal}). "
            f"Confirmation: {confirmation}.{src} (Recorded by spine program.)")


def email_verified(item, message_id: str, sender: str, subject: str) -> str:
    return (f"EMAIL-VERIFIED — {_who(item)} (Gmail check run by spine program): "
            f"confirmation FOUND — \"{subject}\" ({sender}, Gmail {message_id}). "
            f"DO NOT RE-APPLY.")


def skipped(item, reason: str) -> str:
    return f"SKIPPED — {reason} — {_who(item)}. (Recorded by spine program.)"


def staged(item, step: str, blocker: str) -> str:
    return (f"STAGED FOR TAP SESSION — {_who(item)}, step: {step} "
            f"(true blocker reached: {blocker}). (Recorded by spine program.)")


def unstaged(item, note: str = "") -> str:
    """Return a staged / captcha item to the bench (audit fix, Nov 4, 2026:
    the unstaged event type existed but no code path could write it)."""
    n = f" {note}" if note else ""
    return (f"UNSTAGED — {_who(item)} returned to the bench.{n} "
            f"(Recorded by spine program.)")


def captcha(item, step: str, note: str = "") -> str:
    """A CAPTCHA is NOT a tap-session staging: it is a bot-check the user solves
    by taking the browser, so it gets its own entry shape (and its own
    event type — never a staged event, never a why code)."""
    n = f" {note}" if note else ""
    return (f"AWAITING CAPTCHA TAKEOVER — {_who(item)}, step: {step} — "
            f"bot-check on screen; the user solves it by taking the browser, "
            f"not a tap.{n} (Recorded by spine program.)")


def manual_packet(item, portal: str, step: str, note: str = "") -> str:
    """A MANUAL PACKET is NOT a session item at all: the application
    cannot be finished in Muse's browser (Lever rule, Gem upload,
    IP-blocked captcha), so the run hands the user the packet — apply link,
    tailored resume, every field value — and she submits it from her
    own device and reports back. Its own entry shape and its own event
    type (`packet`), superseding any captcha/staged park (the user, Nov 6,
    2026: captcha and manual items get one code-built track file)."""
    n = f" {note}" if note else ""
    return (f"MANUAL PACKET — HANDED TO WU — {_who(item)}, portal: "
            f"{portal}, step: {step} — the user submits this one herself "
            f"from her own device and reports back; Muse records it "
            f"on her report.{n} (Recorded by spine program.)")


def limbo(item, note: str) -> str:
    return (f"IN LIMBO — {_who(item)}: {note} "
            f"(30-minute Gmail check decides; never re-apply while unresolved.)")


def post_submit_pending(item, note: str) -> str:
    return f"POST-SUBMIT VALIDATION PENDING — {_who(item)}: {note}"


def friction(item, signal: str) -> str:
    who = _who(item) if item else "batch"
    return (f"FRICTION — stop-at-first-friction triggered by {who}: {signal}. "
            f"Friction flag set by spine program (lane scope in the flag: "
            f"LinkedIn-sourced trigger = LinkedIn lane stopped, Jobright "
            f"continues per the Nov 7, 2026 fallback; other = all lanes "
            f"stopped).")


def correction(text: str) -> str:
    return f"CORRECTION — {text}"
