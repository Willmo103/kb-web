---
name: generate-uat-testing-artifact
description: Generates standardized, VCS-trackable UAT test reports and logs in uat/ for commit tracking.
---
# Generate UAT Testing Artifact Skill

Use this skill to compile test logs, route coverage metrics, and manual UAT signoffs into git-tracked VCS testing artifacts under `uat/reports/` and `uat/logs/`.

---

## Workflow

1. Run the Python generator script:
   ```bash
   uv run python .agent/skills/generate-uat-testing-artifact/scripts/generate_uat_report.py --task <task_name> --tester "Agent & User"
   ```
2. The script will:
   - Run `pytest` and capture output logs in `uat/logs/test_log_<task_name>.log`.
   - Read test outputs, git status, and router coverage.
   - Render a formatted markdown UAT report at `uat/reports/uat_report_<task_name>.md`.
3. Add the generated UAT files to git tracking:
   ```bash
   git add uat/
   ```
