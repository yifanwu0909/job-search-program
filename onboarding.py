#!/usr/bin/env python3
"""Interactive onboarding for the job search program.

Run it and it walks a new user through setup, step by step:

    python3 onboarding.py            # the full interview (resumes where it left off)
    python3 onboarding.py welcome    # print the welcome message only
    python3 onboarding.py status     # what is still missing / unacknowledged

The flow:
  1. A welcome message.
  2. MUST-READ items on costs, access, the credential vault, and captchas.
     Each one must be acknowledged by typing "I understand" before the
     interview moves on. Acknowledgments are recorded with timestamps in
     state/onboarding.json and are never asked twice.
  3. The interview: personal facts and basic job-hunting information,
     written into config/answers.yaml (with a .bak of the previous file),
     plus the pay floors, search titles, and company-gate numbers written
     into config/rules.yaml.
  4. Permissions: every account access the system may need, asked for up
     front. Each one can be granted now or skipped with "I'll do this
     later when it comes up"; a skip is a complete answer, and the access
     is asked for again when it first comes up. Choices are recorded in
     state/onboarding.json, and any of them can be taken back later.
  5. FYI items, each acknowledged the same way.
  6. A read-back summary of everything collected.

Quitting mid-way is fine: progress is saved after every step, and the
next run picks up where this one stopped. Existing real values are
offered as defaults, so re-running to change one answer is cheap.

The same flow, run conversationally by the user's Muse instead of in
a terminal, is written out in docs/onboarding.md. The two stay in step:
same welcome, same must-reads, same questions, same order.
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

I'll set this up with you, step by step. It takes about 15 minutes.
You answer questions, I write everything down, and at the end I read
it all back so you can check it.

Once we're done, I search for new postings every morning, screen them
against your rules, apply on the employer's own site with a resume
tailored from yours, and keep a record of everything. I also find the
hiring contacts for the roles you apply to, and I watch your inbox so
recruiter replies don't sit unanswered.

First, some must-read items. They cover what this costs, what access
I need, how your passwords are handled, and how captchas work. After
each one, type "I understand" to continue."""

# ---------------------------------------------------------------- must-reads
# The user, Nov 15, 2026: the must-reads are costs, access, the vault, and
# all the captcha things. One acknowledgment per item, never bundled.
MUST_READ = [
    ("Costs", "LinkedIn Premium Career and a paid Jobright plan are required "
              "for the full workflow. LinkedIn and Jobright bill you for "
              "those directly. This program charges nothing and takes no "
              "payment details."),
    ("Costs", "Muse itself can cost money, depending on how hard you run "
              "this. A light setup can fit on the free tier. The full daily "
              "workflow fits within the $20/month tier. You should not need "
              "a tier above that."),
    ("Access", "I sign in as you: LinkedIn, Gmail, Google Calendar and "
               "Google Tasks, Jobright, and Indeed. While signed in I can "
               "do what those accounts can do, so treat my access the same "
               "way you treat your own."),
    ("Access", "I read your email. Application confirmations, recruiter "
               "replies, and LinkedIn notifications all arrive by mail, and "
               "the system cannot work without reading them. I send mail "
               "only with your approval tap, and only under the reply "
               "rules you set during this setup."),
    ("The vault", "Passwords are never typed into chat, and I never see "
                  "them. Your logins are saved in a secure vault. At the "
                  "moment of a sign-in, the browser fills the password in "
                  "for me. If a site has no saved login, you get a secure "
                  "entry card and type the password there yourself."),
    ("The vault", "Some sign-ins ask for a code sent to your email or "
                  "phone, or a tap on your phone to approve. Those steps "
                  "are always yours. I stop and wait. I do not guess codes "
                  "and I do not work around them."),
    ("Captchas", "I never solve a captcha, and I never click one. When a "
                 "site shows a captcha, I stop, hold the page open, and "
                 "you solve it yourself. Captcha work collects into two "
                 "short sessions a day, at times you pick during this "
                 "setup."),
    ("Captchas", "I never work around bot checks, login walls, IP blocks, "
                 "or LinkedIn's limits. Some employer sites block automated "
                 "browsers entirely (Lever, Gem, Rippling, and Paycom are "
                 "the regulars). Those jobs come to you as manual packets: "
                 "the apply link, your tailored resume, and the answers to "
                 "fill in, ready to submit yourself in about two minutes."),
]

