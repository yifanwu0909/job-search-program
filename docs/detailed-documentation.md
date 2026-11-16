# Detailed documentation

This file is the full technical documentation for the job search program. It began as the repository front page and was moved here when the front page was rewritten for new readers. The original text is kept as written. Sections added after it cover the mail flows, the running order of a day, where each main function lives, and what a new user has to provide.

---

# Application Program (spine, v1 — shadow mode)

Implements the design in `../hidden_files/application-program-design-2026-11-04.md`.
The outreach log remains the authoritative record; this program is a
deterministic reader/writer around it. Muse's judgment is spent on browser
control and exceptions — everything repetitive (counting, dedupe, slots,
pacing parameters, log format, verification checks) is code and data here.

## Files
- `config/answers.yaml` — the standing answer set (single copy). Applications
  NEVER name YOUR_CURRENT_EMPLOYER; employer history is the base resume (YOUR_LATEST_EMPLOYER
  latest). YOUR_CURRENT_EMPLOYER appears only under `replies_only`.
- `config/rules.yaml` — machine-checked parameters (targets, pacing, spacing,
  diversification, verification timing, true-blocker list, blocked-count check
  read from the log).
- `state.py` — parses the outreach log into structured state (items, latest
  dispositions, source tags, window tallies, company slots, limbo, staged,
  captcha, claims, blocked-list total). Same log in → same numbers out.
  Prose entries marked AWAITING CAPTCHA TAKEOVER — and staged entries whose
  step is a captcha — classify the item as captcha, never staged.
- `pipeline.py` — the loop driver. Emits ONE work-order JSON per pass with
  preconditions checked in code; consumes result JSONs; a `friction` result
  sets `state/FRICTION.flag`, which makes every `next` refuse until a logged
  all-clear (`clear-friction`).
- `log_writer.py` — the one writer: append-only, house format, CT timestamps.
- `verify.py` — Gmail confirmation check via the Gmail CLI (read-only; a
  not-found never triggers resubmission).
- `email_sweep.py` — the application-email scan's BOOKKEEPING
  half (added Nov 5, 2026; redesigned the same day at the user's direction:
  the script NEVER reads or judges email — reading and judging are
  Muse's work; an earlier same-day version that matched and classified
  in code mis-matched a Disney recruiter email to Care Access on a
  substring, which is why the line is drawn here). The script builds
  the watch list (submitted within 90 days: log parse UNION the scan
  state file's watch bullets; limbo = a limbo event with no submitted
  event, #180), computes the search window (THE PAST HOUR ONLY — the user,
  Nov 5, 2026; 30-minute runs overlap by 30 minutes), searches Gmail,
  and returns the UNRECORDED candidates
  (triage metadata untouched) plus the watch list as one JSON work
  list. Muse reads each candidate, judges it, and hands the judgment
  back as JSON; `record` writes the outreach-log entry + scan-state
  bullets via `log_writer` in the house formats, updates dedupe, and
  keeps a PROGRESS record for forward-moving items (held for delivery
  hours 8 AM–10 PM in the `--tz` zone / ready / reported;
  `--mark-delivered` advances it; a recorded deadline inside 24 hours
  delivers immediately — arithmetic only). FORWARD-MOVE TO-DOS
  (the user, Nov 6, 2026): recording a forward judgment also creates an
  open TO-DO (deduped by Gmail ID; `add-todo` backfills an
  already-recorded one; `--complete-todo` closes one;
  `--set-todo-task` stores its Google Tasks ID; `--list-todos`
  prints the open ones). On every sidecar save the script rebuilds
  THE TRACK FILE `state/forward_todos.json` — every forward item's
  important info (company, role, subtype, gist, deadline, proposed
  times, status, Gmail ID, Google Tasks ID), open items sorted by
  deadline. The scan agent mirrors each to-do into the user's Google Tasks
  "My Tasks" list, and the daily cron
  `forward-todo-reminder-10am-ct` (10:00 AM America/Chicago) reminds
  her of the still-open ones. `--complete` writes the run
  summary and advances the watermark to the run's start; a run that
  never completes never advances it. It never sends mail and never
  writes `events.jsonl`. The cron job
  `job-application-email-followups` carries the judging instructions.
  Tests: `tests/run_email_sweep_tests.py`.
