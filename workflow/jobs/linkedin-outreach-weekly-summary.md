---
id: linkedin-outreach-weekly-summary
title: LinkedIn outreach weekly summary
enabled: true
owner: goal:YOUR-GOAL
mode: task
schedule:
  kind: weekly
  timezone: America/Chicago
  time: 19:23:00
  dow: [Sun]
timeout_secs: 1800
delivery:
  - chat_id: YOUR-MAIN-CHAT-ID
metadata:
  tags: [cron:flexible-time]
  originating_chat_context_json: '{"chat_id":"YOUR-MAIN-CHAT-ID","origin_provider":"main","chat_kind":"direct","event_kind":"message","require_mention":false,"device_id":"YOUR-DEVICE-ID"}'
  presentation_locale: en-US
---
REPORTING TIMEZONE: report times in the user's current timezone. Keep all actual work, schedules, and availability in the user's home timezone exactly as set — convert for display only.

Weekly summary of the user's LinkedIn outreach (daily batches run under the job "LinkedIn AI recruiter outreach (daily batches)").

PERIOD (Oct 31, 2026 audit fix 27c — single definition): The period covered is defined ONCE as "since the previous summary run", and that definition governs. Do NOT use any other conflicting period definition. Read the outreach log at ~/workspace/goals/YOUR-GOAL/hidden_files/outreach-log.md and total the entries since the previous summary run. State the actual dates covered in the report itself.

Send the user one concise chat summary covering:
- Total invitations sent and verified pending in that period, with the per-day counts if the log has them.
- INVITATION BREAKDOWN (Oct 31, 2026 audit fix 27a): Break invitations down using the same categories the daily reports use: hiring contacts (recent applications), people-hiring list, carry-overs, network suggestions, search groups.
- APPLICATIONS SUBMITTED (Oct 31, 2026 audit fix 27b): Applications submitted in the period, taken from the log's LinkedIn Recommended applications batch sections plus any one-off application entries recorded in the log — give the total and, where the log records them, the company/role list.
- INBOX REPLIES (Oct 31, 2026 audit fix 27b; counting defined Nov 1, 2026, audit #14 fix L4): Inbox replies sent in the period, as recorded in the log — give the total count for the period. COUNTING RULE: the total = (a) replies logged by the inbox jobs (hourly sweep passes, quick-check passes, and main-session replies in those same threads) PLUS (b) one-off messages sent on the user's behalf in the period outside those passes (for example a the user-directed thank-you or a one-time reply). Always state the split in the report (e.g., "44 = 37 inbox-pass replies + 7 one-off/directed messages") so the total is reproducible from the log.
- APPLICATION EMAIL-SCAN OUTCOMES (Oct 31, 2026 audit fix 27b): Application email-scan outcomes recorded in the log for the period (for example interview requests, screening/next steps, assessments, rejections, and decisions found by the Gmail follow-up scan) — summarise what the log shows; report only, do not reply to any email.
- Whether the weekly LinkedIn invitation limit was reached at any point in the period, and at what count — say plainly if it was not reached.
- Any blockers recorded (sign-in loss, restriction warnings, note-limit messages).

If the log is missing or has no entries for the period, say that no outreach activity was recorded this week. Keep it short — the user asked for totals and limit status, not the full name list; names are in the log if asked for.
