# Onboarding

Onboarding asks for the account access the system needs, your resume, and a few standing questions, and it prompts you to install the Jobright plugin. It takes about 6 minutes. You can stop at any point and always come back and finish the onboarding later; nothing you finished is asked again.

## How it goes

1. **Welcome.** Muse explains what setup involves: permissions, your resume, a few standing questions, and the Jobright plugin.
2. **Permissions [~2 minutes].** The four accounts below, asked for first. Each one is set up now or skipped for later.
3. **Your resume [~1 minute].** Send the PDF. Every tailored resume is built from it. Its path is written into `program/config/answers.yaml`.
4. **A few standing questions [~2 minutes].** Work authorization, and the equal-opportunity answers. Written into `program/config/answers.yaml` the same way.
5. **The Jobright plugin [~1 minute].** Muse prompts you to install it in your own browser. Installed or skipped; the decision is recorded.

## Permissions: set up now, or skip for later [~2 minutes]

The system works across your accounts, so onboarding asks for the access it needs up front, one item at a time. For each item you choose:

- **Set up now.** Muse does the connecting or signing in with you, right there in the onboarding session.
- **Skip now, I'll do this later when it comes up.** A complete answer. The skip is recorded, and Muse asks again the first time that access is actually needed. Nothing is set up in the background.

Every choice is recorded in `program/state/onboarding.json`. Any grant can be taken back later: tell Muse to disconnect it, disconnect the account yourself, or remove the saved login, and it stops being used.

The four accounts:

1. **Google: Gmail, Calendar, and Tasks.** Why: Gmail is where confirmations, recruiter replies, and LinkedIn notification emails land; Calendar holds interviews, Tasks holds to-dos. Sending email always needs your approval tap.
2. **LinkedIn sign-in.** Why: invitations, invitation accepts, and inbox replies happen inside your LinkedIn account, so Muse signs in as you in its browser to send them and to verify profiles. You enter the login on the secure vault form; Muse never sees the password. Premium Career is what outreach runs on.
3. **Jobright sign-in.** Why: Jobright is a discovery source and its searches run signed in, so Muse signs in as you to run the morning searches. You enter the login on the secure vault form; Muse never sees the password.
4. **Indeed sign-in.** Why: Indeed is the second discovery source, used for screening, and its searches run signed in. You enter the login on the secure vault form; Muse never sees the password.

## A few standing questions [~2 minutes]

Two groups, both written into `program/config/answers.yaml`:

- **Work authorization.** US citizen, US permanent resident (green card, with the since date if you give it), sponsorship needed, or something else in the words a form should get.
- **Equal-opportunity answers.** Race, gender, disability status, and veteran status, as forms ask them. "Prefer not to say" is always an answer.

## The Jobright plugin [~1 minute]

Some applications come to you as manual packets, to submit yourself. Jobright's free autofill plugin fills those forms in for you. Onboarding prompts you to install it in your browser: search your browser's extension store for the Jobright AI autofill plugin. Type "done" when it is installed, or skip it and install it before your first manual application.

Anything you skipped, your Muse will ask you about when it comes up.