- THE OPEN-PILES TRACK FILE `state/open_piles.json` (the user, Nov 6, 2026):
  every application still waiting on the user herself, across ALL windows —
  the captcha takeovers and the MANUAL PACKETS. A manual packet is
  now a first-class program state: `record` outcome `manual_packet`
  (requires a `step` saying why this browser cannot finish it) writes
  a `packet` event (own type in `events.py`, own rank-3 disposition
  in `state.py`, superseding a captcha/staged park) plus a MANUAL
  PACKET prose entry. `Spine.open_piles()` folds the event book
  (governing) with prose names/steps; `record_with_check` rebuilds
  the track file on EVERY recorded outcome, and `spine.py piles`
  rebuilds + prints it. An item leaves its pile only on a later
  submitted/skipped/unstaged event (for a packet: the user's reported
  own-device submission, recorded as `submitted`). Tests:
  `tests/run_events_tests.py` section (h).
- `stock.py` — stocking, standardized (Nov 5, 2026): the last
  hand-written part of the log, now written by code on the same
  pattern. `stock.py format` prints the return form; Muse fills it
  with researched facts (company, role, source, apply link, gate
  counts from an approved source, pay figure + city equivalent,
  verified tailored-resume file); `stock.py record` validates the
  form, assigns item numbers, dedupes against the log, decides the
  gate and pay verdicts in code (same rules.yaml thresholds as
  `spine.py gate`/`pay`), and writes the STOCKED / GATE PASS or
  SKIPPED / SEGMENT STATE / PREP READY lines itself in the formats
  the parser mines. THE HANDOFF IS VERIFIED BOTH WAYS: the result
  echoes the form as "understood" and the re-parsed log as
  "landed_as"; only "verified: true" items count as stocked —
  anything else is reported under "unverified" with the exact
  discrepancies. (Built after #364–#367 landed nameless: runs had
  stocked them in shorthand SEGMENT STATE lines the parser reads as
  hints only.) The directive reaches runs through the `stocking`
  block in `config/rules.yaml`, stamped by `next_order` on every
  response (the sign-in stamp pattern). Tests:
  `tests/run_stock_tests.py`.

## The parser contract — how state.py reads the prose log (Nov 5, 2026)

The user's order after the #381/#49 investigation: outcomes are read ONLY
from the canonical entry grammar the writers emit, never from free
text. The rules (enforced in `state.py`, trapped in
`tests/run_parser_contract_tests.py`):

