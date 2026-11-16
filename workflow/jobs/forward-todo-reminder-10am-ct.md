---
id: forward-todo-reminder-10am-ct
title: Forward-move to-do reminder (10 AM CT)
enabled: true
owner: goal:YOUR-GOAL
mode: task
schedule:
  kind: daily
  timezone: America/Chicago
  time: 10:00:00
delivery:
  - chat_id: 48d41ee3-3ef0-4df2-b23b-dd30c3b929fa
metadata:
  originating_chat_context_json: '{"chat_id":"48d41ee3-3ef0-4df2-b23b-dd30c3b929fa","origin_provider":"main","chat_kind":"direct","event_kind":"message","require_mention":false,"device_id":"8b62e88c-9a8a-0c7b-ef2b-308ea1ee43bc"}'
  presentation_locale: en-US
---
FORWARD-MOVE TO-DO REMINDER — daily at 10:00 AM America/Chicago (the user, Nov 6, 2026: "if move forward, add to to-do list. And remind me 10am CT").

WHAT THIS IS: when the application-email scan (job-application-email-followups) judges an email as forward-moving, the item goes on the user's to-do list: the program (checks/email_sweep.py) keeps the to-do record and builds the track file program/state/forward_todos.json with every forward item's important info, and a matching to-do sits in her Google Tasks default list ("My Tasks"). This job is the daily reminder for the still-open ones. It never replies to email, never books anything, and never creates or completes a to-do on its own — except the Google-Tasks completion sync in Step 2.

STEP 1 — GET THE OPEN TO-DOS (code first): from ~/workspace/goals/YOUR-GOAL/program run:
python3 checks/email_sweep.py --tz America/Chicago --list-todos
It prints {"open_todos": [...]} — each entry: gmail_id, item_id, company, role, subtype, gist, deadline_iso (or null), proposed_times (or null), google_task_id (or null). This list — the same record the track file state/forward_todos.json is built from — is the source of truth for what to remind about.

STEP 2 — GOOGLE TASKS COMPLETION SYNC: for each open to-do whose google_task_id is not null, read that task:
 /opt/hatch/bin/hatch_gws_cli tasks tasks get --params '{"tasklist":"@default","task":"<google_task_id>"}'
If the task's status is "completed", the user has checked it off herself: close the program's to-do with: python3 checks/email_sweep.py --tz America/Chicago --complete-todo <gmail_id> — and do NOT remind her about that item. If the read fails or the task is still needsAction, keep the to-do open and remind as normal.

STEP 3 — REMIND, OR STAY SILENT: if no open to-dos remain after Step 2, end silently — no chat message at all. If any remain, message the user in the main chat with ONE reminder listing every open item, sorted by deadline (earliest first; items with no deadline last). For each item: company — role (subtype); the one-line gist; the deadline and any proposed times converted to the user's reporting timezone (Hawaii Nov 1–6, 2026 → Pacific/Honolulu; home city Central otherwise — the 10:00 AM CT fire time itself never changes). Keep it plain and short. Do not re-report old email content beyond the gist, deadline, and proposed times already in the to-do record.

STEP 4 — FAILURE: if the --list-todos command fails, end silently this run (the next day's run retries); do not invent a list from the log or from Google Tasks alone.
