# Custom HTML UAT Feedback & Issue Generation Rules

This document establishes the rule for gathering User Acceptance Testing (UAT) feedback via interactive custom HTML forms and automatically creating actionable issues for agents to solve.

---

## 1. Requirement for Custom Interactive Feedback Forms
- Text chat alone is insufficient for gathering multidimensional UI feedback. Agents MUST generate and serve an interactive custom HTML page when conducting UAT with the user.
- **Form Generation**: Forms must be written to `scratch/<task_name>_uat_form.html` using the template provided by `collect-uat-feedback-and-create-issues`.

## 2. Specific Data Fields Collected
Custom HTML feedback forms MUST gather *specific, structured data*:
- **Component Identifier**: Ingestion Feed, Profile View, Collections, Virtual Sites, Admin Settings, or Extension.
- **UAT Overall Verdict**: PASS, PASS_WITH_ISSUES, FAIL.
- **Itemized Issue List**:
  - Issue Title
  - Category (Visual/Styling, Logic/Bug, Performance, Feature Request)
  - Severity (Blocker, Major, Minor, Polish)
  - Detailed Description & Steps to Reproduce
  - Expected vs Actual Behavior
  - Agent Action Required

## 3. Form Styling & Theme Standard
- Solarized Light (`#fdf6e3`) default theme, warm gray containers (`#eee8d5`), retro orange (`#cb4b16`) and turquoise (`#2aa198`) accents.
- Automatic Retro Dark theme support (`#002b36` background, `#073642` cards).
- Built-in JavaScript for dynamically adding/removing issue cards and exporting structured JSON (`scratch/<task_name>_uat_data.json`).

## 4. Issue Parsing & Agent Resolution Workflow
1. User interacts with form and saves `scratch/<task_name>_uat_data.json`.
2. Agent executes `uv run python .agent/skills/collect-uat-feedback-and-create-issues/scripts/parse_uat_issues.py --json-path scratch/<task_name>_uat_data.json`.
3. The script extracts each issue item, logs actionable task files, and formats an issue resolution plan.
4. Agent executes the required fixes, updates the VCS UAT report (`uat/reports/`), and re-verifies.