# ---------------------------------------------------------------------- FYIs
FYI = [
    "The daily count only includes applications proved by a confirmation "
    "email or a successful application message shown on screen. "
    "Some days the count is low because the new postings were duplicates or "
    "below your pay floor. That is your rules working, not a failure.",
    "LinkedIn caps connection invitations at roughly 100 a week. When the "
    "cap is hit, outreach pauses and resumes when the week resets. Nothing "
    "is lost; the queue waits.",
    "You can change any rule later with one message to your Muse. It "
    "updates the rule everywhere it is written and reads the change back "
    "to you.",
    "The system keeps a written log of everything it does. You can ask "
    "what happened on any day and get the record.",
    "A nightly audit re-reads the whole day for mistakes and broken rules. "
    "Anything it finds shows up in your morning report.",
]

# ---------------------------------------------------------------- permissions
# Asked for up front, all of them, so there are fewer stops later. Every
# item can be skipped: a skip is recorded, and the access is asked for
# again when it first comes up. Any grant can be taken back later by
# telling Muse, disconnecting the account, or removing the saved login.
PERMISSIONS_INTRO = """The system works across your accounts. Setting each of these up now
means fewer stops later. Every one can be skipped: skip it, and your
Muse will ask again when that access first comes up. You can also
take any of them back later: tell your Muse, disconnect the account,
or remove the saved login, and it stops being used.

One part needs no access at all: the contacto contact-finding runs on
public web search, and the company pages it checks are public."""

