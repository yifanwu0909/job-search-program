---
id: github-auto-sync
title: GitHub auto-sync — commit and push program changes (every 4 hours)
enabled: true
owner: goal:YOUR-GOAL
mode: task
schedule:
  kind: interval
  timezone: America/Chicago
  every: 4h
timeout_secs: 600
delivery:
  - chat_id: 48d41ee3-3ef0-4df2-b23b-dd30c3b929fa
---

# GitHub auto-sync (every 4 hours)

Run exactly: python3 ~/workspace/goals/YOUR-GOAL/program/tools/github_sync.py

The script does the whole sync deterministically and prints ONE JSON line. Act only on its status:

- "clean" or "synced": append one line to today's daily memory log (~/memory/YYYY-MM-DD.md) noting the result (and the commit hash when synced). End silently — never message the user about a routine sync.
- "identifier_found": message the user in the main chat, plainly: the GitHub auto-sync stopped because personal information (name the patterns in plain words, and the files) appeared in changes waiting to be committed; nothing was committed or pushed, and the files were left as they are. Do not edit the files yourself.
- "behind_remote": message the user: the copy on GitHub has edits the local program does not (probably made on the website), so the sync stopped rather than merge on its own; nothing was pushed.
- "error" or "verify_failed", or the script exits nonzero with no JSON: message the user with the one-line error.

Never force-push, never clear skip-worktree, never commit by hand from this job.
