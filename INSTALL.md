# Installing this program

**This page is for a Muse.** Your user has handed you this repo and asked you to set the system up for them. Follow the steps in order. Most steps are yours to run; a few need the user present (onboarding, sign-ins, approvals). Do not skip onboarding, and do not start the daily workflow until the checklist at the bottom is fully green.

## Before you start

Your user needs the accounts and subscriptions in the [README](README.md): a Muse plan, LinkedIn Premium Career, a paid Jobright plan, and accounts on LinkedIn, Jobright, and Indeed, plus Gmail with Google Calendar and Google Tasks. The program itself is Python 3.10+ with one dependency, PyYAML.

## Step 1: Place the repo

Clone or copy the repo to a stable home and keep it there; the scheduled jobs will point at this path. A good home is a goal workspace, for example `~/workspace/goals/<your-goal-slug>/`, with this repo's `program/` folder inside it. Everything below calls that folder **the program folder**. Runtime data (the event book, state files, the outreach log) lives alongside the code and is gitignored, so the repo stays clean as it runs.

## Step 2: Run the installer

```bash
cd <program folder>
python3 install.py
```

It checks the machine, creates the state directories, installs the bundled career-ops skill into `~/workspace/custom-skills/career-ops/` (that skill is how hiring contacts are found), and smoke-tests `spine.py status`. Fix any failed check and run it again. It never overwrites an existing `answers.yaml` and never edits config values.

## Step 3: Run the test suites

The program ships with 11 test suites in `program/tests/`. Run them **one at a time, in sequence, never in parallel** (they share fixtures; parallel runs produce false failures):

```bash
cd <program folder>
for t in tests/run_*_tests.py tests/run_tests.py; do python3 "$t" || echo "FAILED: $t"; done
```

Every suite must pass before you continue. A failure here means the install is wrong, not that the tests are optional.

## Step 4: Onboarding, with your user

This step is a conversation, and it is mandatory. Run it as written in [docs/onboarding.md](docs/onboarding.md): the welcome, the **permissions** first (LinkedIn and Google; each one set up now or skipped for later), then the user's **resume**, then a few **standing questions** (work authorization and the equal-opportunity answers), the user's **job search** (titles, locations, full time or part time, hybrid, remote, or in the office 5 days a week, plus anything else), and a prompt to install the **Jobright autofill plugin** in the user's browser. **LinkedIn alerts and notifications are not a user step**: onboarding records the setup as owed in `program/state/onboarding.json`, and you apply it yourself in Step 5. It records the account decisions in `program/state/onboarding.json` and the resume path and standing answers in `config/answers.yaml` (a real file install.py seeded from `config/answers.example.yaml`; it is gitignored and never committed).

Verify when you finish:

```bash
python3 onboarding.py status
```

It must say **"Onboarding complete."** If it lists anything missing or unacknowledged, go back and finish that part. The user's real config files (`config/answers.yaml`, `config/rules.yaml`, `worker_template.md`) are **gitignored and are never in this repo** — only the `*.example.*` templates are committed. Never commit a real config file. If the user wants version history for their config, keep it in a separate **private** repo of their own and link or copy the files in.

## Step 5: Connect the accounts

- Connect the **Gmail**, **Google Calendar**, and **Google Tasks** connectors in Muse. The system reads confirmations and recruiter mail from Gmail, books calls on Google Calendar only, and turns interview steps into Google Tasks.
- In the browser, sign your user in to **LinkedIn**, **Jobright**, and **Indeed**. When a site asks to save a login, save it to the secure vault. Passwords are never typed into chat, and you never see them.
- Apply the **LinkedIn setup recorded in onboarding** (`linkedin_setup` in `program/state/onboarding.json`), in the user's LinkedIn, yourself — do not ask the user to do it: job alerts saved for every title and location in their job search answers, the date posted filter set to past 24 hours, alert emails daily; email, inbox message, and invitation notifications on individual; every other notification off. See **docs/linkedin-notifications.md**. These emails are a hard prerequisite: without them there is no alert discovery, no message watch, and no invitation handling. Confirm the first alert email has landed in Gmail before the first full run, then mark the setup done in the state file.
- Work from the **permissions recorded in onboarding** (`program/state/onboarding.json`): set up every item the user granted (Google connectors, LinkedIn / Jobright / Indeed sign-ins saved in the vault). Leave skipped items alone; the workflow surfaces the need when it first comes up, and you ask then. Never set up a skipped item in the background.
- Confirm LinkedIn **Premium Career** is active on the account. Outreach does not work without it.

## Step 6: Create the scheduled jobs

The program has no scheduler of its own. Its whole daily rhythm lives in **18 scheduled jobs**, snapshotted in `workflow/jobs/`, one file per job. Each file's frontmatter carries the job's id, schedule, timezone, and owner; the body below the frontmatter is the job's instructions.

Create one job per file with your cron tools, with two adjustments:

1. **Path substitution.** The bodies reference the original install path, `~/workspace/goals/YOUR-GOAL`. Replace every occurrence with the path where you placed the program in Step 1 (the goal folder that contains `program/` and `hidden_files/`). Create a `hidden_files/` folder there if your placement does not have one; several jobs write the outreach log into it.
2. **Session times.** The tap and captcha session jobs (`linkedin-tap-session-*`, `linkedin-captcha-session-*`) run at the two daily windows your user picked (see docs/getting-started.md, "Your two daily windows"). Set their schedules to those times in the user's timezone.

When all 18 exist, list them back and check each one against its file: id, schedule, timezone, enabled. Two jobs to know by name: `linkedin-batch-guardian` (every 30 minutes; it launches and watches the application workers) and `linkedin-nightly-audit` (daily; it re-checks the whole previous day, now including the code/agent interaction track).

## Step 7: First run, small

Do not turn the full workflow loose on day one. Ask the program for one small discovery pass, watch it screen a handful of postings, and read the decisions with your user: which were blocked, which were duplicates, which failed the gate or the pay floor, and why. Then let one morning run end to end and read the morning report together. When your user is happy with the decisions, the system is live.

## Installed means

- [ ] `python3 install.py` passes every check.
- [ ] All 11 test suites pass, run sequentially.
- [ ] `python3 onboarding.py status` says "Onboarding complete."
- [ ] Gmail, Calendar, and Tasks are connected; LinkedIn, Jobright, and Indeed are signed in; Premium Career is active; job alert emails are set.
- [ ] All 18 scheduled jobs exist, with the install path substituted and the session times set to your user's.
- [ ] One small discovery pass and one full morning cycle have been reviewed with the user.

Anything unchecked, the install is not finished. Say which item is missing rather than working around it.
