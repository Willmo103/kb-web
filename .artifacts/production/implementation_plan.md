# Implementation Plan - Merge PR #28 ("Production") into Master & Release v0.2.1

Transition Pull Request [#28](https://github.com/Willmo103/kb-web/pull/28) from draft to ready for review, resolve and close the associated GitHub issues for Sprint 2, Sprint 3, and Parent Issue #30, update the project sprint progress reports and documentation, bump version to `0.2.1`, verify pre-commit and build pipelines, merge PR #28 to `master`, and publish release `v0.2.1`.

## User Review Required

> [!IMPORTANT]
> **Version Alignment to 0.2.1**:
> `pyproject.toml` currently has `version = "0.1.29"`. Tag `v0.1.29` already exists on GitHub from PR #23. `CHANGELOG.md` already defines `0.2.1` as the active release representing the complete PostgreSQL migration, CLI database tools, logical replication, and video backup retention. We will bump `pyproject.toml` to `0.2.1` so that the automated release workflow (`.github/workflows/test-and-release.yml`) builds and publishes `v0.2.1` upon merging into `master`.

> [!NOTE]
> **Scope of Closed Issues**:
> - **Sprint 2**:
>   - Issue #41: Sprint 2: SQLAlchemy ORM & pgvector Searches
>   - Issue #42: Sub-Issue 3: pgvector Extension Integration & Embeddings Refactor
>   - Issue #43: Sub-Issue 4: SQLAlchemy ORM Schema mapping
>   - Issue #44: Sub-Issue 5: Database Session & Driver Abstraction
> - **Sprint 3**:
>   - Issue #45: Sprint 3: Core Database Access Refactoring & Migration Utility
>   - Issue #46: Sub-Issue 6: Database Access Refactoring
>   - Issue #47: Sub-Issue 7: SQLite-to-PostgreSQL Data Ingest Utility
> - **Parent Issue**:
>   - Issue #30: PostgreSQL | SQLAlchemy Support (Sprints 1, 2, and 3 complete all phases of this parent issue)
> - **Remaining Open Issues** (Phase 4 & 5 - Sprints 4 & 5):
>   - Issue #29 (Import Process Refactor), Issue #48/49/50 (Sprint 4 Job Queue), Issue #51/52/53/36 (Sprint 5 WebSocket Ingestion & Docling) remain OPEN for future development.

---

## Proposed Changes

### 1. Step 1: Move PR #28 to Ready for Review
- Execute `gh pr ready 28` to mark PR #28 as open and ready for review.

---

### 2. Step 2: Comment On & Close Associated Issues, Update Documentation & CI/CD Artifacts

#### [MODIFY] [.artifacts/analysis-issues-29-30/sprint_tracker.md](file:///c:/src/kb-web/.artifacts/analysis-issues-29-30/sprint_tracker.md)
- Update Sprint 3 checklist status to `[x]` (Completed).
- Check off Sub-Issue 6 (#46) and Sub-Issue 7 (#47).
- Correct typo on line 19 referencing `(Issue #51)` to `(Issue #44)` for Sub-Issue 5.

#### [MODIFY] [.artifacts/analysis-issues-29-30/sprint_2_orm_pgvector.md](file:///c:/src/kb-web/.artifacts/analysis-issues-29-30/sprint_2_orm_pgvector.md)
- Mark all item checkboxes for Sub-Issues #43, #44, and #42 as completed `[x]`.

#### [MODIFY] [.artifacts/analysis-issues-29-30/sprint_3_core_refactor.md](file:///c:/src/kb-web/.artifacts/analysis-issues-29-30/sprint_3_core_refactor.md)
- Mark all item checkboxes for Sub-Issues #46 and #47 as completed `[x]`.

#### [MODIFY] [pyproject.toml](file:///c:/src/kb-web/pyproject.toml)
- Bump `version` from `"0.1.29"` to `"0.2.1"`.

#### [MODIFY] [CHANGELOG.md](file:///c:/src/kb-web/CHANGELOG.md)
- Verify `[0.2.1]` header references all resolved issue numbers (#30, #41, #42, #43, #44, #45, #46, #47).

#### GitHub Issues & PR Updates
- **Step 2.1 (Issue Comments & Closure)**:
  - Add resolution comments to each issue explaining the implementation and linking to PR #28.
  - Close issues #42, #43, #44, #41, #46, #47, #45, and #30 via `gh issue close <number> --comment "..."`.
  - Commit documentation changes to `production` branch and push to `origin/production`.
  - Post progress comment on PR #28 listing all closed issues and committed artifacts.
- **Step 2.2 (Sprint Progress Report PR Comment)**:
  - Post comprehensive sprint completion and merge-to-master readiness comment on PR #28 including the full Sprint Progress Report table and changelog highlights.

---

### 3. Step 3: Merge PR #28 to Master & Create Release v0.2.1
- Execute PR merge:
  ```bash
  gh pr merge 28 --merge --subject "Merge pull request #28 from Willmo103/production" --body "Release v0.2.1: PostgreSQL & SQLAlchemy ORM migration, pgvector similarity searches, replication & database management CLI, and Admin backups."
  ```
- Checkout and pull `master`:
  ```bash
  git checkout master
  git pull origin master
  ```
- Verify CI/CD pipeline / create GitHub Release `v0.2.1`:
  - Verify GitHub Actions workflow run for release `v0.2.1` or execute:
    ```bash
    gh release create v0.2.1 --title "Release v0.2.1" --notes "Release v0.2.1: Full PostgreSQL migration, SQLAlchemy ORM, pgvector similarity searches, kb-web db CLI, logical replication, YouTube video management, and Admin Dashboard local backups." dist/*.whl dist/*.tar.gz
    ```

---

## Verification Plan

### Automated Tests
- Run complete pytest suite:
  ```bash
  uv run pytest
  ```
- Run build pipeline to verify packages compile:
  ```bash
  uv run python build.py
  ```
- Run UI templates validation:
  ```bash
  python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py
  ```
- Generate UAT testing artifact:
  ```bash
  python .agents/skills/generate-uat-testing-artifact/scripts/generate_uat_report.py
  ```

### Manual & GitHub Verification
- Confirm PR #28 state changes: Draft -> Ready -> Merged.
- Confirm issues #41, #42, #43, #44, #45, #46, #47, #30 are CLOSED.
- Confirm GitHub Release `v0.2.1` is published with built wheel and source distribution assets.
