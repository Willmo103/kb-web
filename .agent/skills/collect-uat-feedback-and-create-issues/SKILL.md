---
name: collect-uat-feedback-and-create-issues
description: Generates custom interactive HTML feedback forms for UAT, collects structured JSON data, and parses form responses into agent-actionable issue tasks.
---
# Collect UAT Feedback & Create Issues Skill

Use this skill whenever conducting User Acceptance Testing (UAT) on UI components or new feature implementations in `kb-web`.

---

## Workflow Steps

### Step 1: Render the Custom HTML Feedback Form
1. Copy `templates/uat_feedback_form.html` to `scratch/<task_name>_uat_form.html`.
2. Pre-fill any relevant task metadata inside the HTML.
3. Direct the user to open `scratch/<task_name>_uat_form.html` in their web browser.

### Step 2: User Form Submission
1. The user selects component ratings (Pass / Pass with Issues / Fail) and inputs specific itemized bug reports or feature requests.
2. The user clicks **"Save JSON"** (or **"Download JSON"**), saving the file to `scratch/<task_name>_uat_data.json`.

### Step 3: Parse Issues & Execute Agent Fixes
1. Run the issue parser script:
   ```bash
   uv run python .agent/skills/collect-uat-feedback-and-create-issues/scripts/parse_uat_issues.py --json-path scratch/<task_name>_uat_data.json
   ```
2. The script parses all submitted issue items and generates actionable issue tasks for the agent in `scratch/<task_name>_parsed_issues.md`.
3. Resolve each reported bug in code, run pytest, and generate the final VCS UAT report.
