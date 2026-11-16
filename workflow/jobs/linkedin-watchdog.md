---
id: linkedin-watchdog
title: LinkedIn system watchdog (daily)
enabled: true
owner: goal:YOUR-GOAL
mode: task
schedule:
  kind: daily
  timezone: America/Chicago
  time: 11:23:00
timeout_secs: 1800
delivery:
  - chat_id: YOUR-MAIN-CHAT-ID
metadata:
  originating_chat_context_json: '{"chat_id":"YOUR-MAIN-CHAT-ID","origin_provider":"main","chat_kind":"direct","event_kind":"message","require_mention":false,"device_id":"YOUR-DEVICE-ID"}'
  presentation_locale: en-US
---
Daily watchdog for the user's LinkedIn job-search system. Do NOT open LinkedIn or browse — read files only: the outreach log at ~/workspace/goals/YOUR-GOAL/hidden_files/outreach-log.md, the quick-check state file at ~/workspace/goals/YOUR-GOAL/hidden_files/inbox-quick-check-state.md, and the email-scan state file at ~/workspace/goals/YOUR-GOAL/hidden_files/application-email-scan-state.md. CHECKS: (1) yesterday's daily outreach run has a dated log entry; (2) at least one hourly inbox pass is logged within the 7:00 AM–10:00 PM CT window today since 7:00 AM (allow morning lag: only flag if no pass is logged by this 11:23 AM check); (3) during work hours (9 AM–5 PM CT) the quick-check state's last-check time is not stale by more than 1 hour; (4) the email-scan state file was updated within the last 2 hours; (5) a batch section exists in the log for the applications batch that started yesterday (~8:23 AM CT); (6) during an open batch window (8:23 AM CT → next day 8:23 AM CT), the batch guardian (linkedin-batch-guardian) has run within the last ~1 hour — its "Guardian [date/time CT]" lines in the outreach log are the evidence — report an anomaly if no guardian line is that fresh. SEGMENT-END NOTE (added Nov 1, 2026, audit #7 fix N24): the applications batch job works in segments; a segment that ends with work still queued shows scheduler status "failed" ("worker reported that the work is not finished") and raises its consecutive-failures count — that is a SEGMENT END, not a death. Judge the batch from the log (dispositions, submissions, guardian lines, BATCH CLOSED markers) and in-flight runs, never from that status string alone; do not report a segment end as an anomaly when the guardian's lines are fresh and the window's accounting is progressing. REPORTING: message the user in chat ONLY if something is missing or stale — name exactly what. If everything is healthy, send no chat message. Either way, append ONE line to the outreach log: 'Watchdog [date/time CT]: all healthy' or 'Watchdog [date/time CT]: ANOMALY — [what]'. FINAL STEP (strengthened Nov 1, 2026, audit #7 fix N40): appending that line is the run's LAST step before ending — the run is not complete until the line is in the log; if the append fails for any reason, say so explicitly in the chat report (even on an otherwise healthy run) so a missing Watchdog line never passes silently. Report times to the user in her current reporting timezone (Hawaii time Nov 1–6, 2026; Pacific Oct 31, 2026; Central otherwise).
