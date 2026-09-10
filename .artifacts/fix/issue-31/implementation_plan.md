# Implementation Plan - Expose Links Privileged Guard & Gotify Test Alert Mitigation

This plan addresses:
1. **Issue #31 ("Links are Exposed")**: Restricts both `GET /links` (the link catalog page) and `GET /links/go` (redirection tracking) to authenticated users only.
2. **Gotify Test Alert Mitigation**: Modifies the test setup fixture in `tests/test_server.py` to mock `kb_core.notifier.Gotify` so that real notifications are not dispatched during tests.
3. **Documentation updates**: Documents test run guidelines for disabling Gotify in `README.md` and `GEMINI.md`.

---

## Proposed Changes

### Links Router Security

#### [MODIFY] [links.py](file:///c:/src/kb-web/src/kb_web/routers/links.py)
- Protect GET `/links` and GET `/links/go` by adding `Depends(verify_auth)` to restrict access to authenticated users only.

### Test suite

#### [MODIFY] [test_server.py](file:///c:/src/kb-web/tests/test_server.py)
- Update the `setup_temp_db` fixture to mock `kb_core.notifier.Gotify` with a dummy class that disables posting.
- Update `test_links_management_and_tracking` to assert that accessing `/links` and `/links/go` without active session credentials correctly redirects (303) to `/login`.
- Assert that accessing them with active session cookies returns the expected success responses (200 / 303 redirect to final URL).

### Documentation

#### [MODIFY] [README.md](file:///c:/src/kb-web/README.md)
- Document the environment/setup required to run tests without triggering real Gotify notifications.

#### [MODIFY] [GEMINI.md](file:///c:/src/kb-web/GEMINI.md)
- Mention Gotify test alert mitigation guidelines in the agent instructions.

#### [MODIFY] [CHANGELOG.md](file:///c:/src/kb-web/CHANGELOG.md)
- Add a new version header `[0.1.31]` documenting the security fix, test improvement, and updated test documentation.

---

## Verification Plan

### Automated Tests
- Run `uv run pytest` to ensure all tests pass (especially link management and settings persistence tests).
- Verify that `build.py` runs and finishes cleanly.
