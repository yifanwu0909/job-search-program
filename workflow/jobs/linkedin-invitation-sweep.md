---
id: linkedin-invitation-sweep
title: LinkedIn invitation sweep (hourly)
enabled: true
owner: goal:YOUR-GOAL
mode: task
schedule:
  kind: interval
  timezone: America/Chicago
  every: 1h
timeout_secs: 1800
delivery:
  - chat_id: YOUR-MAIN-CHAT-ID
---

LinkedIn invitation sweep for the user — the connection-invitation email sweep runs ONCE EVERY HOUR, 24 times a day (set at the user's direction: the 15-minute message-watch frequency was excessive, and four times a day was not enough). Each run looks ONLY at the PAST 2 HOURS of Gmail — one hour of overlap, so a delayed run cannot leave a gap. The four-times-daily inbox sweep (linkedin-inbox-replies) remains the backstop over the past 12 hours; the shared processed pool in program/state/inbox.json means an invitation handled by either run is never seen by the other again.

IN CODE: scope, dedupe, triage and record run through the program's packets, never by judgment in this body. Run from the program folder: `python3 spine.py inbox format` prints the contract (section 6 INVITATION INTAKE, section 7 INVITATION RECORD).

STEP 1 — FIND: run the pinned search (rules.yaml inbox.invitation_hourly_search), limited to the PAST 2 HOURS (append the time bound at search time): from invitations@linkedin.com — SENDER-ONLY, no subject condition, ever (the user's LinkedIn notifications are configured so that address sends connection invitations and nothing else). Read each candidate email IN FULL and build the candidates JSON exactly as the format specifies; hand EVERY find to `spine.py inbox invite-intake`. The code refuses anything from another sender, anything stale, anything already processed, and anything matching the group-invitation or ad/marketing patterns, and marks every refusal processed so it never resurfaces. Work ONLY the actionable list. If it is empty, end silently.

STEP 2 — ACCEPT: for each actionable item, open its accept_url (the href behind the email's Accept button — it redirects and connects the user to that person; never accept through LinkedIn's invitations page). If accept_url is null, open the email itself and click its Accept button instead. Verify on the landing page that the invitation was actually accepted before recording anything. If a sign-in is needed, use the user's saved LinkedIn login; an email-delivered sign-in code may be retrieved from Gmail for the first code step only. If a code expires or is rejected, a second code is needed, or a CAPTCHA or security checkpoint appears: STOP before touching it, hold the page live, and alert the user in chat — never click a CAPTCHA and never push through a checkpoint.

STEP 3 — RECORD AND REPORT: return every worked item through `spine.py inbox invite-record` (gmail_id, person, outcome accepted | skipped). Report only items the record step verifies. Message the user in chat naming each person whose invitation was accepted. Silent when nothing new arrived.

Report times in the user's timezone.
