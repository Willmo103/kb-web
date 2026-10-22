# Sprint: Security Quick Wins (Task 1 & Credential Hygiene)

Draft PR tracking progress for Task 1 security vulnerabilities and credential hygiene from the Code Audit.

### Issues Addressed
- [x] **SEC-01** (Fixes #93): Rate-limit spoofing bypass via `X-Forwarded-For`
- [x] **SEC-03** (Fixes #95): Git repository import argument injection & `shell=True` on Windows
- [x] **SEC-02** (Fixes #94, Refs #97): Stored XSS via un-sanitized Markdown/HTML rendering + CSP implementation
- [x] **SEC-04** (Fixes #96): Fail-closed default credentials (`admin123` / `kb-secret-key`)
- [x] **SEC-05** (Fixes #111): Random session secret independent of admin password
- [x] **SEC-06** (Fixes #110): Hashed passwords (`scrypt`) and secret redaction from config/exports

### Status
- Implementation complete
- Pre-commit template verification passed (25 templates, 0 errors)
- Unit test suite passed (197 / 197 passed)
- Walkthrough and changelog documentation updated

### Child Sprints & Dependent Pull Requests
- Child PR #114: [Code Review Issue Generator Skill & Remaining Audit Fixes](https://github.com/Willmo103/kb-web/pull/114) (target: `development`)
