# User Acceptance Testing (UAT) & UI Validation Rules

This rule defines mandatory standards for User Acceptance Testing (UAT), UI validation, testing artifacts versioning, and interactive feedback collection for `kb-web`.

---

## 1. Strict Pre-Commit UI UAT Verification
- **Mandatory UAT Step**: Before committing any UI template changes (`src/kb_web/templates/`), CSS adjustments, or PWA/Extension feature updates, the agent MUST perform local UAT verification with the user.
- **Interim UAT Block**: The agent must NOT finalize binary packaging or execute git commit until local UI functionality is verified.

## 2. Generating VCS Testing Artifacts
- **Artifact Directory**: Agents MUST create and commit UAT verification artifacts under `uat/` inside the repository.
- **Testing Artifacts**:
  - `uat/reports/`: Markdown summary reports containing test scenarios executed, routes tested, browser extension responses, and validation screenshots/diagrams.
  - `uat/test_logs/`: Log outputs from test server runs or automated client interactions.
- **Version Control**: All generated UAT test reports and logs must be committed to git alongside the feature branch.

## 3. Collecting UAT Feedback via Custom HTML Pages
- When gathering user feedback on UI changes, new features, or design options, agents MUST use the `collect-user-inputs` skill to render a custom HTML feedback form.
- **Form Customization**:
  - Render a standalone, self-contained HTML page in `scratch/uat_feedback_form.html`.
  - Style the form in Solarized Light / Retro Dark theme.
  - Form fields must gather *specific, multidimensional feedback*: component usability ratings, exact visual bugs, responsiveness at scaling, expected vs actual behavior, and feature requests.

## 4. Generating Actionable Issues for Agents
- When the user submits the custom HTML feedback form:
  - Form saves structured JSON feedback to `scratch/uat_issues.json`.
  - The agent MUST parse `uat_issues.json`, extract identified bugs or feature requests, and generate structured issue tasks for itself to solve.
  - Once resolved, the agent updates the UAT test report artifact in `uat/reports/` and re-verifies.
