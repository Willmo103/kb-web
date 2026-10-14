# Walkthrough: Fix 'config' is undefined on `GET /import` & Future Issues Creation

## 1. Bug Fix: 'config' is undefined on `GET /import`

### Root Cause
`url_import.j2.html` line 277 referenced `config.repo_import_default_depth`:
```html
<input type="number" id="repoCloneDepth" value="{{ config.repo_import_default_depth or 1 }}" min="1" max="100">
```
In `src/kb_web/routers/admin.py`, `get_import_url_page()` and `handle_incoming_mobile_share()` called `template.render(is_admin=True, collections=collections)` without passing `config=config`, and `_jinja_env.globals` did not bind `config` globally.

### Solution Applied (Defense-in-Depth)
1. **Global Binding in `src/kb_web/base.py`**:
   - Registered `_jinja_env.globals["config"] = config` so all templates have access to application config.
2. **Explicit Passing in `src/kb_web/routers/admin.py`**:
   - Updated `get_import_url_page()` and `handle_incoming_mobile_share()` to explicitly pass `config=config`.
3. **Template Fallback Guard in `src/kb_web/templates/url_import.j2.html`**:
   - Wrapped line 277 with safe Jinja2 evaluation: `value="{{ (config.repo_import_default_depth if (config is defined and config) else 1) or 1 }}"`.
4. **Regression Unit Test in `tests/test_server.py`**:
   - Added `test_import_page_renders_with_config_context` verifying that `/import` and `/import/shared-url` render with HTTP 200.

### Release & Verification
- Unit test passed: `tests/test_server.py::test_import_page_renders_with_config_context`
- UI template verification: 25 templates checked, 0 warnings.
- Committed to `fix/import-page-config-undefined`, merged into `development`, merged into `production`, and pushed to `origin`.

---

## 2. Future Issues Created on GitHub Repository

Per instructions, the following future issues were created on `Willmo103/kb-web` for tracking:

1. **Issue #91**: [[FUTURE] Error Agent: Source code inspection tools, distilled live debugging system prompt, and GitHub issue reporting](https://github.com/Willmo103/kb-web/issues/91)
   - Read-only tools for error agent to view source code and logs.
   - Distilled architecture-aware system message for live debugging.
   - Explaining credentialing (`GITHUB_TOKEN` / `GH_TOKEN`) and enabling automated issue creation for unhandled server crashes.

2. **Issue #92**: [[FUTURE] Expose various system messages and prompt templates in the admin portal](https://github.com/Willmo103/kb-web/issues/92)
   - Audit all non-numerical prompt strings, system instructions, and classification templates.
   - Refactor the Admin Portal with Monaco Editor and live split-pane rendered Markdown preview.
