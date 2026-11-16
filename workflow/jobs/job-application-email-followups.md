---
id: job-application-email-followups
title: Job application follow-up email scan (every 30 min)
enabled: true
owner: goal:linkedin-ai-recruiter-outreach-weekly
mode: task
schedule:
  kind: interval
  timezone: America/Chicago
  at: 2026-11-05T20:00:00
  every: 30m
timeout_secs: 1800
delivery:
  - chat_id: 48d41ee3-3ef0-4df2-b23b-dd30c3b929fa
metadata:
  originating_chat_context_json: '{"chat_id":"48d41ee3-3ef0-4df2-b23b-dd30c3b929fa","origin_provider":"main","chat_kind":"direct","event_kind":"message","require_mention":false,"device_id":"8b62e88c-9a8a-0c7b-ef2b-308ea1ee43bc"}'
  presentation_locale: en-US
---
APPLICATION-EMAIL SCAN — every 30 minutes (:00/:30 Central). The script (~/workspace/goals/linkedin-ai-recruiter-outreach-weekly/program/checks/email_sweep.py) does all bookkeeping: watch list, past-hour search, dedupe, recording, delivery timing, to-do records. You do the reading and judging — the language work. Never hand-run searches, never hand-write scan records.

SCOPE: only email about jobs the user has actually applied for (her narrow exception to the no-inbox-monitoring rule). Chat-report FORWARD MOVEMENT ONLY; everything else is filed silently. Never reply to any email in any step — if a reply is needed, the chat report is the deliverable and the user decides.

TIMEZONES: scheduling logic stays America/Chicago. Report times to the user in the timezone she is in on that date; pass that zone to the script as --tz.

STEP 1 — WORK LIST: from ~/workspace/goals/linkedin-ai-recruiter-outreach-weekly/program run: python3 checks/email_sweep.py --tz <ZONE>. It prints ONE JSON: watch[] (item_id, company, role, submitted date, limbo flag), candidates[] (past hour only), held_due[], open_todos[], forward_progress counts. The watermark advances only when you complete the run (Step 5).
TO-DO SYNC (right after the work list): for each open_todos entry with google_task_id null, create its Google Task per Step 4 and store the ID with: python3 checks/email_sweep.py --set-todo-task <gmail_id> <task_id>. Never create a second Google Task for a Gmail ID that already has one.

STEP 2 — DELIVER WHAT IS DUE: for each held_due item, message the user in chat: company, role, type, sender and date, a one-line gist, and any deadline or proposed times (converted to the user's reporting timezone); if it proposes call/interview times, note how they sit against her standing availability (free for calls after 2:00 PM CT) — information only. Then run: python3 checks/email_sweep.py --mark-delivered <gmail_id>. Never click scheduling links or book anything.

STEP 3 — READ AND JUDGE: skim candidates; open in full (/opt/hatch/bin/hatch_gws_cli gmail +read --id <gmail_id> --format json) any message that could concern a watched application — when in doubt, open it. Exactly ONE judgment per opened message. The kinds:
- forward — the company is moving her forward: interview requests or scheduling asks (a scheduling link with no specific times still counts); next-step notices (assessments, take-home tasks, questionnaires, background-check or reference requests tied to her candidacy); offers and offer-related mail. NOT forward: a receipt's conditional "we will reach out if you are a match" — that is a confirmation.
- rejection — any not-moving-forward decision: rejections, waitlist/hold notices that are not an advance, role-filled notices. Judge the BODY, not the subject.
- confirmation — a submission-confirmation receipt for an application already recorded as submitted.
- limbo_confirmation — a submission-confirmation receipt for a watch entry flagged limbo.
- process — submission-process mail (account verification / identity / code mail tied to an application). Never copy a code value into any record or message.
- out_of_scope — everything else: newsletters, marketing, product mail unrelated to her candidacy, mail that merely MENTIONS a watched company without being about her application, and anything about companies not on the watch list.
Candidates you only skimmed and did not open need no judgment. Matching: use the watch entry's item_id when you can name the exact application. If the email ties to a DIFFERENT role at the same company, use that company's entry and pass the email's role as "role". If the company is known but the role is unclear, pass item_id null with the company and the script resolves the company-level entry.

STEP 4 — RECORD EACH JUDGMENT: write a JSON file (one per message) with fields: gmail_id; kind; item_id (or null); company (only when item_id is null); role (only when the email ties to a different role than the logged one); subtype (forward only: "interview request", "next step", or "offer"); gist (one line, your own words); sender; subject; date_iso (the message's date as an ISO datetime); deadline_iso (only when the email states a response deadline, as an ISO datetime in the user's current zone; otherwise null); proposed_times (text, only when the email proposes any; otherwise null). Then run: python3 checks/email_sweep.py record <file> --tz <ZONE>.
- If the script REFUSES a judgment (already recorded, or no watched application), do not force it — re-check your match; a message that truly matches nothing watched is out_of_scope.
- HANDOFF CHECK: every record result carries "understood" and "verified" (the script re-read the records to prove the judgment landed). If "verified" is false, check "problems", fix the cause, and record once more; if it still fails, treat it as a script failure (Step 6).
- For each forward item with deliver_now = true: message the user as in Step 2, then run: python3 checks/email_sweep.py --mark-delivered <gmail_id>. deliver_now = false means the script is holding it for delivery hours — say nothing; it returns as held_due at the next in-hours run. (The script applies the under-24-hour deadline exception itself.)
- TO-DO CREATION (forward only, whether deliver_now is true or false): if the record result's todo has google_task_id null, create ONE Google Tasks to-do in the user's default list: /opt/hatch/bin/hatch_gws_cli tasks tasks insert --params '{"tasklist":"@default"}' --json '{"title":"Follow up: <company> — <role> (<subtype>)","notes":"<gist> Deadline: <deadline_iso or none>. Proposed times: <proposed_times or none>. Gmail <gmail_id>","due":"<deadline date as RFC3339 midnight UTC, only when deadline_iso exists>"}'. Omit "due" entirely when there is no deadline. Then store the returned task "id" with: python3 checks/email_sweep.py --set-todo-task <gmail_id> <task_id>. If the insert fails, leave google_task_id null and move on — the Step 1 sync retries it next run. A to-do stays open until the user says the item is done; reporting it does NOT close it.

STEP 5 — COMPLETE THE RUN: run: python3 checks/email_sweep.py --complete --tz <ZONE>. This writes the run's summary entry and advances the watermark. If you cannot finish judging (a tool failure mid-run), do NOT complete: the next run re-lists the unrecorded candidates, and recorded ones are never reprocessed.

STEP 6 — SCRIPT FAILURE: if the work-list or complete command exits nonzero or prints no JSON, append one line to ~/workspace/goals/linkedin-ai-recruiter-outreach-weekly/hidden_files/application-email-scan-state.md: "- <current date/time CT> — SCRIPT FAILURE (email_sweep.py): <the error, one line>. Scan not completed this run." Then end silently. A record-command refusal for ONE message is not a script failure — handle it per Step 4.
