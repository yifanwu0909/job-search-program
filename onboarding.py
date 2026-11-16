#!/usr/bin/env python3
"""Interactive onboarding for the job search program.

Onboarding asks for three things only: the account access the system
needs, your resume, and a few standing questions (work authorization
and the equal-opportunity answers forms ask for).

    python3 onboarding.py            # run onboarding (resumes where it left off)
    python3 onboarding.py welcome    # print the welcome message only
    python3 onboarding.py status     # what is still missing

The flow:
  1. A welcome message.
  2. Permissions: LinkedIn and Google, asked for first. Each one is
     set up
     now or skipped with "I'll do this later when it comes up"; a skip
     is a complete answer, and the access is asked for again when it
     first comes up. Choices are recorded with timestamps in
     state/onboarding.json, and any of them can be taken back later.
  3. Your resume (PDF). Every tailored resume is built from this file.
     Its path is written into config/answers.yaml (with a .bak of the
     previous file).
  4. A few standing questions: work authorization, and the
     equal-opportunity answers (race, gender, disability, veteran),
     written into config/answers.yaml the same way.
  5. Your job search: what titles, locations, full time or part
     time, and hybrid, remote, or in the office 5 days a week, plus
     anything else Muse needs to know. Written into
     config/answers.yaml under job_search.
  6. A prompt to install the Jobright autofill plugin in the user's
     own browser (it fills in the manual applications). Installed or
     skipped; the decision is recorded in state/onboarding.json.

Every prompt ends with two buttons, as typed options: "skip" (Skip
this now) and "break" (Take a break). Break stops the session and
saves everything; running onboarding again picks up where it stopped.
Nothing already decided or saved is asked again.

The same flow, run conversationally by the user's Muse instead of in
a terminal, is written out in docs/onboarding.md. The two stay in
step: same welcome, same accounts, same order.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ANSWERS = os.path.join(HERE, "config", "answers.yaml")
DEFAULT_RULES = os.path.join(HERE, "config", "rules.yaml")
DEFAULT_STATE = os.path.join(HERE, "state", "onboarding.json")

WELCOME = """Welcome to your job search program.

I'll set this up with you, step by step. It takes about 8 minutes
in total. You answer questions, and I write everything down.

