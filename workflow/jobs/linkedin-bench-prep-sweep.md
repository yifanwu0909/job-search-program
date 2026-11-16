---
id: linkedin-bench-prep-sweep
title: Bench prep sweep — build missing tailored resumes (every 30 min)
enabled: true
owner: goal:YOUR-GOAL
mode: task
schedule:
  kind: interval
  timezone: America/Chicago
  at: 2026-11-15T09:36:50
  every: 30m
timeout_secs: 3600
delivery:
  - chat_id: YOUR-MAIN-CHAT-ID
metadata:
  tags: [cron:automatic-interval-anchor]
  originating_chat_context_json: '{"chat_id":"YOUR-MAIN-CHAT-ID","origin_provider":"main","chat_kind":"direct","event_kind":"message","require_mention":false,"device_id":"YOUR-DEVICE-ID"}'
  presentation_locale: en-US
---
BENCH PREP SWEEP — goal YOUR-GOAL. Purpose (the user fix pass, Nov 15, 2026, closing nightly-audit finding NA-2026-11-15-1): the Nov 14 window closed at 0 verified of 60 because gate-passed bench items sat all day with no tailored resume and spine.py next could not serve them. Workers now prep at stocking (worker_template.md PREP AT STOCKING), and this sweep is the backstop: any bench item in the CURRENT window that still lacks its tailored resume gets one built by you, so it becomes servable the same window.

Work in ~/workspace/goals/YOUR-GOAL/program/ with the outreach log at ../hidden_files/outreach-log.md and resumes in ../hidden_files/tailored-resumes/.

1. Run `python3 spine.py status` (current window) and `python3 spine.py next`. The bench items failing ONLY the tailored_resume_on_disk check (named in next's skipped list, or bench items whose parsed resume_file is empty / file missing) are your work list. If none, end quietly — no log entry, no chat message.
2. For each failing item (at most 4 per run, oldest stocked first): read its stocked payload from program/events.stocked.json (company, role, url). Fetch the posting text from the url (text fetch is enough; do not open a browser session, do not sign in anywhere). Build the tailored resume from the BASE RESUME ONLY, following the established build pattern: reuse hidden_files/build_prep_20261104.py's HEAD and EXP, write a tailored Career Summary + Technical Skills matched to the posting's keywords with every fact taken from the base resume (employment exactly YOUR_LATEST_EMPLOYER / YOUR_EMPLOYER / YOUR_EMPLOYER; NEVER name YOUR_CURRENT_EMPLOYER), run the text through the humanizer rules (~/workspace/custom-skills/humanizer/SKILL.md, facts unchanged), save <company-slug>-<role-slug>-<posting-id-or-short-hash>.html and .pdf into hidden_files/tailored-resumes/ using hidden_files/make_pdf_bold.py, and read-back verify the PDF text: header line "Your City, ST | (000) 000-0000 | you@example.com | LinkedIn | U.S. Green Card Holder" present, zero "YOUR_CURRENT_EMPLOYER".
3. Register each built resume by appending ONE entry to the outreach log in this exact shape: "- [<time> CST, <Day Mon DD, YYYY>] PREP READY — #<id> <Company>, <Role> — tailored resume <file>.pdf (#<id>) built from the base resume only and read-back verified (header contact line + U.S. Green Card Holder printed; zero YOUR_CURRENT_EMPLOYER). (Bench prep sweep.) humanizer: passed"
4. Re-run `python3 spine.py status` and `python3 spine.py next` and confirm each prepped item no longer fails tailored_resume_on_disk. Append one closing line to the outreach log naming what you prepped and the verification result. If a build fails (posting gone, payload missing, parse collision on the item number), log that as a named blocker in the same closing line and move on — never force it, never re-stock, never submit anything.
5. Scope limits: bench items of the current window only. Never touch staged, captcha, limbo, packet, or submitted items. Never submit an application, send a message, or change any rule. No chat delivery — your record is the outreach log; surface nothing to the user from this job.
