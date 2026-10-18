# User Feedback

**Date**: 2026-10-17  
**Branch**: `feature/security-quick-wins-sprint`  
**Directives**:
1. Work on Task 1 from the Code Audit Review:
   - **SEC-01 (Issue #93)**: Rate-limit spoofing (trusting `X-Forwarded-For`).
   - **SEC-03 (Issue #95)**: Repo-import argument injection & unsafe `shell=True`.
   - **SEC-02 (Issue #94)**: Stored HTML / Markdown XSS + missing Content Security Policy (CSP).
   - **SEC-04 (Issue #96)**: Fail-closed default credentials (`admin123` / `kb-secret-key`).
2. Optional stretch goal ("feel froggy"): Task 2:
   - **SEC-05 (Issue #111)**: Random session secret independent of admin password.
   - **SEC-06 (Issue #110)**: Hashed passwords (e.g. `scrypt`) & no secrets in `kb-web.json`.
3. Tracking requirements:
   - Maintain a draft PR to `master` to track progress.
   - Associate issues to commits (e.g., `Refs #93`, `Fixes #93`, etc. in commit messages).
4. Follow strict development lifecycle: verify tests, maintain documentation, provide clear implementation plan before code execution.
