# Customization

The examples in this repo are one sample setup. This page lists the fields you can change, what each one does, and where it lives. Most live in two files: `program/config/rules.yaml` (the machine-checked rules) and `program/config/answers.yaml` (the standing answers used on forms). The rest live in the goal file (`workflow/GOAL.md`) and in the scheduled jobs (`workflow/jobs/`).

Ask your Muse to change any of them. It will update the setting everywhere it is written down and read it back to confirm.

## How to change

Just tell Muse to change it. Say what you want different, in plain words. Muse updates the setting everywhere it is written and reads the change back to you. You never edit these files by hand.

## Who you are (answers.yaml)

- Legal name, including your name in your native language if forms ask for it.
- Email, phone, home address, LinkedIn profile link.
- Work authorization and citizenship status, in the exact words forms should get.
- Education: schools, degrees, years, grade point averages.
- Employer history, exactly as it appears on your resume.
- Notice period, and any timing notes (for example, extra time needed before starting a job in another state).
- Equal opportunity answers: race, gender, disability, veteran status.
- Whether the system may invent a fun fact when a form asks for one. This user said yes, for personal-color questions only. Professional facts are never invented, and that part is not a setting.
- Whether the system may agree to AI notetakers recording your interviews. This user said yes.

## What you are looking for (rules.yaml)

- Job titles searched. Example: Your Job Title and Your Second Job Title on Jobright and Indeed and in the career-ops scan's portal filters, plus your saved titles on the LinkedIn alert lane.
- Locations: which states or cities, and whether remote roles count.
- Pay floors. Here: $YOUR_BAR attainable pay for any onsite or hybrid role, $YOUR_BASE for nationally priced remote roles, and a researched city equivalent for remote roles priced by city. A posting below the floor is skipped and logged.
- Daily targets. Here: 60 verified applications a day across all sources, and 30 connection invitations a day.
- Role filter. Here: titles containing Staff, Lead, Principal, or Consultant are out, and a data scientist job only counts if the work is technical. Reporting and dashboard work under a data science title is out. So is consulting work: roles that bill your hours to a client.
- Standing declines. Example: onsite or hybrid roles in your excluded locations are declined on sight, whatever the fit.

## The company gate (rules.yaml)

Before applying, each company is checked. This is the most personal part of the setup, so read it before keeping any of it.

- Source order: Revelio first (free, no account). If the company is not on Revelio, the check falls back to the company's LinkedIn page.
- Minimum size: companies under 100 people are skipped. Skipping for size does not block the company; a bigger posting from the same company later can still pass.
- Staff location cap: if more than half the company's staff are based in South Asia, the company is skipped and blocked. The 50 percent line and the region are this user's choice.
- If neither source gives usable numbers, the posting is dropped for that day. It is not blocked, and it can come back if the data improves.

Change the numbers, change the region, change the source, or switch the gate off. Your Muse can also add a gate of your own, for example a minimum company age or a funding requirement, as long as a source exists for the data.

## Your block list (rules.yaml and the outreach log)

- Companies the system must never apply to. Here the list has 57 names: large outsourcing firms, plus companies this user ruled out one by one.
- A blocked company is declined on sight, in applications and in LinkedIn replies, without re-checking.
- Companies get added to the list when the user says so, or when the gate rule above blocks them.

## Outreach (rules.yaml)

- Invitation target: 30 verified invitations a day, inside LinkedIn's weekly cap of roughly 100. When the cap is hit, sending pauses. It never works around the cap.
- Who gets invited: people with influence on the role at companies just applied to. Recruiters first, then the likely hiring manager, then other senior people on the team.
- The no-peers rule: nobody at or below the user's own level gets an invitation. Here that means nobody at Your Current Level or below.
- Where names come from: the career-ops contacto method only (public web searches). LinkedIn is never searched for people. If contacto finds nobody for a role, the role is skipped, not filled from another source.
- The note: short (300 characters at most), names the role and the company, written for that person. Notes are drafted by Muse and checked against the humanizer rules before sending.

## Replies (rules.yaml and GOAL.md)

- Work authorization is stated early in a recruiter conversation, without waiting to be asked.
- No relocation help offered by a company is fine. An on-site interview is fine. Both are answered yes when asked. The system does not bring up relocation on its own.
- No salary numbers in messages. The pay rules apply to postings, not to chat.
- The phone number is shared only inside an active conversation about a specific role, when the other side asks or needs it to book a call. Every share is logged.
- Calls are booked only once the company and the role are known. Both calendars are checked, and the booking goes on Google Calendar.
- Conversations older than a month, and threads where the user wrote last, are left alone.

## The schedule (workflow/jobs/)

- When the day opens (here 8:23 AM) and when the morning report lands (9:23 AM).
- The outreach run time (10:23 AM).
- Tap sessions and captcha sessions: twice a day, here YOUR_AFTERNOON_TIME and YOUR_EVENING_TIME, in the user's timezone.
- The inbox watch interval (every 15 minutes), the mail scan interval (every 30 minutes), and the daily inbox check (8:30 AM).
- The nightly audit (8:47 AM) and the weekly summary (Sunday evening).

## Verification (rules.yaml)

- Each submission is checked for its confirmation email at +10 minutes and again at +30 minutes. A successful application message shown at submit time also proves a submission on its own; the email checks are the backstop.
- A submission with no confirmation after the second check sits in limbo. It is never re-applied. If you want different timing, or a third check, say so.
