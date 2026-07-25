# VCS Testing Artifact Rules

This document establishes the rule requiring agents to generate, track, and commit concrete testing artifacts into Version Control System (VCS) for all `kb-web` changes.

---

## 1. Requirement for VCS Artifact Generation
- Every UI feature, refactor, or bug fix MUST include generated testing artifacts committed directly into git under the `uat/` directory.
- **Directory Structure**:
  ```
  remotes/kb-web/uat/
  ├── reports/                # Markdown UAT test reports
  │   └── uat_report_<task>_<date>.md
  └── logs/                   # Raw route & template test output logs
      └── test_log_<task>_<date>.log
  ```

## 2. Contents of UAT Testing Artifacts
Every UAT report artifact (`uat/reports/*.md`) MUST contain:
1. **Target Feature / Component**: Clean description of modified UI templates, routers, or extension files.
2. **Environment Specs**: Python version, `uv` lock status, server host/port used during UAT.
3. **Automated Test Results**: Full output summary from `pytest` and `verify_ui_templates.py`.
4. **Interactive UAT Log**: Record of user feedback received via custom HTML feedback form and status of resolved issues.
5. **Sign-off Matrix**: Verification checklist signed off by the active agent prior to commit.

## 3. Git Tracking Policy
- Testing artifacts in `uat/` are **tracked in git** (VCS) and MUST be committed alongside code edits.
- Never place transient build artifacts or scratch data into `uat/`. Use `scratch/` for transient temporary files.
