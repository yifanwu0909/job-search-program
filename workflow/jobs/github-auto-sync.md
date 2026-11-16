---
id: github-auto-sync
title: GitHub auto-sync — pull author updates, then push program changes (every 4 hours)
enabled: true
owner: goal:YOUR-GOAL
mode: task
schedule:
  kind: interval
  timezone: America/Chicago
  every: 4h
timeout_secs: 600
delivery:
  - chat_id: YOUR-MAIN-CHAT-ID
---

# GitHub auto-sync (every 4 hours)

Two scripts, run in this order. Each does its whole job deterministically and prints ONE JSON line. Act only on the statuses.

## Step 1 — pull the author's updates

Run exactly: python3 ~/workspace/goals/YOUR-GOAL/program/tools/github_pull.py

It fetches the author's published updates (from the upstream remote when the install has one, otherwise origin) and merges them in WITHOUT overwriting or deleting anything the user changed locally: uncommitted edits are set aside and put back, a backup ref of the pre-pull state is kept, and anything that truly collides stops the pull instead of being forced.

- "up_to_date" or "updated": append one line to today's daily memory log (~/memory/YYYY-MM-DD.md) noting the result (and the commit count when updated). Continue to Step 2 silently — never message the user about a routine update.
- "conflict": message the user in the main chat, plainly: an update from the author touches the same lines as one of their own committed changes (name the files), so the pull stopped and nothing was changed; their version is intact, and a backup was kept. Do not try to resolve it yourself.
- "local_changes_preserved_in_stash": message the user, plainly: the author's update is in, but some of their uncommitted edits touched the same lines, so those edits were kept safe in a git stash instead of being overwritten (name the files); nothing was lost, and you can put the edits back with their go-ahead. Do not re-apply the stash yourself.
- "merge_in_progress": message the user: a merge was already half-done in the program repo, so the sync left everything alone.
- "error", or the script exits nonzero with no JSON: append the one-line error to today's daily memory log and continue to Step 2. Message the user only if the pull errors on two runs in a row.

## Step 2 — push the user's program changes

Run exactly: python3 ~/workspace/goals/YOUR-GOAL/program/tools/github_sync.py

- "clean" or "synced": append one line to today's daily memory log (~/memory/YYYY-MM-DD.md) noting the result (and the commit hash when synced). End silently — never message the user about a routine sync.
- "identifier_found": message the user in the main chat, plainly: the GitHub auto-sync stopped because personal information (name the patterns in plain words, and the files) appeared in changes waiting to be committed; nothing was committed or pushed, and the files were left as they are. Do not edit the files yourself.
- "behind_remote": message the user: the copy on GitHub has edits the local program does not (probably made on the website), so the sync stopped rather than merge on its own; nothing was pushed.
- "error" or "verify_failed", or the script exits nonzero with no JSON: message the user with the one-line error.

Never force-push, never clear skip-worktree, never commit or merge by hand from this job.
