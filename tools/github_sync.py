#!/usr/bin/env python3
"""github_sync.py — periodic auto-commit and push of this repo.

Run by the github-auto-sync scheduled job. Fully deterministic: it makes no
judgment calls, it only syncs or stops.

What it does, in order:
1. Re-asserts skip-worktree on the three placeholder files
   (config/answers.yaml, config/rules.yaml, worker_template.md) so their
   live local content can never be staged.
2. Fetches origin. If the remote has commits the local repo does not (for
   example an edit made on github.com), it stops and reports
   {"status": "behind_remote"} — it never merges unattended.
3. If the working tree is clean, reports {"status": "clean"}.
4. Stages everything pending and scans the staged diff for personal
   identifiers. A hit unstages everything, commits nothing, and reports
   {"status": "identifier_found"} with the pattern names and file names
   (never the matched content).
5. Otherwise commits, pushes, and verifies the remote hash equals the
   local one. Reports {"status": "synced"}.

Prints ONE JSON line on stdout. Exit codes: 0 = clean or synced,
3 = stopped, needs the user; 1 = error.
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
PLACEHOLDER_FILES = ["config/answers.yaml", "config/rules.yaml", "worker_template.md"]
# The identifier patterns live OUTSIDE the repo (they are themselves personal
# data and must never be committed): one pattern per line in this file.
PATTERNS_FILE = (REPO.parent / "hidden_files" / "github-sync-patterns.txt")


def load_patterns():
    if not PATTERNS_FILE.exists():
        raise RuntimeError("identifier patterns file is missing — refusing to sync unscanned")
    patterns = [ln.strip() for ln in PATTERNS_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not patterns:
        raise RuntimeError("identifier patterns file is empty — refusing to sync unscanned")
    return patterns
ENV = dict(os.environ)
ENV["GIT_SSH_COMMAND"] = "ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes"


def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=REPO, env=ENV, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return r


def main():
    try:
        # 1. Placeholder protection, re-asserted every run.
        git("update-index", "--skip-worktree", *PLACEHOLDER_FILES)
        # 2. Fetch and refuse to merge unattended.
        git("fetch", "--quiet", "origin")
        behind = int(git("rev-list", "--count", "HEAD..origin/main").stdout.strip() or 0)
        if behind > 0:
            print(json.dumps({"status": "behind_remote", "behind": behind}))
            return 3
        # 3. Nothing to do?
        if not git("status", "--porcelain").stdout.strip():
            print(json.dumps({"status": "clean"}))
            return 0
        # 4. Stage and scan.
        git("add", "-A")
        files = [f for f in git("diff", "--cached", "--name-only").stdout.splitlines() if f]
        if not files:
            print(json.dumps({"status": "clean"}))
            return 0
        patterns = load_patterns()
        hits = {}
        for f in files:
            text = git("diff", "--cached", "--", f).stdout
            found = [p for p in patterns if p in text]
            if found:
                hits[f] = found
        if hits:
            git("reset", "--quiet")
            print(json.dumps({"status": "identifier_found",
                              "patterns": sorted({p for v in hits.values() for p in v}),
                              "files": sorted(hits)}))
            return 3
        # 5. Commit, push, verify.
        now = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M CT")
        subject = f"Auto-sync: {len(files)} file(s) changed ({now})"
        body = "\n".join(files[:15])
        git("commit", "--quiet", "-m", subject, "-m", body)
        git("push", "--quiet", "origin", "main")
        local = git("rev-parse", "HEAD").stdout.strip()
        remote = git("ls-remote", "origin", "main").stdout.split()[0]
        if local != remote:
            print(json.dumps({"status": "verify_failed", "local": local[:7], "remote": remote[:7]}))
            return 1
        print(json.dumps({"status": "synced", "commit": local[:7], "files": len(files)}))
        return 0
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)[:300]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
