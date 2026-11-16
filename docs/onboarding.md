# Onboarding

Setup is a conversation. Your Muse runs it with you, one step at a time, and writes your answers into the program as you go. It takes about 15 minutes. You can stop at any point and pick it up later; nothing you finished is asked again.

There are two ways to run it. They are the same flow, with the same words, in the same order:

- In chat: tell your Muse "run onboarding." It follows this page.
- In a terminal: run `python3 program/onboarding.py`. The script asks the same questions and records the same acknowledgments.

## How it goes

1. **Welcome.** Muse explains what the system does and what setup involves.
2. **Must-read items.** Eight short items, in four groups: costs, access, the vault, and captchas. Muse shows you one at a time. You answer **"I understand"** to each before it moves on. No bundling, no skipping. Each acknowledgment is recorded with its time in `program/state/onboarding.json`.
3. **The interview.** Eight short steps of questions (below). Muse writes each step into `program/config/answers.yaml` and `program/config/rules.yaml` as you finish it.
4. **Permissions.** Every account access the system may need, asked for up front (below). Each one can be set up now or skipped for later.
5. **FYI items.** Five shorter notes, each acknowledged the same way.
6. **Read-back.** Muse reads everything back to you, including which permissions you set up and which you skipped. Check it. Then Muse starts with a small first run so you can watch the screening decisions before the volume goes up.

## The must-read items

These are the deal terms. Muse reads them exactly as written in `program/onboarding.py`:

- **Costs (1 of 2).** LinkedIn Premium Career and a paid Jobright plan are required for the full workflow. LinkedIn and Jobright bill you directly. The program charges nothing and takes no payment details.
- **Costs (2 of 2).** Muse itself can cost money, depending on how hard you run this. A light setup can fit on the free tier. The full daily workflow fits within the $20/month tier. You should not need a tier above that.
- **Access (1 of 2).** Muse signs in as you: LinkedIn, Gmail, Google Calendar and Google Tasks, Jobright, and Indeed. While signed in it can do what those accounts can do, so treat its access the same way you treat your own.
- **Access (2 of 2).** Muse reads your email. Confirmations, recruiter replies, and LinkedIn notifications all arrive by mail, and the system cannot work without reading them. It sends mail only with your approval tap, and only under the reply rules you set during setup.
- **The vault (1 of 2).** Passwords are never typed into chat, and Muse never sees them. Logins are saved in a secure vault. At the moment of a sign-in, the browser fills the password in. If a site has no saved login, you get a secure entry card and type the password there yourself.
- **The vault (2 of 2).** Some sign-ins ask for a code sent to your email or phone, or a tap on your phone to approve. Those steps are always yours. Muse stops and waits. It does not guess codes and does not work around them.
- **Captchas (1 of 2).** Muse never solves a captcha and never clicks one. When a site shows one, Muse stops, holds the page open, and you solve it yourself. Captcha work collects into two short sessions a day, at times you pick during setup.
- **Captchas (2 of 2).** Muse never works around bot checks, login walls, IP blocks, or LinkedIn's limits. Some employer sites block automated browsers entirely (Lever, Gem, Rippling, and Paycom are the regulars). Those jobs come to you as manual packets: the apply link, your tailored resume, and the answers to fill in, ready to submit yourself in about two minutes.

## The interview

Eight steps. Muse asks, you answer, Muse writes it down before moving on.

1. **Your resume.** Send the PDF. Every tailored resume is built from it.
2. **The facts forms ask for.** Full legal name, your name in your native language if you have one, email, phone, LinkedIn profile link, home address.
3. **Work authorization.** Citizen, permanent resident, sponsorship, or something else, in the words a form should get.
4. **Education and employers.** Schools, degrees, years, grade point averages. Employers and titles exactly as they appear on your resume, most recent first.
5. **Standing choices.** Notice period. Equal opportunity answers. Whether Muse may invent a fun fact when a form asks for one. Whether it may agree to AI notetakers recording your interviews.
6. **What you're looking for.** Job titles to search, the places the location searches should cover, whether remote roles count, and your pay floors for onsite and for remote work. Plus any work you refuse under any title.
7. **Companies.** Your block list, if you have one. Then the company gate: Muse explains the default (companies under 100 people skipped; companies with more than half their staff in South Asia blocked) and that the second half of that rule is personal to the original user. You keep it, change the numbers, or turn it off.
8. **Replies and your daily windows.** When you're free for recruiter calls. Whether your phone number may be shared inside an active role conversation. The two times a day you'll tap approvals and solve captchas.

