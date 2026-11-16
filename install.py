#!/usr/bin/env python3
"""Installer for the job search program. Run by the user's Muse
(see INSTALL.md at the repo root), or by hand:

    python3 install.py [--home DIR] [--dry-run]

What it does, in order:
  1. Checks the machine: Python 3.10+, PyYAML importable.
  2. Creates the runtime state directories the program expects
     (program/state/, program/state/heartbeats/), plus the outreach
     log file config/rules.yaml points at (paths.outreach_log),
     empty if missing — the first status call reads it.
  3. Installs the career-ops skill files bundled in this repo
     (career-ops/) into <home>/workspace/custom-skills/career-ops/,
     unless they are already there. Existing files are never
     overwritten unless --force is passed.
  4. Smoke-tests the program: spine.py status must run and print.
  5. Prints the remaining steps (onboarding, accounts, scheduled
     jobs) — those need the user and their Muse, so the script
     does not attempt them.

It never touches the network, never edits config values, and never
overwrites an existing answers.yaml.
"""

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))  # the repo root IS the program folder
REPO = HERE


def check(label, ok, detail=""):
    print(f"  [{'ok' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=os.path.expanduser("~"),
                        help="home directory to install the skill into "
                             "(default: the real home)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen, change nothing")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing career-ops skill copy")
    args = parser.parse_args()
    dry = args.dry_run
    failures = 0

    print("Installing the job search program")
    print(f"  repo: {REPO}")
    print(f"  home: {args.home}" + ("  (dry run)" if dry else ""))

    print("\n1. Machine checks")
    failures += not check("Python 3.10+",
                          sys.version_info >= (3, 10),
                          f"found {sys.version.split()[0]}")
    try:
        import yaml  # noqa: F401
        failures += not check("PyYAML importable", True)
    except ImportError:
        failures += not check("PyYAML importable", False,
                              "install it: pip install pyyaml")

    print("\n2. Runtime state directories")
    for rel in ("state", os.path.join("state", "heartbeats")):
        path = os.path.join(HERE, rel)
        if os.path.isdir(path):
            check(f"program/{rel}/ exists", True)
        elif dry:
            check(f"program/{rel}/ would be created", True)
        else:
            os.makedirs(path, exist_ok=True)
            check(f"program/{rel}/ created", os.path.isdir(path))
    # The outreach log: the path comes from config (paths.outreach_log);
    # the file itself is runtime data, so creating it empty is setup,
    # not a config edit. An existing log is never touched.
    try:
        import yaml
        with open(os.path.join(HERE, "config", "rules.yaml"),
                  encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        log_path = os.path.expanduser(
            (cfg.get("paths") or {}).get("outreach_log", ""))
        if not log_path:
            failures += not check("outreach log ready", False,
                                  "paths.outreach_log is not set")
        elif os.path.exists(log_path):
            check("outreach log exists (left as is)", True)
        elif dry:
            check(f"outreach log would be created at {log_path}", True)
        else:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            open(log_path, "w", encoding="utf-8").close()
            check("outreach log created empty", os.path.exists(log_path))
    except Exception as exc:  # config unreadable: report, do not guess
        failures += not check("outreach log ready", False,
                              str(exc)[:120])

    print("\n3. career-ops skill (contacto people-finding)")
    src = os.path.join(REPO, "career-ops")
    dst = os.path.join(args.home, "workspace", "custom-skills", "career-ops")
    if not os.path.isdir(src):
        failures += not check("bundled career-ops/ present in repo", False)
    elif os.path.isdir(dst) and not args.force:
        check(f"already installed at {dst} (left as is; --force to "
              f"overwrite)", True)
    elif dry:
        check(f"would copy career-ops/ to {dst}", True)
    else:
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        check(f"copied to {dst}", os.path.isdir(dst))

    print("\n4. Smoke test")
    spine = os.path.join(HERE, "spine.py")
    if dry:
        check("would run spine.py status", os.path.exists(spine))
    else:
        proc = subprocess.run([sys.executable, spine, "status"],
                              capture_output=True, text=True, timeout=120)
        ok = proc.returncode == 0 and bool(proc.stdout.strip())
        failures += not check("spine.py status runs", ok,
                              "" if ok else (proc.stderr or proc.stdout)
                              .strip().splitlines()[-1][:120]
                              if (proc.stderr or proc.stdout).strip()
                              else "no output")

    print("\n5. What remains (needs the user and their Muse)")
    print("  a. Onboarding:  python3 onboarding.py   (must-reads first,")
    print("     then the interview — do not skip it)")
    print("  b. Accounts: connect Gmail + Google Calendar + Google Tasks;")
    print("     LinkedIn Premium Career; a paid Jobright plan; sign in to")
    print("     LinkedIn, Jobright, and Indeed in the browser.")
    print("  c. Scheduled jobs: create one job per file in workflow/jobs/,")
    print("     replacing the original program path with this repo's path")
    print("     (see INSTALL.md, step 6).")
    print("  d. First run: ask for a small test batch and read the morning")
    print("     report before letting the full daily workflow run.")

    if failures:
        print(f"\nInstall finished with {failures} failed check(s). "
              "Fix those and run me again.")
        return 1
    print("\nInstall checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
