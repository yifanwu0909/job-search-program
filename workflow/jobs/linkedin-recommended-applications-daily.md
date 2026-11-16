---
id: linkedin-recommended-applications-daily
title: LinkedIn Recommended applications (two-lane, 24h spread)
enabled: true
owner: goal:YOUR-GOAL
mode: task
schedule:
  kind: daily
  timezone: America/Chicago
  time: 08:23:00
timeout_secs: 86400
delivery:
  - chat_id: 48d41ee3-3ef0-4df2-b23b-dd30c3b929fa
metadata:
  originating_chat_context_json: '{"chat_id":"48d41ee3-3ef0-4df2-b23b-dd30c3b929fa","origin_provider":"main","chat_kind":"direct","event_kind":"message","require_mention":false,"device_id":"5ac11a8e-9761-4273-8a82-e352148c5f7d"}'
  presentation_locale: en-US
---
LinkedIn Recommended applications — DAILY KICKOFF ONLY (rebuilt Nov 6, 2026 around the worker supervisor, program/supervisor.py). The batch itself is run by template workers (program/worker_template.md) launched by the batch guardian under the supervisor's code verdict. This job's whole job is to open the window on time — it is an alarm clock, not a worker.

1. Append the new window's batch section header to the outreach log at ~/workspace/goals/YOUR-GOAL/hidden_files/outreach-log.md (skip this step if a header for today's window date already exists): a line "## <YYYY-MM-DD> — LinkedIn Recommended applications batch — <YYYY-MM-DD>" (the window date = today in America/Chicago, in BOTH positions — this is the exact format state.py's SECTION_RE requires; the nightly audit had to repair the 2026-11-07 header by hand because this step once specified a shorter form the parser cannot see, and the invisible section zeroed the new window's counts) followed by one entry line: "- [<current time CT>] BATCH STARTED — window <date> 8:23 AM CT → next day 8:23 AM CT. Target 60 verified in TOTAL across sources (program source configuration: LinkedIn 0, Jobright 60, Indeed 60, LinkedIn alerts 60 — the shared TOTAL of 60 binds and the source figures never sum). Workers are launched by the supervisor/guardian from program/worker_template.md."
2. Trigger a guardian pass: cron.run on linkedin-batch-guardian. Its supervisor verdict (window open, no worker heartbeat yet) starts the first worker.
3. End. Do NOT screen jobs, apply to anything, or launch a worker yourself — there is exactly one launch path (the guardian's), so two starters can never collide. If the guardian trigger fails, note it in the log header entry and end; the guardian's regular 30-minute pass starts the worker anyway.
