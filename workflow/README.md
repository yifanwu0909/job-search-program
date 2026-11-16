# Workflow files

These are templates of the workflow files: a goal file and the scheduled jobs that run the workflow. They come from one working setup, generalized — **every name, time, title, location, and criterion in them is a sample value to replace with your own** when your Muse creates your jobs from them (INSTALL.md, step 6).

- `GOAL.md` is the goal file template: the standing rules for the whole job search, in the user's own terms.
- `jobs/` holds the scheduled jobs that run the workflow: the daily batch, the guardian, the outreach run, the inbox checks, the mail scan, the tap and captcha sessions, the audit, and the reports. Each file is one job's full instructions, with its schedule in the file header.
- The worker template the batch workers follow is one level up, at `../worker_template.example.md` (your install seeds your own `worker_template.md` from it).
- The contacto method used to find hiring contacts is under `../career-ops/`.
