# Sprint Execution Workflow

This document defines the systematic, step-by-step workflow that agents and developers must follow when executing a development sprint.

---

## Step-by-Step Workflow

### 1. Sprint Discovery & Artifact Reading
- Locate and read the corresponding sprint details document (e.g. `sprint_1_dev_env.md`).
- Review the sprint goal, parent/child issue IDs, and the task checkboxes checklist.

### 2. Dedicated Branch Creation
- Ensure your local repository is up to date:
  ```bash
  git checkout production
  git pull origin production
  ```
- Create a dedicated feature branch for the sprint:
  ```bash
  git checkout -b feature/sprint-<number>-<short_description>
  ```
  *(Example: `git checkout -b feature/sprint-1-dev-env`)*

### 3. Draft Pull Request & Issue Association
- Publish the sprint branch to the remote repository:
  ```bash
  git push -u origin feature/sprint-<number>-<short_description>
  ```
- Create a draft Pull Request back to `production` using the GitHub CLI:
  ```bash
  gh pr create --draft --base production --title "Sprint <number>: <Goal Description>" --body "Resolves Sprint Issues"
  ```
- Retrieve the PR number and associate all sprint issues with the draft PR (using the parent/child issues listed in the sprint document).

### 4. Incremental Task Resolution
- Work through the issues sequentially using the sprint checklist as your progress guideline.
- As tasks are completed, update the checkbox states in the sprint document (change `[ ]` to `[x]`).
- Commit changes incrementally with descriptive messages, ensuring the updated sprint markdown document is committed together with the code edits.

### 5. Verification & PR Readiness
- Run the full regression test suite (`uv run pytest`), linter (`uv run ruff check .`), and template verifiers (`verify_ui_templates.py`).
- Run the UAT report generator tool to compile testing artifacts under `uat/`.
- Switch the Pull Request from **Draft** to **Ready for Review**:
  ```bash
  gh pr ready <pr_number>
  ```
- Add review comments directly on the PR's code diff where helpful to explain custom configurations, design choices, or database schemas.
- **Do not merge the PR.** Leave the Pull Request open for the user to review, approve, and merge back to `production`.
