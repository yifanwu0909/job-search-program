# Goal: YOUR JOB SEARCH (template)

> This is a template goal file. Replace every YOUR_… value and every
> example rule with your own. The program's machine-checked rules live
> in `program/config/rules.yaml`; this file states the same search in
> your own words for the scheduled jobs to follow.

## Objective

Run a daily job search: find fresh postings for **Your Job Title** and
**Your Second Job Title**, screen them in code, apply on employer
sites, and send connection invitations to hiring contacts for the
roles just applied to.

- Daily target: **YOUR_DAILY_TARGET verified applications** across
  Jobright, Indeed, and LinkedIn job-alert emails.
- Daily outreach target: **YOUR_OUTREACH_TARGET verified invitations**.

## What counts

- Titles: your titles from `config/rules.yaml` (the search matrix and
  the LinkedIn alert definitions live there).
- Locations: your standing locations from `config/rules.yaml`.
- Role filter: your banned title words and track rules in
  `config/rules.yaml`. Only work that matches your definition of the
  role counts.
- Pay filter: your bars in `config/rules.yaml` — the universal bar for
  onsite/hybrid roles, the home-city base for nationally priced
  remote roles, a researched equivalent for city-priced remote roles.
- Company gate: every company is checked in code before a posting is
  opened (blocked list first, then duplication, then the workforce
  gate in `config/rules.yaml`).
- Full-time direct employment only, under your own standing rules.

## Applications

- Applications go in on the employer's own site or ATS, never through
  a job board.
- A submission is verified when the confirmation email arrives or the
  success screen is shown.
- Steps that need you (approval cards, CAPTCHAs, codes, documents)
  wait for your two daily sessions, at **YOUR_AFTERNOON_TIME** and
  **YOUR_EVENING_TIME** in your timezone: tap sessions for approvals,
  captcha sessions for bot checks. You solve every CAPTCHA yourself;
  Muse never clicks one.
- Sites that block the browser entirely become manual packets you
  submit yourself.

## Outreach

- Hiring contacts for the most recent applications come first.
- People are found with the career-ops contacto mode only, run
  exactly as its mode file prescribes; code decides who is invited.
- No peers: nobody at or below your own level.
- Notes are personalized, name the role and company, and stay within
  the length limit in `config/rules.yaml`.

## Replies

- Standing answers live in `config/rules.yaml` (for example: whether
  no relocation help is fine, whether an on-site interview is fine).
- Your availability: free for calls after **YOUR_CALL_TIME**.
- Meetings are booked on Google Calendar only, with a briefing one
  hour before.

## Records

- The outreach log is the running record; the program's event book is
  the count of record. Code decides and records; agents report back
  in fixed formats.
