# Onboarding

Welcome to your job search program. I'll set this up with you, step by step. It takes about 10 minutes in total. You answer questions, and I write everything down. Here's what we'll cover: permissions, your resume, a few standing questions, your job search, the Jobright plugin, and a few questions about you, so I know who I'm working for.

## The doctor check

Before anything is asked, Muse checks what is already in place — the same check `python3 onboarding.py status` prints. Only the steps still missing are walked. A step whose answers are already saved is skipped, never re-asked, and a field still holding the shipped example value is flagged. You can stop at any point and pick up where you left off.

## How it goes

1. **LinkedIn sign-in or register [~1 minute].** Why: invitations, accepts, and inbox replies all happen inside your LinkedIn account, so Muse signs in as you. To set up: your Muse prompts the secure vault card. Enter your LinkedIn login on it, or register first if you do not have an account. Muse never sees the password.
2. **Gmail: connect Google [~1 minute].** Why: confirmations and recruiter replies land in Gmail, interviews go on Calendar, to-dos go in Tasks. To set up: your Muse prompts the Google connect card. Connect your account on it, and give Muse access to Gmail, Calendar, and Tasks. Muse sends email only with your approval.
3. **Upload your resume [~1 minute].** Send the PDF. Every tailored resume is built from it.
4. **Standing questions [~2 minutes].** Work authorization, and the equal-opportunity answers: race, gender, disability status, veteran status. "Prefer not to say" is always an answer.
5. **Your job search [~2 minutes].** What job title are you looking for? Location? Full time or part time? Hybrid, remote, or in the office 5 days a week? Anything else Muse needs to know? You can always tell Muse more anytime in the future, and it will update your requirements.
6. **Jobright plugin [~1 minute].** Some applications come to you as manual packets, to submit yourself. Jobright's free autofill plugin fills those forms in for you. Install it in your browser: search your browser's extension store for the Jobright AI autofill plugin. Tell Muse when it's done and you'll wrap up the onboarding.
7. **Getting to know you [~2 minutes, recommended].** Asked one question at a time. The basics are in, and the system works much better when it knows you well — think of it as onboarding a recruiter. What makes you unique as a candidate, your superpower? What kind of work excites you, and what drains you? Any deal-breakers, in your own words? Your proudest professional achievement, the one you'd lead with? Any projects, articles, or case studies you've published? Blank is fine for any of these, and you can skip the step and tell Muse later instead. Your answers are kept as context for tailoring, connection notes, and fit judgment. They are never put on an application form, and the enforced filters stay in the rules file.

**LinkedIn alerts and notifications are not a step for you.** Once you give your job search, Muse sets them up itself in your LinkedIn, from your answers: job alerts saved for every title and location, date posted set to past 24 hours, alert emails daily; notifications set to exactly four categories on — InMail, Messages, Invitations to connect, and Job alerts, each with in-app notifications off and email on at individual frequency — and every other notification off completely. The program already reads those emails, the same way it does for its owner.

**Ready.** When the steps are done, Muse runs the check once more and confirms everything required is in place before the first run.

Muse can tell when a step is done: the vault card is finished, the connection shows connected, the resume arrives. The user never has to say "done." The plugin is the exception: the user tells Muse when it's installed.

Anything you skipped, your Muse will ask you about when it comes up. Anything already saved can be changed anytime by telling your Muse, or by editing `config/answers.yaml` directly.

**Your first run starts tomorrow.**