## Permissions: set up now, or skip for later

The system works across your accounts, so onboarding asks for all of the access it may ever need, up front, one item at a time. For each item you choose:

- **Set up now.** Muse does the connecting or signing in with you, right there in the onboarding session.
- **Skip now, I'll do this later when it comes up.** A complete answer. The skip is recorded, and Muse asks again the first time that access is actually needed. Nothing is set up in the background.

Every choice is recorded in `program/state/onboarding.json`. Any grant can be taken back later: tell Muse to disconnect it, disconnect the account yourself, or remove the saved login, and it stops being used.

For every item, Muse explains why it is needed before asking for anything. Passwords are never typed into the chat: you enter them on a secure vault form, and Muse never sees them.

The eight items:

1. **Google: Gmail, Calendar, and Tasks.** Why: Gmail is where confirmations, recruiter replies, and LinkedIn notification emails land; Calendar holds interviews, Tasks holds to-dos. Sending email always needs your approval tap.
2. **LinkedIn sign-in.** Why: invitations, invitation accepts, and inbox replies happen inside your LinkedIn account, so Muse signs in as you in its browser to send them and to verify profiles. You enter the login on the secure vault form; Muse never sees the password. Premium Career is what outreach runs on.
3. **LinkedIn notification emails.** Why: job alerts, message notifications, and invitation emails are how the system hears about new jobs and messages without browsing LinkedIn. A short settings pass on LinkedIn itself, following docs/linkedin-notifications.md, which Muse walks you through. No credential is involved.
4. **Jobright sign-in.** Why: Jobright is a discovery source and its searches run signed in, so Muse signs in as you to run the morning searches. You enter the login on the secure vault form; Muse never sees the password.
5. **Indeed sign-in.** Why: Indeed is the second discovery source, used for screening, and its searches run signed in. You enter the login on the secure vault form; Muse never sees the password.
6. **Employer portal accounts.** Why: applications are submitted on employer portals (Workday, Greenhouse, SuccessFactors, iCIMS, Lever, Ashby, Dayforce, UKG, and others), and submitting means signing in. Sign-in with Google where offered; Greenhouse needs only an email code; for the rest you set one portal password yourself on the secure vault form and Muse reuses it without ever seeing it. Lever, Gem, Rippling, and Paycom are never signed into at all; those come as manual packets.
7. **Reading sign-in codes from your email.** Why: portal sign-ins often email a one-time code, and the sign-in stalls without it. With this, Muse may fetch the first emailed code for a sign-in step from your Gmail and use it. If a code expires, is rejected, or a second one is needed, it stops and asks you.
8. **Asking for your taps.** Why: phone approvals, captchas, and email send approvals can only be done by you. With this, Muse brings them to you in your two daily sessions (see docs/tap-sessions/README.md and docs/captcha-sessions/README.md). Without it, Muse never asks, and those steps simply wait.

One part needs no access at all: the contacto contact-finding runs on public web search, and the company pages it checks are public.

## The FYI items

Shorter notes, acknowledged one at a time at the end: the daily count only includes applications proved by a confirmation email or a successful application message shown on screen, so a low day usually means your rules filtered the postings; LinkedIn caps invitations at roughly 100 a week and outreach pauses when it hits the cap; any rule can be changed later with one message; the system keeps a written log of everything it does; and a nightly audit re-reads each day for mistakes, with findings in your morning report.

## If you stop halfway

Everything finished is saved: acknowledgments in `program/state/onboarding.json`, answers in the config files after each step. Run onboarding again and it picks up where you stopped. Finished steps show your existing answers as defaults, so changing one answer later is quick.

## When you're done

`python3 program/onboarding.py status` reports anything still missing or unacknowledged, and says "Onboarding complete" when nothing is left. Do not start the daily workflow until it does.
