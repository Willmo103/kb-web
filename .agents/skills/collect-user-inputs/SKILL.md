---
name: collect-user-inputs
description: Generates custom HTML feedback collection forms for UAT, gathering structured JSON input and creating actionable issue reports for agents.
---
# Collect User Inputs & UAT Feedback Skill

This skill allows agents to generate interactive, custom HTML forms to collect structured UAT feedback, bug reports, and design choices directly from the user. Form submissions are saved as JSON, generating issues for agents to solve.

---

## Workflow Steps

### Step 1: Generate Custom HTML Feedback Form
1. Create a self-contained HTML page in `scratch/<task_name>_uat_form.html`.
2. Apply Solarized Light (`#fdf6e3`) and Retro Dark (`#002b36` / `#073642`) styling.
3. Include specific, multidimensional input fields:
   - **Target Component / Page**: Select dropdown (e.g. Ingestion Feed, Virtual Sites, Collections, Admin Settings, Extension).
   - **Overall Rating / Status**: Pass, Pass with Issues, Fail.
   - **Specific Bugs & Issues**: Textarea detailing step-to-reproduce, expected vs actual behavior.
   - **Visual / Layout Feedback**: Aesthetics, theme alignment, scaling issues.
   - **Requested Agent Actions**: List of specific fixes requested by the user.

### Step 2: Direct User to Open Form
1. Direct the user to open `scratch/<task_name>_uat_form.html` in their web browser.
2. Instruct them to fill in feedback and click **"Save JSON"** (saving to `scratch/<task_name>_uat_issues.json`).

### Step 3: Process JSON & Generate Agent Tasks
1. Read `scratch/<task_name>_uat_issues.json` using `view_file`.
2. Extract all reported bugs and requested fixes.
3. Generate structured issues/tasks and execute the code fixes.
4. Record UAT test log in `uat/reports/` and commit to VCS.