PERMISSIONS = [
    ("google_account", "Google: Gmail, Calendar, and Tasks",
     "Your Gmail is the system's inbox: application confirmations, "
     "recruiter replies, and LinkedIn notification emails all land "
     "there. Calendar holds your interviews, and Tasks holds your "
     "to-dos. Connecting Google lets your Muse read that mail, book "
     "interviews, and keep the to-do list. It sends email only with "
     "your approval tap."),
    ("linkedin_signin", "LinkedIn sign-in",
     "Your Muse signs in to LinkedIn as you in its browser: verifying "
     "profiles, sending the connection invitations, accepting "
     "invitations, and replying in your inbox under your reply rules. "
     "The login is saved in the secure vault. Premium Career is what "
     "the outreach runs on."),
    ("linkedin_notifications", "LinkedIn notification emails",
     "Job alerts, message notifications, and invitation emails are how "
     "the system hears about new jobs and new messages without "
     "browsing LinkedIn. Turning them on is a short settings pass on "
     "LinkedIn itself. The steps are written out in "
     "docs/linkedin-notifications.md."),
    ("jobright_signin", "Jobright sign-in",
     "Jobright is one of the discovery sources. Your Muse signs in as "
     "you to run the morning searches, and the login is saved in the "
     "secure vault. A paid plan is what covers this volume."),
    ("indeed_signin", "Indeed sign-in",
     "Indeed is the second discovery source, used for screening. Your "
     "Muse signs in as you to run its searches, and the login is "
     "saved in the secure vault."),
    ("portal_accounts", "Employer portal accounts",
     "Applications live on employer portals: Workday, Greenhouse, "
     "SuccessFactors, iCIMS, Lever, Ashby, Dayforce, UKG, and others. "
     "Where a portal offers sign-in with Google, your Muse uses "
     "that. Greenhouse needs no password at all, just an email code. "
     "For the rest, you set one portal password yourself in the secure "
     "vault and your Muse reuses it; it never sees the password. A "
     "few hosts (Lever, Gem, Rippling, Paycom) are never signed into "
     "at all: those applications come to you as manual packets."),
    ("email_codes", "Reading sign-in codes from your email",
     "Portal sign-ins often email you a one-time code. With this "
     "permission, your Muse may fetch the first code for a sign-in "
     "step from your Gmail and use it. If a code expires, is rejected, "
     "or a second code is needed, it stops and asks you. It never "
     "goes looking for codes for anything else."),
    ("tap_approvals", "Asking for your taps",
     "Some steps can only be done by you: approving a sign-in on your "
     "phone, solving a captcha, approving an email before it sends. "
     "With this permission, your Muse brings those to you in the two "
     "daily sessions you picked, plus the odd single tap in between. "
     "Without it, your Muse never asks, and those steps simply "
     "wait."),
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
    return {"acknowledged": {}, "steps_done": []}


def save_state(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------ prompt helpers
def ask(prompt, default=None, allow_blank=False, validate=None):
    """One question. Returns the answer string. Ctrl-C / EOF propagates
    as a clean stop (the caller saves state first)."""
    while True:
        suffix = f" [{default}]" if default not in (None, "") else ""
        raw = input(f"{prompt}{suffix}: ").strip()
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


def ask_yes_no(prompt, default=True):
    label = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{label}]: ").strip().lower()
        if raw == "":
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please answer y or n.")


def ask_int(prompt, default=None):
    def _check(raw):
        try:
            int(raw.replace(",", "").replace("$", ""))
        except ValueError:
            return "That needs to be a whole number."
        return None
    raw = ask(prompt, default=str(default) if default is not None else None,
              validate=_check)
    return int(raw.replace(",", "").replace("$", ""))


def valid_email(raw):
    return None if "@" in raw and "." in raw.split("@")[-1] else \
        "That does not look like an email address."


def acknowledge(kind, index, topic, text, state, state_path):
    """Show one must-read / FYI item and wait for 'I understand'."""
    key = f"{kind}:{index}"
    if key in state["acknowledged"]:
        return
    print()
    print(f"--- {kind} {index + 1}: {topic} ---")
    print(text)
    while True:
        raw = input('Type "I understand" to continue: ').strip().lower()
        if raw in ("i understand", "understand", "i do"):
            break
        print('  I need the words "I understand" for this one, so I know '
              "it landed.")
    state["acknowledged"][key] = now_iso()
    save_state(state_path, state)


def acknowledge_all(kind, items, state, state_path):
    for i, item in enumerate(items):
        if kind == "Must-read":
            topic, text = item
        else:
            topic, text = "Good to know", item
        acknowledge(kind, i, topic, text, state, state_path)


def permissions_step(state, state_path):
    """Ask for every access the system may need, up front.

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
        print("=== Permissions: set up access now, or skip for later ===")
        print(PERMISSIONS_INTRO)
    for key, title, text in PERMISSIONS:
        if key in perms:
            continue
        print()
        print(f"--- {title} ---")
        print(text)
        while True:
            raw = input('Type "grant" to set this up now, or "skip" to '
                        "do it later when it comes up: ").strip().lower()
            if raw in ("grant", "g", "now", "yes", "y"):
                perms[key] = {"decision": "granted", "at": now_iso()}
                break
            if raw in ("skip", "s", "later", "no", "n"):
                perms[key] = {"decision": "skipped", "at": now_iso()}
                break
            print('  I need one of the two: "grant" or "skip". Skipping '
                  "is fine; it only means I ask again when it comes up.")
        save_state(state_path, state)
    granted = [t for k, t, _ in PERMISSIONS
               if perms.get(k, {}).get("decision") == "granted"]
    skipped = [t for k, t, _ in PERMISSIONS
               if perms.get(k, {}).get("decision") == "skipped"]
    return granted, skipped


# ------------------------------------------------------------------- the ask
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


def interview(answers, rules):
    """Steps 1-8. Mutates the answers and rules dicts. Returns a list of
    human-readable notes about rules-side choices for the read-back."""
    notes = []

    print()
    print("=== Step 1 of 8: your resume ===")
    resume = ask("Path to your current resume (PDF)",
                 default=current(answers, "applicant", "resume_file"))
    while not os.path.exists(resume):
        print("  I can't find that file. Check the path and try again.")
        resume = ask("Path to your current resume (PDF)")
    set_path(answers, resume, "applicant", "resume_file")
    print("  Got it. Every tailored resume is built from this file, and")
    print("  nothing goes on an application that is not on it or below.")

    print()
    print("=== Step 2 of 8: the facts forms ask for ===")
    set_path(answers, ask("Your full legal name",
             default=current(answers, "applicant", "full_name")),
             "applicant", "full_name")
    native = ask("Your legal name in your native language, if you have one "
                 "(blank if not)",
                 default=current(answers, "applicant", "legal_name_native"),
                 allow_blank=True)
    if native:
        set_path(answers, native, "applicant", "legal_name_native")
    name = get_path(answers, "applicant", "full_name").split()
    set_path(answers, name[0], "applicant", "first_name")
    set_path(answers, name[-1], "applicant", "last_name")
    set_path(answers, ask("Email", default=current(answers, "applicant",
             "email"), validate=valid_email), "applicant", "email")
    set_path(answers, ask("Phone", default=current(answers, "applicant",
             "phone")), "applicant", "phone")
    set_path(answers, ask("LinkedIn profile URL",
             default=current(answers, "applicant", "linkedin_url")),
             "applicant", "linkedin_url")
    street = ask("Home street address",
                 default=current(answers, "applicant", "address", "street"))
    city = ask("City", default=current(answers, "applicant", "address",
               "city"))
    region = ask("State", default=current(answers, "applicant", "address",
                 "state"))
    zipcode = ask("ZIP code", default=current(answers, "applicant",
                  "address", "zip"))
    set_path(answers, street, "applicant", "address", "street")
    set_path(answers, city, "applicant", "address", "city")
    set_path(answers, region, "applicant", "address", "state")
    set_path(answers, zipcode, "applicant", "address", "zip")
    set_path(answers, "US", "applicant", "address", "country")
    set_path(answers, f"{street}, {city}, {region} {zipcode}",
             "applicant", "address", "line")
    contact_line = (f"{city}, {region} | "
                    f"{get_path(answers, 'applicant', 'phone')} | "
                    f"{get_path(answers, 'applicant', 'email')} | LinkedIn")
    set_path(answers, contact_line, "applications", "resume_header",
             "contact_line")

    print()
    print("=== Step 3 of 8: work authorization ===")
    print("  1) US citizen")
    print("  2) US permanent resident (green card)")
    print("  3) I need sponsorship")
    print("  4) Something else (you'll type it)")
    choice = ask("Which fits you? (1-4)", default="2")
    if choice == "1":
        status, china = "US citizen", None
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
                    default=None, allow_blank=True)
        status = "US permanent resident (green card)"
        if since:
            status += f" since {since}"
        set_path(answers, status, "applications", "citizenship",
                 "united_states")
    if choice != "3":
        set_path(answers, False, "applications", "work_authorization",
                 "sponsorship_required")
    set_path(answers, status, "applications", "work_authorization", "status")
    set_path(answers, True, "applications", "work_authorization",
             "authorized_to_work_us")
    set_path(answers, "U.S. Green Card Holder" if choice == "2" else status,
             "applications", "resume_header", "status_line")

    print()
    print("=== Step 4 of 8: education and employers ===")
    print("  Education first. One school at a time; blank school name "
          "when done.")
    education = []
    while True:
        school = ask("School", allow_blank=True)
        if not school:
            break
        education.append({
            "school": school,
            "degree": ask("Degree"),
            "start": ask("Start year"),
            "end": ask("End year"),
            "gpa": ask("GPA (blank if you don't want it used)",
                       allow_blank=True) or None,
        })
    if education:
        set_path(answers, education, "applications", "education")
    print("  Now employers, most recent first, exactly as on your resume.")
    print("  Blank employer name when done.")
    history = []
    while True:
        employer = ask("Employer", allow_blank=True)
        if not employer:
            break
        history.append({
            "employer": employer,
            "title": ask("Job title"),
            "location": ask("Location (blank if your resume shows none)",
                            allow_blank=True) or None,
            "start": ask("Start (YYYY-MM)"),
            "end": ask("End (YYYY-MM)"),
        })
    if history:
        set_path(answers, history, "applications", "employer_history")
        set_path(answers, history[0]["employer"], "applications",
                 "current_employer")
        set_path(answers, history[0]["title"], "applications",
                 "current_title")

    print()
    print("=== Step 5 of 8: standing choices ===")
    weeks = ask_int("Notice period, in weeks", default=2)
    set_path(answers, weeks, "applications", "notice_period", "weeks")
    set_path(answers, round(weeks / 4.33, 1), "applications",
             "notice_period", "months")
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
    fun = ask_yes_no("When a form asks for a fun fact, may I invent a "
                     "harmless one instead of stopping to ask?", default=True)
    set_path(answers,
             "invent a plausible, lively one; never ask (personal-color "
             "items only — professional facts are never invented)"
             if fun else "leave blank; never invent anything",
             "applications", "fun_facts")
    consent = ask_yes_no("May I agree when a company asks to record "
                         "interviews with an AI notetaker?", default=True)
    set_path(answers, "yes" if consent else "no", "applications",
             "ai_notetaker_interview_consent")

    print()
    print("=== Step 6 of 8: what you're looking for ===")
    titles_raw = ask("Job titles to search for, separated by commas",
                     default=None)
    titles = [t.strip() for t in titles_raw.split(",") if t.strip()]
    scope = ask("Which places should the location searches cover? "
                "(for example: California/Washington, or Texas)",
                default="California/Washington")
    remote = ask_yes_no("Count fully remote roles?", default=True)
    discovery = rules.setdefault("discovery", {})
    discovery["linkedin_search_titles"] = titles
    for source, remote_row in (
            ("jobright_searches", {"remote_via": "work_model_filter"}),
            ("indeed_searches", {"location_via": "location_field"})):
        rows = [{"title": t, "location_scope": scope,
                 "location_via": "location_field"} for t in titles]
        if remote:
            rows += [{"title": t, "location_scope": "Remote",
                      **remote_row} for t in titles]
        discovery[source] = rows
    notes.append(f"Search titles: {', '.join(titles)} "
                 f"(locations: {scope}; remote: "
                 f"{'yes' if remote else 'no'})")
    bar = ask_int("Lowest pay you'll accept for an onsite or hybrid role "
                  "($ per year)", default=200000)
    rules.setdefault("pay_filter", {})["universal_bar"] = bar
    remote_bar = ask_int("Lowest pay for a nationally priced remote role "
                         "($ per year)", default=120000)
    rules["pay_filter"]["remote_national_bar"] = remote_bar
    notes.append(f"Pay floors: ${bar:,} onsite/hybrid, "
                 f"${remote_bar:,} remote")
    refused = ask("Work you refuse under any title (for example: "
                  "consulting, reporting-only). Blank for none.",
                  allow_blank=True)
    if refused:
        notes.append(f"Refused work: {refused}")

    print()
    print("=== Step 7 of 8: companies ===")
    blocked_raw = ask("Companies you will never apply to, separated by "
                      "commas. Blank for none.", allow_blank=True)
    if blocked_raw:
        blocked = [c.strip() for c in blocked_raw.split(",") if c.strip()]
        notes.append(f"Block list you named: {', '.join(blocked)} "
                     "(your Muse merges these into the program's "
                     "blocked-companies list before the first run)")
    print()
    print("  The company gate: before applying, each company is checked")
    print("  on Revelio (free). The setup in this repo skips companies")
    print("  under 100 people, and blocks companies with more than half")
    print("  their staff in South Asia. That second rule is personal to")
    print("  the original user. Keep it, change it, or turn it off.")
    gate_choice = ask("Gate: (1) keep as is, (2) change the numbers, "
                      "(3) turn it off", default="1")
    gate = rules.setdefault("gate", {})
    if gate_choice == "2":
        gate["hard_pass_total_below"] = ask_int(
            "Skip companies under how many people?", default=100)
        gate["india_block_pct"] = ask_int(
            "Block when the South Asia share is above what percent?",
            default=50)
        notes.append(f"Company gate: under "
                     f"{gate['hard_pass_total_below']} people skipped, "
                     f"over {gate['india_block_pct']}% South Asia blocked")
    elif gate_choice == "3":
        gate["hard_pass_total_below"] = 0
        gate["india_block_pct"] = 100
        notes.append("Company gate: off (size floor 0, share cap 100%)")
    else:
        notes.append("Company gate: kept (under 100 people skipped, "
                     "over 50% South Asia blocked)")

    print()
    print("=== Step 8 of 8: replies and your daily windows ===")
    free_after = ask("You're free for recruiter calls after what time? "
                     "(for example: 2:00 PM CT)", default="2:00 PM CT")
    set_path(answers, f"free for calls after {free_after} (standing)",
             "replies_only", "availability")
    share_phone = ask_yes_no("May I share your phone number inside an "
                             "active conversation about a specific role, "
                             "when the other side needs it to book a "
                             "call? (It is never put in cold messages.)",
                             default=True)
    notes.append(f"Phone sharing in active role conversations: "
                 f"{'yes' if share_phone else 'no'}")
    tap1 = ask("First daily tap/captcha session time", default="1:30 PM")
    tap2 = ask("Second daily tap/captcha session time", default="7:30 PM")
    notes.append(f"Tap and captcha sessions: {tap1} and {tap2} "
                 "(your Muse sets the session schedules to these times)")
    return notes


# -------------------------------------------------------------------- status
REQUIRED_FIELDS = [
    (("applicant", "full_name"), "your full legal name"),
    (("applicant", "email"), "your email"),
    (("applicant", "phone"), "your phone"),
    (("applicant", "linkedin_url"), "your LinkedIn profile URL"),
    (("applicant", "address", "street"), "your street address"),
    (("applicant", "address", "city"), "your city"),
    (("applicant", "address", "zip"), "your ZIP code"),
    (("applications", "work_authorization", "status"),
     "your work authorization status"),
    (("applications", "education"), "your education"),
    (("applications", "employer_history"), "your employer history"),
]


def missing_fields(answers):
    missing = []
    for path, label in REQUIRED_FIELDS:
        value = get_path(answers, *path)
        if value is None or (isinstance(value, (str, list)) and
                             (not value or is_placeholder(str(value)))):
            missing.append(label)
    return missing


def cmd_status(args):
    answers = load_yaml(args.answers)
    state = load_state(args.state)
    missing = missing_fields(answers)
    unacked = [f"Must-read {i + 1} ({t})" for i, (t, _) in
               enumerate(MUST_READ)
               if f"Must-read:{i}" not in state["acknowledged"]]
    unacked += [f"FYI {i + 1}" for i in range(len(FYI))
                if f"FYI:{i}" not in state["acknowledged"]]
    perms = state.get("permissions", {})
    unacked += [f"Permission decision: {title}" for key, title, _ in
                PERMISSIONS if key not in perms]
    print(f"Answers file: {args.answers}")
    if missing:
        print("Still missing or placeholder:")
        for item in missing:
            print(f"  - {item}")
    else:
        print("All required answers are filled in.")
    if unacked:
        print("Not yet acknowledged:")
        for item in unacked:
            print(f"  - {item}")
    else:
        print("All must-read and FYI items are acknowledged.")
    complete = not missing and not unacked
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
    rules = load_yaml(args.rules)
    try:
        if not state.get("welcomed"):
            print(WELCOME)
            state["welcomed"] = now_iso()
            save_state(args.state, state)
        acknowledge_all("Must-read", MUST_READ, state, args.state)
        notes = interview(answers, rules)
        perm_granted, perm_skipped = permissions_step(state, args.state)
        save_yaml(args.answers, answers, ANSWERS_HEADER)
        with open(args.rules, encoding="utf-8") as fh:
            rules_text = fh.read()
        # rules.yaml carries long explanatory comments the program's
        # other tools rely on; only the three numeric leaves the
        # interview touches are rewritten, in place, by line edit.
        import re
        def set_leaf(text, key, value):
            pattern = rf"^(\s*{key}:\s*)\S+"
            new_text, n = re.subn(pattern, rf"\g<1>{value}", text,
                                  count=1, flags=re.M)
            return new_text if n else text
        rules_text = set_leaf(rules_text, "universal_bar",
                              rules["pay_filter"]["universal_bar"])
        rules_text = set_leaf(rules_text, "remote_national_bar",
                              rules["pay_filter"]["remote_national_bar"])
        rules_text = set_leaf(rules_text, "india_block_pct",
                              rules["gate"]["india_block_pct"])
        rules_text = set_leaf(rules_text, "hard_pass_total_below",
                              rules["gate"]["hard_pass_total_below"])
        # Search blocks: replace each block's rows with the interview's
        # titles and scope, in the file's own one-row-per-line format.
        def set_block(text, key, row_lines):
            pattern = rf"^(  {key}:\n)(?:    - .*\n)+"
            block = rf"\g<1>" + "".join(f"    - {line}\n"
                                         for line in row_lines)
            new_text, n = re.subn(pattern, block, text, count=1,
                                  flags=re.M)
            return new_text if n else text
        disc = rules.get("discovery", {})
        if disc.get("linkedin_search_titles"):
            rules_text = set_block(
                rules_text, "linkedin_search_titles",
                [f'"{t}"' for t in disc["linkedin_search_titles"]])
        for key in ("jobright_searches", "indeed_searches"):
            if disc.get(key):
                lines = []
                for row in disc[key]:
                    bits = ", ".join(
                        f'{k}: "{v}"' if k in ("title", "location_scope")
                        else f"{k}: {v}" for k, v in row.items())
                    lines.append("{" + bits + "}")
                rules_text = set_block(rules_text, key, lines)
        with open(args.rules, "w", encoding="utf-8") as fh:
            fh.write(rules_text)
        acknowledge_all("FYI", FYI, state, args.state)
    except (KeyboardInterrupt, EOFError):
        # Answers live in the in-memory dict until the interview ends;
        # save whatever was collected so a stopped run loses nothing.
        save_yaml(args.answers, answers, ANSWERS_HEADER)
        save_state(args.state, state)
        print()
        print("Stopped. Your progress is saved; run me again and I'll "
              "pick up where we left off.")
        return 0

    print()
    print("=== Read-back: what I have for you ===")
    print(f"Name: {get_path(answers, 'applicant', 'full_name')}")
    print(f"Email: {get_path(answers, 'applicant', 'email')}")
    print(f"Phone: {get_path(answers, 'applicant', 'phone')}")
    print(f"Address: {get_path(answers, 'applicant', 'address', 'line')}")
    print(f"Work authorization: "
          f"{get_path(answers, 'applications', 'work_authorization', 'status')}")
    for note in notes:
        print(f"- {note}")
    if perm_granted:
        print("Permissions set up now: " + "; ".join(perm_granted))
    if perm_skipped:
        print("Permissions skipped for later: " + "; ".join(perm_skipped)
              + " (your Muse will ask again when each one comes up, "
              "and any of them can be taken back at any time)")
    print()
    print("Saved to config/answers.yaml (previous version kept as "
          "answers.yaml.bak) and config/rules.yaml.")
    print("Next: connect your accounts (LinkedIn with Premium Career, "
          "Jobright, Indeed, Gmail with Calendar and Tasks), then ask "
          "your Muse for a small first run so you can watch the "
          "screening decisions before the volume goes up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
