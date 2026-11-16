# Workflow files

These are copies of the live workflow files, taken on November 15, 2026. The live system keeps running from its own copies, so this folder is a record of how the workflow stood on that date, not the place to edit it.

- `GOAL.md` is the goal file: the standing rules for the whole job search, in the user's own terms.
- `jobs/` holds the scheduled jobs that run the workflow: the daily batch, the guardian, the outreach run, the inbox checks, the mail scan, the tap and captcha sessions, the audit, and the reports. Each file is one job's full instructions, with its schedule in the file header.
- The worker template the batch workers follow is one level up, at `../worker_template.md`.
- The contacto method used to find hiring contacts is under `../career-ops/`.