Here's what we'll cover: permissions, your resume, a few standing
questions, your job search, and the Jobright plugin."""

# ---------------------------------------------------------------- permissions
# Asked for first, both of them, so there are fewer stops later. Every
# item can be skipped: a skip is recorded, and the access is asked for
# again when it first comes up. Any grant can be taken back later by
# telling Muse, disconnecting the account, or removing the saved login.
PERMISSIONS = [
    ("linkedin_signin", "LinkedIn sign-in or register",
     "Why: invitations, accepts, and inbox replies all happen inside "
     "your LinkedIn account, so Muse signs in as you.\n"
     "  To set up: your Muse prompts the secure vault card. Enter "
     "your LinkedIn login on it, or register first if you do not "
     "have an account. Muse never sees the password."),
    ("google_account", "Gmail: connect Google",
     "Why: confirmations and recruiter replies land in Gmail, "
     "interviews go on Calendar, to-dos go in Tasks.\n"
     "  To set up: your Muse prompts the Google connect card. "
     "Connect your account on it, and give Muse access to Gmail, "
     "Calendar, and Tasks. Muse sends email only with your "
     "approval."),
]

PLACEHOLDER_BITS = (
    "YOUR_", "you@example.com", "(000) 000-0000", "123 Main St",
    "Your City", "00000", "MM/DD/YYYY", "your-profile",
    "YOUR_FULL_NAME",
)


def is_placeholder(value):
    if value is None:
        return True
    if isinstance(value, str):
        if not value.strip():
            return True
        return any(bit in value for bit in PLACEHOLDER_BITS)
    return False


def load_yaml(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save_yaml(path, data, header):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            old = fh.read()
        with open(path + ".bak", "w", encoding="utf-8") as fh:
            fh.write(old)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False,
                       default_flow_style=False)


def load_state(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {"permissions": {}}


def save_state(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_path(data, *keys):
    node = data
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def set_path(data, value, *keys):
    node = data
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value


def current(data, *keys):
    """The existing value if it is real, else None (so placeholders are
    never offered as defaults)."""
    value = get_path(data, *keys)
    return None if is_placeholder(value) else value


# ------------------------------------------------------------ prompt helpers
class SkipPrompt(Exception):
    """The user pressed the 'Skip this now' button at a prompt."""


class BreakPrompt(Exception):
    """The user pressed the 'Take a break' button at a prompt."""


def ask(prompt, default=None, allow_blank=False, validate=None):
    """One question. Returns the answer string. Every prompt ends with
    the two buttons, as typed options: 'skip' (Skip this now) and
    'break' (Take a break). Ctrl-C / EOF propagates as a clean stop
    (the caller saves state first)."""
    while True:
        suffix = f" [{default}]" if default not in (None, "") else ""
        raw = input(f"{prompt}{suffix} [skip · break]: ").strip()
        if raw.lower() == "skip":
            raise SkipPrompt
        if raw.lower() == "break":
            raise BreakPrompt
        if raw == "":
            if default not in (None, ""):
                return default
            if allow_blank:
                return ""
            print("  I need an answer for this one.")
            continue
        if validate:
            problem = validate(raw)
            if problem:
                print(f"  {problem}")
                continue
        return raw


# -------------------------------------------------------------------- steps
def permissions_step(state, state_path):
    """Ask for every account access the system may need, up front.

    Each item is granted now or skipped ("I'll do this later when it
    comes up"). Both are complete answers and are recorded with a
    timestamp; an item already decided is never asked again. Returns
    (granted_titles, skipped_titles) covering every item.
    """
    perms = state.setdefault("permissions", {})
    if all(key in perms for key, _, _ in PERMISSIONS):
        pass  # all decided in an earlier run; fall through to summary
    else:
        print()
        print("=== Permissions [~2 minutes] ===")
    for key, title, text in PERMISSIONS:
        if key in perms:
            continue
        print()
        print(f"--- {title} ---")
        print(text)
        while True:
            raw = input("Press Enter when done "
                        "[skip · break]: ").strip().lower()
            if raw == "break":
                raise BreakPrompt
            if raw in ("", "done", "grant", "g", "now", "yes", "y"):
                perms[key] = {"decision": "granted", "at": now_iso()}
                break
            if raw in ("skip", "s", "later", "no", "n"):
                perms[key] = {"decision": "skipped", "at": now_iso()}
                break
            print('  Press Enter when it is set up, or type "skip".')
        save_state(state_path, state)
    granted = [t for k, t, _ in PERMISSIONS
               if perms.get(k, {}).get("decision") == "granted"]
    skipped = [t for k, t, _ in PERMISSIONS
               if perms.get(k, {}).get("decision") == "skipped"]
    return granted, skipped


def resume_step(answers):
    """Ask for the resume PDF and record its path in the answers."""
    print()
    print("=== Your resume [~1 minute] ===")
    resume = ask("Path to your current resume (PDF)",
                 default=current(answers, "applicant", "resume_file"))
    while not os.path.exists(resume):
        print("  I can't find that file. Check the path and try again.")
        resume = ask("Path to your current resume (PDF)")
    set_path(answers, resume, "applicant", "resume_file")
    print("  Got it. Every tailored resume is built from this file.")


def questions_step(answers):
    """Work authorization and the equal-opportunity answers."""
    print()
    print("=== A few standing questions [~2 minutes] ===")
    print("  Work authorization first.")
    print("  1) US citizen")
    print("  2) US permanent resident (green card)")
    print("  3) I need sponsorship")
    print("  4) Something else (you'll type it)")
    choice = ask("Which fits you? (1-4)", default="2")
    if choice == "1":
        status = "US citizen"
        set_path(answers, "citizen", "applications", "citizenship",
                 "united_states")
    elif choice == "3":
        status = ask("Your status, in the words a form should get")
        set_path(answers, True, "applications", "work_authorization",
                 "sponsorship_required")
    elif choice == "4":
        status = ask("Your status, in the words a form should get")
    else:
        since = ask("Green card holder since (MM/DD/YYYY)",
                    allow_blank=True)
        status = "US permanent resident (green card)"
        if since:
            status += f" since {since}"
        set_path(answers, status, "applications", "citizenship",
                 "united_states")
    if choice != "3":
        set_path(answers, False, "applications", "work_authorization",
                 "sponsorship_required")
    set_path(answers, status, "applications", "work_authorization",
             "status")
    set_path(answers, True, "applications", "work_authorization",
             "authorized_to_work_us")
    set_path(answers, "U.S. Green Card Holder" if choice == "2" else status,
             "applications", "resume_header", "status_line")
    print("  Now the equal-opportunity questions forms ask. "
          "'Prefer not to say' is always an answer.")
    set_path(answers, ask("Race, as forms ask it (or: prefer not to say)",
             default=current(answers, "applications", "eeo", "race")),
             "applications", "eeo", "race")
    set_path(answers, ask("Gender (or: prefer not to say)",
             default=current(answers, "applications", "eeo", "gender")),
             "applications", "eeo", "gender")
    set_path(answers, ask("Disability status (none, yes, or prefer not "
             "to say)", default=current(answers, "applications", "eeo",
             "disability") or "none"), "applications", "eeo", "disability")
    set_path(answers, ask("Veteran status (not a veteran, veteran, or "
             "prefer not to say)", default=current(answers, "applications",
             "eeo", "veteran") or "not a veteran"), "applications", "eeo",
             "veteran")


def search_step(answers):
    """What jobs to look for: titles, locations, type, workplace."""
    print()
    print("=== Your job search [~2 minutes] ===")
    titles = ask("What job title are you looking for? "
                 "(comma-separate if more than one)")
    set_path(answers, [t.strip() for t in titles.split(",") if t.strip()],
             "job_search", "titles")
    locations = ask("Location: where? (comma-separate if more than one)")
    set_path(answers,
             [t.strip() for t in locations.split(",") if t.strip()],
             "job_search", "locations")
    set_path(answers, ask("Full time or part time?", default="Full-time"),
             "job_search", "employment_type")
    set_path(answers, ask("Hybrid, remote, or in the office 5 days "
             "a week?"), "job_search", "workplace")
    notes = ask("Anything else I need to know?", allow_blank=True)
    if notes:
        set_path(answers, notes, "job_search", "notes")
    print("  You can always tell me more anytime in the future, and "
          "I'll update your requirements.")


def plugin_step(state, state_path):
    """Prompt the user to install the Jobright autofill plugin in
    their own browser. Installed or skipped; both are recorded."""
    if "plugin" in state:
        return state["plugin"].get("decision")
    print()
    print("=== The Jobright plugin [~1 minute] ===")
    print("  Some applications come to you as manual packets, to submit")
    print("  yourself. Jobright's free autofill plugin fills those forms")
    print("  in for you. Install it in your browser now: search your")
    print("  browser's extension store for the Jobright AI autofill")
    print("  plugin. Tell me when it's done and we'll wrap up the")
    print("  onboarding.")
    while True:
        raw = input('Type "done" when it is installed, or "skip" to do '
                    "it later [break = take a break]: ").strip().lower()
        if raw == "break":
            raise BreakPrompt
        if raw in ("done", "installed", "yes", "y"):
            state["plugin"] = {"decision": "installed", "at": now_iso()}
            break
        if raw in ("skip", "s", "later", "no", "n"):
            state["plugin"] = {"decision": "skipped", "at": now_iso()}
            break
        print('  I need one of the two: "done" or "skip".')
    save_state(state_path, state)
    return state["plugin"]["decision"]


# -------------------------------------------------------------------- status
def cmd_status(args):
    answers = load_yaml(args.answers)
    state = load_state(args.state)
    resume = get_path(answers, "applicant", "resume_file")
    resume_ok = not is_placeholder(resume)
    perms = state.get("permissions", {})
    undecided = [title for key, title, _ in PERMISSIONS
                 if key not in perms]
    q_missing = []
    if is_placeholder(get_path(answers, "applications",
                               "work_authorization", "status")):
        q_missing.append("work authorization")
    for key, label in (("race", "race"), ("gender", "gender"),
                       ("disability", "disability"),
                       ("veteran", "veteran status")):
        if is_placeholder(get_path(answers, "applications", "eeo", key)):
            q_missing.append(label)
    print(f"Answers file: {args.answers}")
    if resume_ok:
        print(f"Resume: {resume}")
    else:
        print("Still missing: your resume (PDF).")
    if undecided:
        print("No decision yet for:")
        for title in undecided:
            print(f"  - {title}")
    else:
        print("All account access is decided.")
    if q_missing:
        print("Still missing: " + ", ".join(q_missing) + ".")
    search_ok = bool(get_path(answers, "job_search", "titles")) and \
        bool(get_path(answers, "job_search", "locations")) and \
        not is_placeholder(get_path(answers, "job_search", "workplace"))
    if not search_ok:
        print("Still missing: your job search answers.")
    plugin_ok = "plugin" in state
    if not plugin_ok:
        print("No decision yet for: the Jobright plugin.")
    complete = resume_ok and not undecided and not q_missing and \
        search_ok and plugin_ok
    print("Onboarding complete." if complete else
          "Onboarding not finished yet. Run: python3 onboarding.py")
    return 0 if complete else 3


ANSWERS_HEADER = ("# Standing answer set for job applications, filled in "
                  "by onboarding.py.\n# Personal values: keep this file "
                  "local. Do not commit it with real values.\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "welcome", "status"])
    parser.add_argument("--answers", default=DEFAULT_ANSWERS)
    parser.add_argument("--rules", default=DEFAULT_RULES)
    parser.add_argument("--state", default=DEFAULT_STATE)
    args = parser.parse_args()

    if args.command == "welcome":
        print(WELCOME)
        return 0
    if args.command == "status":
        return cmd_status(args)

    state = load_state(args.state)
    answers = load_yaml(args.answers)
    try:
        if not state.get("welcomed"):
            print(WELCOME)
            state["welcomed"] = now_iso()
            save_state(args.state, state)
        perm_granted, perm_skipped = permissions_step(state, args.state)
        try:
            resume_step(answers)
            resume_done = True
        except SkipPrompt:
            resume_done = False
            print("  Resume skipped for now; I will ask again next time.")
        try:
            questions_step(answers)
            questions_done = True
        except SkipPrompt:
            questions_done = False
            print("  Standing questions skipped for now; I will ask "
                  "again next time.")
        try:
            search_step(answers)
            search_done = True
        except SkipPrompt:
            search_done = False
            print("  Job search skipped for now; I will ask again "
                  "next time.")
        plugin_decision = plugin_step(state, args.state)
        save_yaml(args.answers, answers, ANSWERS_HEADER)
    except BreakPrompt:
        save_yaml(args.answers, answers, ANSWERS_HEADER)
        save_state(args.state, state)
        print()
        print("Taking a break. Your progress is saved; run me again "
              "and I'll pick up where we left off.")
        return 0
    except (KeyboardInterrupt, EOFError):
        save_yaml(args.answers, answers, ANSWERS_HEADER)
        save_state(args.state, state)
        print()
        print("Stopped. Your progress is saved; run me again and I'll "
              "pick up where we left off.")
        return 0

    print()
    print("=== Done ===")
    if perm_granted:
        print("Set up: " + "; ".join(perm_granted))
    if perm_skipped:
        print("Skipped for later: " + "; ".join(perm_skipped)
              + " (your Muse will ask again when each one comes up, "
              "and any of them can be taken back at any time)")
    if resume_done:
        print(f"Resume: {get_path(answers, 'applicant', 'resume_file')}")
    else:
        print("Resume: still needed. Run onboarding again to add it.")
    if not questions_done:
        print("Standing questions: still needed. Run onboarding again "
              "to answer them.")
    if not search_done:
        print("Job search: still needed. Run onboarding again to "
              "answer it.")
    if plugin_decision == "skipped":
        print("Jobright plugin: skipped for now. Install it before "
              "your first manual application.")
    print("Next: your Muse connects the accounts you set up, then "
          "starts with a small first run so you can watch the "
          "screening decisions before the volume goes up.")
    print("Anything you skipped, your Muse will ask you about when "
          "it comes up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
