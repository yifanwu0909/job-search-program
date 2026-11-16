#!/usr/bin/env python3
"""github_pull.py — periodic safe pull of the author's published updates.

Run by the github-auto-sync scheduled job, BEFORE github_sync.py. Fully
deterministic: it makes no judgment calls — it updates, or it stops with
the user's work exactly as it was.

The author's updates arrive on a remote: "upstream" when the install has
one (a fork adds the author's repo as upstream), otherwise "origin" (a
direct clone of the author's repo). Only the main branch is pulled.

What it does, in order:
1. If a merge is already in progress, stops and reports
   {"status": "merge_in_progress"} — it never piles onto a half-done
   merge.
2. Fetches the update remote. If it has no commits the local repo lacks,
   reports {"status": "up_to_date"}.
3. Points a backup ref (refs/backup/pre-pull-<timestamp>) at the current
   HEAD. The pre-pull state is therefore always recoverable, and the ref
   is local only — never pushed.
4. If the working tree has uncommitted changes, stashes them (tracked
   files only; untracked and gitignored files — including the user's
   real config, which is gitignored — are never touched by anything in
   this script).
5. Merges the remote main (a fast-forward when the local repo has no
   commits of its own). A merge CONFLICT aborts the merge, restores the
   stash, and reports {"status": "conflict", "files": [...]} — the
   author's change is never forced over the user's own commits.
6. Restores the stash. If the user's uncommitted edits collide with the
   merged update, the edits stay preserved IN THE STASH (nothing is
   dropped or overwritten), the working tree is left clean at the merged
   state, and it reports {"status": "local_changes_preserved_in_stash"}.
7. Otherwise reports {"status": "updated", ...}.

Prints ONE JSON line on stdout. Exit codes: 0 = up to date or updated,
3 = stopped, needs the user; 1 = error.

Test hook: GITHUB_PULL_REPO overrides the repo path (the scratch repos
in tests/run_sync_tests.py use it). Real runs never set it.
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(os.environ.get("GITHUB_PULL_REPO")
            or Path(__file__).resolve().parent.parent)
ENV = dict(os.environ)
ENV["GIT_SSH_COMMAND"] = ("ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes "
                          "-o BatchMode=yes")


def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=REPO, env=ENV,
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return r


def update_remote() -> str:
    remotes = git("remote").stdout.split()
    return "upstream" if "upstream" in remotes else "origin"


def main():
    try:
        # 1. Never pile onto a half-done merge.
        if (REPO / ".git" / "MERGE_HEAD").exists():
            print(json.dumps({"status": "merge_in_progress"}))
            return 3
        remote = update_remote()
        # 2. Fetch; anything new?
        git("fetch", "--quiet", remote)
        behind = int(git("rev-list", "--count",
                         f"HEAD..{remote}/main").stdout.strip() or 0)
        if behind == 0:
            print(json.dumps({"status": "up_to_date", "remote": remote}))
            return 0
        old = git("rev-parse", "HEAD").stdout.strip()
        # 3. Backup ref at the pre-pull HEAD — always recoverable.
        ts = datetime.now(ZoneInfo("America/Chicago")).strftime(
            "%Y%m%d-%H%M%S")
        backup = f"refs/backup/pre-pull-{ts}"
        git("update-ref", backup, "HEAD")
        # 4. Stash uncommitted tracked changes, if any.
        dirty = bool(git("status", "--porcelain",
                         "--untracked-files=no").stdout.strip())
        stashed = False
        if dirty:
            git("stash", "push", "--quiet", "-m", f"github_pull {ts}")
            stashed = True
        # 5. Merge (fast-forward when possible).
        m = git("merge", "--no-edit", f"{remote}/main", check=False)
        if m.returncode != 0:
            files = git("diff", "--name-only",
                        "--diff-filter=U").stdout.split()
            git("merge", "--abort", check=False)
            restored = True
            if stashed:
                restored = git("stash", "pop", "--quiet",
                               check=False).returncode == 0
            print(json.dumps({"status": "conflict", "files": files,
                              "backup": backup,
                              "stash_restored": restored}))
            return 3
        # 6. Restore the user's uncommitted edits.
        if stashed:
            top = git("stash", "list", "--format=%gd %s",
                      check=False).stdout.splitlines()
            ours = bool(top) and f"github_pull {ts}" in top[0]
            a = git("stash", "apply", "--quiet", check=False)
            if a.returncode != 0:
                # The edits collide with the update. They stay preserved
                # in the stash; leave the tree clean at the merged state.
                files = git("diff", "--name-only",
                            "--diff-filter=U").stdout.split()
                git("restore", "--staged", "--worktree", ".",
                    check=False)
                print(json.dumps(
                    {"status": "local_changes_preserved_in_stash",
                     "files": files, "backup": backup}))
                return 3
            if ours:
                git("stash", "drop", "--quiet", "stash@{0}", check=False)
        # 7. Updated.
        new = git("rev-parse", "HEAD").stdout.strip()
        print(json.dumps({"status": "updated", "remote": remote,
                          "commits": behind, "from": old[:7],
                          "to": new[:7], "backup": backup}))
        return 0
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)[:300]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
