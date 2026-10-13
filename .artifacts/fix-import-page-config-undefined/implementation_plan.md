# Implementation Plan: Fix 'config' is undefined on `GET /import`

## Root Cause Analysis
During the implementation of the Git Repository web importer in `url_import.j2.html`, line 277 introduced:
```html
<input type="number" id="repoCloneDepth" value="{{ config.repo_import_default_depth or 1 }}" min="1" max="100" ...>
```
However, the routes serving `url_import.j2.html` in `src/kb_web/routers/admin.py`:
- `get_import_url_page()` (line 136)
- `handle_incoming_mobile_share()` (line 161)
rendered the template using:
```python
template.render(is_admin=True, collections=collections)
```
without passing `config=config`, and `_jinja_env.globals` did not define `config`. This caused Jinja2 to raise `jinja2.exceptions.UndefinedError: 'config' is undefined` when accessing `/import`.

## Proposed Fix (Defense-in-Depth)

1. **Global Jinja2 Configuration Exposure (`src/kb_web/base.py`)**:
   - Register `_jinja_env.globals["config"] = config`.
   - Ensures that all Jinja2 templates across the application can safely access global configuration attributes without relying solely on every route handler explicitly passing `config=config`.

2. **Explicit Parameter Passing (`src/kb_web/routers/admin.py`)**:
   - In `get_import_url_page()`:
     ```python
     return HTMLResponse(content=template.render(is_admin=True, collections=collections, config=config))
     ```
   - In `handle_incoming_mobile_share()`:
     ```python
     return HTMLResponse(content=template.render(prefilled_url=target_link, is_admin=True, collections=collections, config=config))
     ```

3. **Defensive Template Guard (`src/kb_web/templates/url_import.j2.html`)**:
   - Safeguard line 277 with Jinja2 `defined` check and fallback:
     ```html
     value="{{ (config.repo_import_default_depth if (config is defined and config) else 1) or 1 }}"
     ```

4. **Regression Unit Testing (`tests/test_server.py`)**:
   - Add unit test verifying `GET /import` and `GET /import/shared-url` render with HTTP 200 and properly populate `repoCloneDepth` without raising `UndefinedError`.

5. **Self-Documentation & Release Flow**:
   - Update `CHANGELOG.md` under `[Fixed]`.
   - Run `uv run pytest` and pre-commit checks.
   - Commit on `fix/import-page-config-undefined`.
   - Merge into `development` and then merge/push into `production`.