- **Position, not keywords.** An outcome binds only from (a) the entry
  HEAD — a token from the closed outcome vocabulary (SUBMITTED,
  EMAIL-VERIFIED, SKIPPED, STAGED FOR TAP SESSION, AWAITING CAPTCHA
  TAKEOVER, UNSTAGED, IN LIMBO, POST-SUBMIT VALIDATION PENDING, …)
  binding the entry's own subject item — or (b) a legacy multi-item
  entry's segment, where the token must sit at the head of the first
  clause after the segment's identity (the first or second " — "/": "
  delimiter; a short label clause like "+10-MIN GMAIL CHECK (…):" may
  precede it), or in the plus-joined idiom ("CREDENTIAL TEST PASSED +
  SUBMITTED"). "NOT SUBMITTED" is a guard, never a submission.
- **Everything else is inert.** Reasons, quotes, URLs, parentheticals,
  bold markers, tallies, dedupe notes, and cross-references to other
  items ("duplicate of #182, which was verified") never create an
  outcome, an identity, or an item — however many outcome words they
  contain. This is the #381 fix: a SKIPPED entry whose reason mentions
  "verified" stays skipped.
- **Identities by position, not by word.** Company/role come only
  from canonical STOCKED / outcome entries: the text after "#NNN "
  up to the outcome delimiter, split at the first comma — except a
  closed legal-suffix token (Inc/LLC/Ltd/Corp/Co/GmbH/AG/BV/Pty/KK/
  SRL) after that comma shifts onto the company ("Smith, Inc."). A
  company literally named "Verified" or "Submitted LLC" and a role
  containing "submitted" therefore parse correctly. In the dash
  identity pattern, a bare verdict word (PASS/SKIP/HOLD) in the
  company slot is a screening shape, never a company — the #49 fix.
- **CORRECTION entries are annotations** — never mined, never create
  items — with ONE narrow exception for the log's own supersede
  mechanism: a correction that names a single subject in its head,
  explicitly supersedes a prior claim ("is superseded"), and asserts
  the corrected outcome as PAGE-CONFIRMED / EMAIL-VERIFIED binds that
  outcome for its subject (#198 Navan, whose only submission record
  is its superseding correction). A correction merely containing
  outcome words stays inert (#146).
- **SEGMENT STATE shorthand lines are hints only.** They never create
  items, identities, or outcomes; a source/gate hint attaches solely
  to an item a canonical entry already created. (email_sweep's
  segment fallbacks, which fill blank company/role for real items
  from segment lines, are unaffected.)
- **Summary heads never create dispositions** — Guardian tallies
  (bare or dash-prefixed; both split as their own entries), SEGMENT
  CLOSE/START, hourly sweeps, audits, FINAL ACCOUNTING. A Guardian
  tally line can never merge into the preceding entry and contaminate
  its segments.
- **First submission owns the window.** An item has exactly one
  submission for window attribution: the FIRST submitted-format entry
  in the log. Later submitted-format entries in newer sections never
  re-attribute it (the #198/#203/#226 double-count fix);
  EMAIL-VERIFIED catch-up entries tie to the item's submission
  window. "Counts toward this window" flags are scoped to the window
  of the entry that recorded them.

## The handoff contract — audited across every channel (Nov 5, 2026)

The user's rule: when Muse and the program talk, each side must be able
to prove it understood what the other handed off. Every write is
echoed as "understood" and read back as "landed_as"; only
"verified: true" counts. Audit of all program↔Muse channels:

| Channel | Understanding check |
|---|---|
| `spine.py gate` / `pay` | Verdict JSON echoes every input (counts, pct, figures, city). Already sound. |
| `spine.py next` (work order) | Carries item id, company, role, source, answers, resume path — the run's understanding is proven by the record it files for that item (checked below). |
| `spine.py record` | FIXED Nov 5: `record_with_check` echoes the outcome as understood (incl. fields as received), re-reads BOTH records — prose entry byte-for-byte in the log, latest event in the book — and exposes the why code the program DERIVED when the caller didn't supply one (no silent interpretation). The CLI prints a HANDOFF CHECK line whose instruction rides in the output. |
| `spine.py verify` / verify-queue | Program-internal (Gmail evidence → record); the drain's writes are the watcher's next state-check pass's subject — covered by the divergence net. |
| `spine.py status` / `state_check` / `shadow_pass.py` | Pure read-backs: both views' counts + classified divergences. This IS the standing cross-check. |
| `stall_check.py` / `bench_check.py` | Single-word verdicts with the numbers behind them, dual-channeled (JSON + exit code). Already sound. |
| `email_sweep.py` work list | Candidates pass through untouched (raw ids/subjects — nothing interpreted to misunderstand). |
| `email_sweep.py record` | FIXED Nov 5: result carries "understood" (judgment + the application the program resolved it to) and "landed" (id re-read from the scan state, entry re-read from the log, dismissal re-read for out-of-scope), "verified" only when all landed. The scan job's instructions tell the run what to do on verified: false. |
| `stock.py format` / `record` | Built with the contract from the start (see above). |

Tests: handoff groups in `tests/run_events_tests.py` (g) and
`tests/run_email_sweep_tests.py` (h), incl. mangled-write cases that
must come back unverified; `tests/run_stock_tests.py` (h).
- `events.py` + `events.jsonl` — the functional log: one compact dictionary
  per line, append-only, ONLY the most important info:
  `{"ts": "2026-11-04T14:15:00-06:00", "type": "submitted", "item": 164, "src": "JOBRIGHT", "win": "2026-11-04"}`.
  Those keys are the whole schema — `ts` (CT ISO), `type`, `item` (item #),
  `src` (LINKEDIN | JOBRIGHT, omitted when an event has no source, e.g.
  friction_set), `win` (the window date the event counts toward). No actor,
  no company, no payload, no prose; anything richer lives in the outreach
  log. The one optional key is `"why"`, a short code (pay / role / gate /
  dup / closed / card / code / id_doc / other) on skipped and staged events
  only. **`captcha` is its own event type, kept fully separate from taps**:
  a captcha is a bot-check the user solves by taking the browser, not an approval
  she grants, so a captcha blocker records a `captcha` event (never a
  staged event, never a `why`) and an AWAITING CAPTCHA TAKEOVER prose
  entry; `status` prints an "Awaiting captcha (n)" line distinct from
  "Staged for tap session (n)", and `state-check` compares the captcha
  lists too. Every `record` outcome writes BOTH the prose entry
  and its structured event in the same call. Consumers page through it with
  a watermark (`spine.py events --since <ISO ts>`). The live file starts
  empty; driver-mode runs fill it (it is never backfilled from prose — that
  would make the shadow comparison circular). Two record outcomes are
  prose-only because the design's event-type list has no type for them:
  `post_submit_pending` and `exception`. A `correction` event is a marker
  only — with no payload, the prose CORRECTION entry carries its substance.
- `state.py` also folds the event stream (`fold_events`);
  `spine.py state-check` prints prose vs events tallies side by side and a
  DIVERGENCE line for any item whose disposition differs.
- `spine.py` — CLI: `status`, `next`, `record`, `verify`, `clear-friction`,
  `events`, `state-check`. `--events PATH` overrides the events file (test
  pairs); for a non-live `--log`, the events file defaults to
  `<log-stem>.events.jsonl` beside that log, so tests can never write the
  live stream.
- `invitations.py` + `spine.py invite …` (the user, Nov 10, 2026 — "handle the
  tracking in the code"): connection invitations are tracked in the same
  event book under the invite_sent / invite_backfill / invite_counter
  vocabulary (no `item` key, so the application fold never sees them).
  `invite record` validates + appends sends (duplicate person+date
  refused), `invite counter` snapshots LinkedIn's Sent-People counter
  at a run's start/end, `invite status` computes sent-today /
  all-time / remaining quota (rules.yaml invitations.daily_target) and
  the counter discrepancy + cross-day drift as numbers, and
  `invite backfill` is the one-time reconciliation path that seeded
  the pre-code history (420 through Nov 10, 2026; see
  backfill_invitations.py and the shadow log). The program number is
  ground truth for invitations, as `spine.py status` is for
  applications.

## Usage (shadow mode)
```
python3 spine.py status [--date 2026-11-04] [--json]
python3 spine.py next [--date 2026-11-04]        # one work order JSON
python3 spine.py verify 164                      # Gmail check for an item
python3 spine.py --log <COPY> record result.json # NEVER the live log in shadow mode
python3 spine.py events [--since 2026-11-04T13:00:00-06:00]
python3 spine.py state-check [--date 2026-11-04] [--events <TEST events.jsonl>]
python3 spine.py invite status [--date 2026-11-10] [--json]  # invitation count of record
python3 spine.py invite record packet.json                   # {person, note, company?, role?} or {"invites": [...]}
python3 spine.py invite counter --phase start --value 1174   # Sent-People counter snapshot
python3 tests/run_tests.py                       # round-trip tests (copy only)
python3 tests/run_events_tests.py                # events-layer tests (copies only)
python3 tests/backfill_events.py                 # seed tests/events_test.jsonl from the live parse
```

## Hard constraints honored by this build
- The live outreach log is READ-ONLY for the program during shadow mode;
  tests write only to `tests/log_copy.md`.
- Append-only: the program never edits or deletes log lines; corrections are
  appended CORRECTION entries, as before.
- Counters are computed from the log, never asserted: any tally a run reports
  must come from `spine.py status`.
- Doorway guards read DATA, never prose (the user, Nov 5, 2026, late: "Use LLM
  for this type of questions. Only give code what it can easily digest:
  dictionary or other data structure."). The run (the LLM — it saw the
  screen) classifies each park into rules.yaml staging.blocker_kinds
  (approval_card / sign_in / resume_upload / identity_document /
  wu_input / code_step / other) and flags IP-blocked captchas with
  ip_blocked: true; record() checks only that data plus the item's
  route host/ATS. Guards: Workday route + sign_in kind → refused
  (follow workday_failure_path); sign_in kind without signin_attempted
  → refused; Gem route + resume_upload kind → refused (packet);
  captcha with ip_blocked and no manual_packet → refused; missing or
  unknown blocker_kind → refused; blank stage → refused. An earlier
  keyword-parsing version was ripped out the same night at the user's order.
  Trap tests prove prose-independence both ways (a sign_in kind with
  innocent prose is refused; an approval_card kind with credential-
  laden prose records). Stated limit: the classification and the
  attestations are the run's claims — the doorway forces them into the
  open; the nightly audit and watcher read what actually happened.


---

# The mail parts

Mail does four jobs in this system, all through Gmail. Three of them read LinkedIn notification email, and each scan recognizes its mail by one pinned test, written out in full under each job below. A sender address can be the whole test because of how your LinkedIn notifications are set up — that setup comes first.

## Your LinkedIn notification settings (set up for you at onboarding)

You do not set these up yourself. During onboarding, Muse sets your LinkedIn notifications to exactly this, and the mail scans below depend on it:

- **Exactly four categories on: InMail, Messages, Invitations to connect, and Job alerts.**
- On each of the four: **in-app notifications OFF**, **email ON**, and email frequency **Individual** (one email per event) where LinkedIn offers a frequency choice. The Job alerts page offers no frequency choice; email on is the whole setting there.
- **Every other notification category off completely** — in-app and email.

This is why the scans can be simple. With every other category off, each LinkedIn sender address carries one kind of mail and nothing else: invitations@linkedin.com sends you connection invitations only, so the invitation scan never has to test the subject line at all. If you ever change these settings, tell your Muse — the scans' tests assume them. The click-by-click reference for checking the settings yourself is [linkedin-notifications.md](linkedin-notifications.md).

## Watching for LinkedIn messages (every 15 minutes)

Job: `linkedin-message-email-watch`. It replies to new LinkedIn messages in near-real time, driven by the notification emails — it never browses LinkedIn looking for news.

**What it scans for** (Gmail, rolling window):

- **From:** messaging-digest-noreply@linkedin.com — the only sender LinkedIn uses for message notifications.
- **Subject:** contains "messaged you".
- **Window:** the past hour only, every 15 minutes.

When a notification matches, the job opens that one person's conversation — never any other — and replies under the standing reply rules. It never sweeps the whole inbox. Before acting, it claims the item in a shared ledger (`hidden_files/inbox-action-claims.md`) so the sweep below never answers the same person twice.

## The inbox sweep (four times a day, past 12 hours)

Jobs: `linkedin-inbox-replies` (8:30 AM), `linkedin-inbox-replies-midday` (12:30 PM), `linkedin-inbox-replies-afternoon` (4:30 PM), `linkedin-inbox-replies-evening` (8:30 PM) — one body, four runs a day. Each run is a backstop covering **only the past 12 hours**, so anything that arrives or is accepted during the day is picked up by the next run. It has three parts:

**1. Inbox messages the watch missed.** The program computes the scope in code: LinkedIn conversations whose latest incoming message arrived within the past 12 hours, minus every thread the watch or an earlier run already claimed in the shared ledger. The run works only those conversations, under the same reply rules as the watch.

**2. Connection invitations.**

- **From:** invitations@linkedin.com.
- **Subject:** no condition — **sender-only**, exactly like job alerts. Under the notification settings above, that address sends connection invitations and nothing else, so the sender alone identifies the mail. (An earlier filter also tested the subject; it missed a real invitation after LinkedIn changed its sender and subject, and was scrapped.)
- **Window:** the past 12 hours of Gmail.

Each invitation is accepted through the **Accept link inside the email** — never through LinkedIn's invitations page — and the acceptance is verified on the landing page before it is recorded. The code refuses anything stale, already processed, or matching the ad/marketing and group-invitation patterns.

**3. Job alert emails** (these feed the discovery lane).

- **From:** jobalerts-noreply@linkedin.com.
- **Subject:** no condition, ever — **sender-only**. Alert subjects are built from the first company on the list and arrive in many formats, so the subject is never consulted.
- **Window:** the past 12 hours of Gmail.

Each alert email's job list is vetted up to a hard limit of five pages, and every posting goes through the same screening as the other discovery sources before anything is stocked.

**4. The sweep itself — the catch-all, and forward movement.** The sweep is the fourth scan in its own right: four times a day it re-checks the LinkedIn inbox directly, so anything the notification emails missed still gets caught within the same 12-hour window. And when a message it picks up moves an application forward — an interview request, a scheduling ask, next steps, an offer — the sweep acts on it in the same run: it checks the company's recorded gate verdict, books the interview on Google Calendar once the company and role are known (checking Google Calendar and the paired phone's calendar for conflicts first, under the user's standing availability), creates the forward-movement to-do on Google Tasks, and reports the news to the user in chat. A researched briefing then lands one hour before the meeting.

## The application email scan (every 30 minutes)

Job: `job-application-email-followups`, with `email_sweep.py` doing the bookkeeping. Two kinds of mail matter:

- Confirmation emails from employers and application systems. These are the proof behind the verified count. Each submission is also checked at +10 minutes and again at +30 minutes by the verification queue, which the shadow pass drains.
- Follow-up emails about jobs already applied to: interview requests, assessments, next steps. Forward movement is reported to the user in chat and turned into a Google Tasks to-do with its deadline. Rejections are written to the log only. The scan never replies to this mail on its own.

## Sending mail

The system sends email rarely, and only inside threads the user is already part of. Every send needs the user's approval tap first. After a send, the message is read back and the To field is checked against the intended recipient. A reply always goes to the other party's message in the thread, never to the user's own sent message.

## Reports the user gets

- Morning report (9:23 AM, `linkedin-recommended-applications-morning-report`): the finished window's count, replies that moved forward, and anything waiting on the user.
- Forward-move to-do reminder (10:00 AM, `forward-todo-reminder-10am-ct`): the still-open interview and assessment to-dos.
- Weekly summary (Sunday evening, `linkedin-outreach-weekly-summary`): invitations sent that week, applications verified, inbox replies handled.

# How a day runs

Times are Central. The window for a day's **60-application target** (customizable) opens at **8:23 AM**.

### Job discovery

**8:23 AM:** the daily batch starts (`linkedin-recommended-applications-daily`). Workers search **Jobright** and **Indeed** for postings from the **last 24 hours**, run the **career-ops scan** over the public ATS boards on the same window, and take in the **LinkedIn job alert emails**.

### Screening

Screening runs **in code, before any posting is opened**: **blocked companies** (your block list, customizable) first, then companies **already applied to**, then the **company gate** on Revelio (company size and where its staff are based; LinkedIn company pages are the fallback when Revelio has no data). A posting that fails a screen is **dropped and logged with the reason**. A posting that passes is **vetted**: a read of the posting for **role fit** (technical work, not reporting work and not consulting), **work authorization**, and **pay against the user's floors** (customizable).

### Application

Prep: a **tailored resume** is built from the base resume and read back. An item is stocked to the **bench** only when its resume exists. A sweep every 30 minutes (`linkedin-bench-prep-sweep`) builds any resume the first pass missed.

Applying: up to **three workers** run in parallel. The **guardian** (`linkedin-batch-guardian`, every 30 minutes) keeps them alive and restarts them if one dies. Applications go in on the **employer's own site**. When a worker reaches a step only the user can do, the item waits for the **YOUR_AFTERNOON_TIME or YOUR_EVENING_TIME tap session or captcha session** (times customizable). Sites that block this browser entirely (Lever, Gem, Rippling, Paycom) become **manual packets** the user submits herself.

### Application follow-up

Verification: a submission counts toward the 60 when the employer's **confirmation email** arrives, or when the site showed a **successful application message** at submit time. If a submission cannot be proved, it is **not counted**. The confirmation email is checked at **+10 and +30 minutes** after each submission as a backstop. Submissions with neither proof sit in **limbo** and are **never re-applied**.

The **application email scan** (every 30 minutes) watches for what comes back. Interview requests and assessments become **to-dos**, interviews are **booked** on the user's calendar, and a researched **briefing lands one hour before** each one. **Rejections are logged and left alone.**

### LinkedIn networking

**10:23 AM:** networking (`linkedin-recruiter-outreach-weekly`). For the most recent applications, **contacto** finds the hiring contacts, the program checks them against the rules (**seniority above the user's**, real influence on the role, still at the company), and invitations go out on LinkedIn: up to **30 a day** (customizable), inside LinkedIn's **weekly cap of roughly 100**.

### LinkedIn inbox replies

The **message watch** (every 15 minutes) answers new LinkedIn messages under the user's standing **reply rules** (customizable), one person at a time. A **sweep four times a day** (8:30 AM, 12:30 PM, 4:30 PM, 8:30 PM) picks up anything the watch missed over the past 12 hours, plus **connection invitations** and **job alerts**.

**The notification setup this runs on** — Muse sets it during onboarding; the user never sets it by hand. Exactly four LinkedIn notification categories on: **InMail, Messages, Invitations to connect, and Job alerts**. On each one: **in-app notifications off, email on**, and email frequency **Individual** where LinkedIn offers a frequency choice (the Job alerts page offers none). **Every other category off completely.** Because nothing else is on, each LinkedIn sender address carries one kind of mail and nothing else — which is what makes the sender-only tests below safe.

**What each scan looks for in the email:**

- **Inbox messages** — the watch, every 15 minutes: **from messaging-digest-noreply@linkedin.com** AND **subject contains "messaged you"**, past hour only. The sweep additionally re-checks the LinkedIn inbox itself for conversations whose latest incoming message arrived within the past 12 hours and that no earlier run has claimed.
- **Connection invitations** — the sweep, four times a day: **from invitations@linkedin.com**, **no subject test** (sender-only — under the setup above, that address sends connection invitations and nothing else), past 12 hours. Each one is accepted through the Accept link inside the email, and the acceptance is verified before it is recorded.
- **Job alerts** — the sweep, four times a day: **from jobalerts-noreply@linkedin.com**, **no subject test** (sender-only — alert subjects are built from the first company on the list and arrive in many formats), past 12 hours. Each alert's job list is vetted up to five pages and feeds the discovery lane.
- **The sweep itself** — the fourth scan, four times a day: it re-checks the LinkedIn inbox directly and catches anything the notification emails missed in the past 12 hours. Anything that moves a job forward — an interview request or a scheduling ask — is acted on in the same run: the interview is booked on the user's Google Calendar (once the company and role are known), a to-do is created on Google Tasks, and the news is reported to the user, with a researched briefing one hour before the meeting.

The same three scans are described again, in the mail-flow order, under "The mail parts" above.

### Checks that run all day

The **shadow pass** (every 30 minutes) compares the written log with the program's own event record, flags any disagreement, checks for stalls, and drains the verification queue. The next morning at **8:47 AM**, the **nightly audit** (`linkedin-nightly-audit`) re-reads the whole previous day for gaps and rule breaks. A **watchdog** (`linkedin-watchdog`, 11:23 AM) checks the system itself once a day.

# Main functions and where they live

The code is organized in three folders under `program/`: the top level holds the entry points you run by name (`spine.py`, `supervisor.py`, `onboarding.py`, `install.py`); `engine/` holds the shared library modules; `checks/` holds the standalone scan scripts the scheduled jobs run; `tools/` holds one-off utilities.

- Job discovery: `engine/discovery.py`, driven by the worker template (`worker_template.md`). Sources: Jobright, Indeed, the career-ops scan, and LinkedIn alert emails.
- Screening and the company gate: `spine.py` (the gate and pay commands), `engine/gate_intake.py`, `engine/gate_fallback.py`, `engine/discovery.py`. Thresholds and rules: `config/rules.yaml`.
- Stocking the bench: `engine/stock.py`. An item enters the bench only with a verified tailored resume attached, and the resume is built before stocking, not after.
- Application: workers follow `worker_template.md` and take one work order at a time from `engine/pipeline.py` through `spine.py next`. Outcomes are recorded with `spine.py record`, which writes both the written log and the event book (`engine/events.py`, `events.jsonl`).
- Resumes: built per posting from the base resume. The prep sweep job keeps the bench supplied.
- Application follow-up: verification (`engine/verify.py`, plus the verification queue drained by the shadow pass, `checks/shadow_pass.py`); the application email scan (`checks/email_sweep.py`) watches for forward movement; interviews are booked on Google Calendar with a researched briefing one hour before, and forward moves become Google Tasks to-dos.
- LinkedIn networking: `engine/invitations.py` and `engine/outreach_targets.py`. Contact finding: `career-ops/modes/contacto.md`, with the house rules in `career-ops/modes/_custom.md`.
- LinkedIn inbox replies: `engine/inbox.py` and the mail jobs listed above.
- Supervision: `supervisor.py` (worker liveness and launches), `checks/stall_check.py`, `checks/bench_check.py`, `checks/browser_progress.py`, `checks/recovery_check.py`, and the guardian job.
- Standing answers: `config/answers.yaml`. In this repository the personal values in that file are placeholders. The live system keeps the real file on its own machine and never commits it.

# Information a new user has to provide

- A current resume (PDF). Every tailored resume is built from it, and nothing on an application comes from anywhere else.
- Standing facts: legal name (including in their native language, if forms ask), email, phone, home address, work authorization and citizenship status, education (schools, degrees, years, grade point averages), employers exactly as they appear on the resume, and notice period.
- Targets and floors: job titles, locations or remote, and the lowest pay accepted for onsite, hybrid, and remote roles.
- A block list of companies, plus any standing declines, such as a state where onsite roles are refused, or consulting work.
- Reply rules: when to accept a call, what to decline, what may be shared (phone number, work authorization), and what must come back to the user.
- A short "getting to know you" pass (optional, recommended): their superpower, what excites them, what drains them, deal-breakers, proudest achievement, and any published proof. This is context for Muse only — it never goes on an application form and never overrides the rules.
- Nothing to configure in LinkedIn by hand: during onboarding, Muse creates the job alerts and sets the LinkedIn notification settings (see "Your LinkedIn notification settings" above) from these answers.
- Accounts and subscriptions: LinkedIn with Premium Career, Jobright on a paid plan, Indeed, the free career-ops scanner, and Gmail with Google Calendar and Google Tasks connected.
- Two daily windows when the user can tap approvals and solve captchas. Here they are YOUR_AFTERNOON_TIME and YOUR_EVENING_TIME.

## Who does what: the control tower and the planes

The system is split between program code and Muse agents, and the split is a rule, not a habit. The picture the owner uses: **the code is the air traffic control tower, and each agent is an individual airplane.** The tower assigns every plane its mission, its route, and its landing slot, and the tower keeps the log of everything in the air. Each plane flies only its own assigned mission and radios back structured reports. A plane never reroutes itself, never decides another plane's mission, and never writes the tower's log.

The user is not a step in the chain either. The day runs on its own, and the user is called in from the side only at the moments a step genuinely needs a person: a tap approval, a captcha, a decision only they can make.

In practice:

- **Code owns all logging and logistics flow.** Counting, dedupe, screening order, gate and pay verdicts, pile and slot state, pacing and scheduling decisions. Every write to the outreach log and the program event book goes through code (`spine.py`, `stock.py`, and the program's own writers), never through an agent hand-writing an entry or an outcome.
- **Agents only browse, process text, and report back.** An agent handles the parts that need eyes (reading postings, emails, and pages; filling forms; writing notes), judges their content, and returns the result to code as a fixed JSON or dictionary packet. An agent never decides a verdict the code can decide, never records an outcome except through the code with a packet, and never lets its own prose summary create a state.
- **No hardcoded catch-words in code.** Code must not decide anything by matching keywords or catch phrases in free prose (log text, posting text, email text, a worker's summary). Decisions read structured data: fields, enums, counts. The only exceptions are patterns that are super obvious and fixed: closed vocabularies the program itself emits (its canonical outcome tokens and log markers), exact sender addresses, and exact subject markers the rules name word for word.

The nightly audit checks this boundary every day as its own track: it re-greps the code for prose-matching decision points and classifies each one as structured data, a fixed pattern, or a catch-word, and it checks the day's runs for outcomes no code writer produced and for instructions that asked an agent to decide something code owns. A catch-word decision that changed an outcome is a high-severity finding.
