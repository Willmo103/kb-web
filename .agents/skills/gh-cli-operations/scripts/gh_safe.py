#!/usr/bin/env python3
"""
gh_safe.py - Guarded GitHub CLI execution wrapper.
Provides structured logging to .artifacts/gh-actions.log, shell quoting safety,
and safety validation for pull requests and issues.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

ARTIFACTS_DIR = Path(".artifacts")
LOG_FILE = ARTIFACTS_DIR / "gh-actions.log"


def log_action(action: str, repo: str, title: str, result: str, url: str = "", ref: str = ""):
    """Appends a structured JSON log entry to .artifacts/gh-actions.log."""
    try:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "action": action,
            "repo": repo,
            "ref": ref,
            "title": title,
            "result": result,
            "url": url,
        }
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[WARN] Failed to write gh action log: {e}", file=sys.stderr)


def get_repo() -> str:
    """Extracts default github repo from git remote or defaults to Willmo103/kb-web."""
    try:
        res = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                             capture_output=True, text=True, check=True)
        repo = res.stdout.strip()
        if repo:
            return repo
    except Exception:
        pass
    return "Willmo103/kb-web"


def cmd_status(args):
    """Checks gh authentication status."""
    res = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    print(res.stdout or res.stderr)
    sys.exit(res.returncode)


def cmd_create_issue(args):
    """Creates an issue using a file body with duplicate check and logging."""
    repo = args.repo or get_repo()
    body_file = Path(args.body_file)
    if not body_file.is_file():
        print(f"[ERROR] Body file not found: {args.body_file}", file=sys.stderr)
        sys.exit(1)

    # Check for duplicate open issue title
    try:
        check = subprocess.run(
            ["gh", "issue", "list", "--repo", repo, "--state", "open", "--json", "title", "--jq", ".[].title"],
            capture_output=True, text=True, check=True
        )
        existing = [t.strip() for t in check.stdout.splitlines() if t.strip()]
        if args.title in existing:
            print(f"[SKIP] Issue with title already open: '{args.title}'")
            return
    except Exception as e:
        print(f"[WARN] Duplicate check failed: {e}", file=sys.stderr)

    cmd = ["gh", "issue", "create", "--repo", repo, "--title", args.title, "--body-file", str(body_file.resolve())]
    if args.label:
        for lbl in args.label:
            cmd.extend(["--label", lbl])

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        url = res.stdout.strip()
        print(f"[SUCCESS] Issue created: {url}")
        log_action("gh issue create", repo, args.title, "ok", url=url, ref=args.ref or "")
    else:
        err = res.stderr.strip() or res.stdout.strip()
        print(f"[ERROR] Failed to create issue: {err}", file=sys.stderr)
        log_action("gh issue create", repo, args.title, "error", url="", ref=args.ref or "")
        sys.exit(res.returncode)


def cmd_create_pr(args):
    """Creates a pull request with base guardrails and draft protection."""
    repo = args.repo or get_repo()
    body_file = Path(args.body_file)
    if not body_file.is_file():
        print(f"[ERROR] Body file not found: {args.body_file}", file=sys.stderr)
        sys.exit(1)

    cmd = ["gh", "pr", "create", "--repo", repo, "--title", args.title, "--base", args.base, "--body-file", str(body_file.resolve())]
    if args.draft:
        cmd.append("--draft")

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        url = res.stdout.strip()
        print(f"[SUCCESS] PR created: {url}")
        log_action("gh pr create", repo, args.title, "ok", url=url)
    else:
        err = res.stderr.strip() or res.stdout.strip()
        print(f"[ERROR] Failed to create PR: {err}", file=sys.stderr)
        log_action("gh pr create", repo, args.title, "error", url="")
        sys.exit(res.returncode)


def main():
    parser = argparse.ArgumentParser(description="Guarded GitHub CLI wrapper with structured logging.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # status
    p_status = subparsers.add_parser("status", help="Check gh auth status")
    p_status.set_defaults(func=cmd_status)

    # create-issue
    p_issue = subparsers.add_parser("create-issue", help="Create a GitHub issue safely")
    p_issue.add_argument("--title", required=True, help="Issue title")
    p_issue.add_argument("--body-file", required=True, help="Path to markdown body file")
    p_issue.add_argument("--label", action="append", help="Issue labels (repeatable)")
    p_issue.add_argument("--repo", help="Target repository (owner/repo)")
    p_issue.add_argument("--ref", help="Optional internal audit reference ID")
    p_issue.set_defaults(func=cmd_create_issue)

    # create-pr
    p_pr = subparsers.add_parser("create-pr", help="Create a GitHub PR safely")
    p_pr.add_argument("--title", required=True, help="PR title")
    p_pr.add_argument("--body-file", required=True, help="Path to markdown PR description file")
    p_pr.add_argument("--base", default="development", help="Base branch (default: development)")
    p_pr.add_argument("--draft", action="store_true", default=True, help="Create as draft (default: True)")
    p_pr.add_argument("--repo", help="Target repository (owner/repo)")
    p_pr.set_defaults(func=cmd_create_pr)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
