---
name: live-server-test
description: Uses curl to test and audit site routes against a live running test or production server without executing admin operations.
---
# Live Server Test Skill

Use this skill to audit public and protected site routes against a live running test or production server (e.g. `https://kb-test.willmo.dev`) using `curl`.

> [!IMPORTANT]
> **Safety Guardrail**: This skill is strictly **read-only**. It audits route availability, response headers, redirects, and content types via `GET` requests. It NEVER executes administrative operations, state changes, or mutating actions (`POST`, `PUT`, `DELETE`, `/admin/*`).

---

## Workflow

1. Run the live route audit script:
   ```bash
   uv run python .agents/skills/live-server-test/scripts/audit_live_routes.py --host https://kb-test.willmo.dev
   ```

2. Optional flags:
   - `--host <url>`: Base URL of the live server (default: `https://kb-test.willmo.dev`).
   - `--api-key <key>`: Optional API key to verify authenticated API responses.
   - `--cookie <session_cookie>`: Optional session cookie to verify authenticated UI views.
   - `--output <path>`: Path to write a markdown audit report (default: `uat/reports/live_server_audit_<timestamp>.md`).

3. What the audit verifies:
   - **Public Endpoints**: `/api/health`, `/login`, `/manifest.json`, `/favicon.ico` return HTTP 200.
   - **Protected UI Routes**: `/`, `/pages`, `/sites`, `/notes`, `/collections`, `/conversations`, `/reports`, `/reports/rag`, `/taxonomy`, `/workspaces` redirect to `/login` (HTTP 303) when unauthenticated, or return HTTP 200 when authenticated.
   - **Protected API Endpoints**: `/api/sites`, `/api/articles`, `/api/tags` return HTTP 401 Unauthorized when unauthenticated.
   - **Security Headers**: Verifies injection of `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, and `X-XSS-Protection`.
   - **Latency Benchmarks**: Measures total round-trip response time for each route.
