#!/usr/bin/env python3
"""Tests for tools/github_pull.py — the safe auto-pull of author updates.

Builds scratch git repos (an "author" repo and a "user" clone) in a temp
dir and checks the pull's promises:
  a) a clean user fast-forwards to the author's new commit;
  b) the user's uncommitted edits to OTHER files survive an update;
  c) uncommitted edits that collide with the update are preserved in the
     stash, never overwritten (status local_changes_preserved_in_stash);
  d) a committed local change that conflicts with the author's change
     stops the pull (status conflict) with the tree untouched;
  e) no author changes -> up_to_date;
  f) every non-trivial run leaves a refs/backup/pre-pull-* ref.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PULL = HERE.parent / "tools" / "github_pull.py"
FAILURES = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f" :: {detail}"))
    if not cond:
        FAILURES.append(name)


def git(cwd, *args, check_rc=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                       text=True)
    if check_rc and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} in {cwd}: {r.stderr}")
    return r


def write(repo, name, text):
    (Path(repo) / name).write_text(text, encoding="utf-8")


def commit_all(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", msg)


def run_pull(user_repo):
    env = dict(os.environ)
    env["GITHUB_PULL_REPO"] = str(user_repo)
    r = subprocess.run([sys.executable, str(PULL)], env=env,
                       capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])


def make_world(tmp):
    """author.git (bare) <- author work clone; user clones the bare repo."""
    bare = Path(tmp) / "author.git"
    git(tmp, "init", "--bare", "--quiet", "-b", "main", str(bare))
    author = Path(tmp) / "author"
    git(tmp, "clone", "--quiet", str(bare), str(author))
    for repo in (author,):
        git(repo, "config", "user.email", "author@example.com")
        git(repo, "config", "user.name", "Author")
    write(author, "doc.md", "line one\nline two\nline three\n")
    write(author, "other.md", "other file\n")
    commit_all(author, "initial")
    git(author, "push", "--quiet", "origin", "main")
    user = Path(tmp) / "user"
    git(tmp, "clone", "--quiet", str(bare), str(user))
    git(user, "config", "user.email", "user@example.com")
    git(user, "config", "user.name", "User")
    return bare, author, user


def author_edits(author, name, text, msg="author update"):
    write(author, name, text)
    commit_all(author, msg)
    git(author, "push", "--quiet", "origin", "main")


def main():
    # (a) clean fast-forward + (f) backup ref
    with tempfile.TemporaryDirectory() as tmp:
        _, author, user = make_world(tmp)
        author_edits(author, "doc.md", "line one\nline two CHANGED\nline three\n")
        rc, out = run_pull(user)
        check("a1 clean pull updates", rc == 0 and out["status"] == "updated",
              str(out))
        check("a2 content is the author's",
              (user / "doc.md").read_text() == "line one\nline two CHANGED\nline three\n")
        refs = git(user, "for-each-ref", "--format=%(refname)",
                   "refs/backup/").stdout
        check("f1 backup ref left behind", "refs/backup/pre-pull-" in refs,
              refs)
    # (b) uncommitted edits elsewhere survive
    with tempfile.TemporaryDirectory() as tmp:
        _, author, user = make_world(tmp)
        write(user, "other.md", "other file\nUSER EDIT\n")
        author_edits(author, "doc.md", "line one\nline two CHANGED\nline three\n")
        rc, out = run_pull(user)
        check("b1 update succeeds with dirty tree",
              rc == 0 and out["status"] == "updated", str(out))
        check("b2 user edit preserved",
              (user / "other.md").read_text() == "other file\nUSER EDIT\n")
        check("b3 stash emptied after restore",
              git(user, "stash", "list").stdout.strip() == "")
    # (c) colliding uncommitted edits preserved in the stash
    with tempfile.TemporaryDirectory() as tmp:
        _, author, user = make_world(tmp)
        write(user, "doc.md", "line one\nline two USER\nline three\n")
        author_edits(author, "doc.md", "line one\nline two AUTHOR\nline three\n")
        rc, out = run_pull(user)
        check("c1 colliding edits -> preserved_in_stash",
              rc == 3 and out["status"] == "local_changes_preserved_in_stash",
              str(out))
        check("c2 tree holds the author's merged version",
              (user / "doc.md").read_text() == "line one\nline two AUTHOR\nline three\n")
        stash = git(user, "stash", "list").stdout
        check("c3 the user's edit is in the stash", "github_pull" in stash,
              stash)
        shown = git(user, "stash", "show", "-p", "stash@{0}").stdout
        check("c4 stash content is the user's edit", "line two USER" in shown)
    # (d) committed conflict stops, tree untouched
    with tempfile.TemporaryDirectory() as tmp:
        _, author, user = make_world(tmp)
        write(user, "doc.md", "line one\nline two USER\nline three\n")
        commit_all(user, "user's own commit")
        head_before = git(user, "rev-parse", "HEAD").stdout.strip()
        author_edits(author, "doc.md", "line one\nline two AUTHOR\nline three\n")
        rc, out = run_pull(user)
        check("d1 committed conflict -> conflict status",
              rc == 3 and out["status"] == "conflict", str(out))
        check("d2 HEAD unchanged",
              git(user, "rev-parse", "HEAD").stdout.strip() == head_before)
        check("d3 tree clean, user's version intact",
              git(user, "status", "--porcelain").stdout.strip() == ""
              and "line two USER" in (user / "doc.md").read_text())
    # (e) nothing new
    with tempfile.TemporaryDirectory() as tmp:
        _, author, user = make_world(tmp)
        rc, out = run_pull(user)
        check("e1 no changes -> up_to_date",
              rc == 0 and out["status"] == "up_to_date", str(out))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL SYNC TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
