# Package Quirks & Technical Caveats Memory

Record of package-specific traps, configurations, and quirks discovered across development turns.

---

### 1. `yt-dlp` Video & Audio Streams
- **Issue**: Modern YouTube videos serve separated adaptive video and audio streams (DASH/HLS). Requesting `"format": "mp4/best"` selects a pre-muxed container. Since YouTube almost exclusively serves legacy 360p pre-muxed mp4 streams, `best` causes yt-dlp to pick the best single stream, which is **video-only without sound**.
- **Rule**: Always specify combined stream selectors such as `bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b` and explicitly set `"merge_output_format": "mp4"`. Ensure `ffmpeg` is available on the system PATH.
- **Config**: Expose format strings in `/admin` per Rule 7.

---

### 2. Python `hmac.compare_digest` with Strings
- **Issue**: `hmac.compare_digest(a, b)` strictly requires ASCII-only string characters when strings are passed. If a user supplies a non-ASCII password (e.g. `pässwörd`) or non-ASCII header value, Python raises `TypeError: comparing strings with non-ASCII characters is not supported`.
- **Rule**: Always encode strings to bytes (`a.encode("utf-8")`) before calling `hmac.compare_digest()`.

---

### 3. Windows PowerShell & `gh issue create` Quoting
- **Issue**: When running `gh issue create` in PowerShell, passing file paths with `--body-file $tmp` can fail with `unknown argument "..."; please quote all values that have spaces` if paths contain spaces or backslashes.
- **Rule**: Quote the argument explicitly (`--body-file "$tmp"`) or use stdin (`--body-file -`). Always use temporary files with utf-8 encoding rather than large inline string flags (`--body "..."`) to avoid terminal escaping issues.

---

### 4. Jinja2 Autoescaping & Structural HTML
- **Issue**: Jinja2 blocks and conditional divs (`{% if %}`) must be carefully audited. A dropped `</div>` inside an `{% if %}` block can nest sibling `.admin-tab-pane` containers, making JavaScript tab-switchers hide all content panes simultaneously.
- **Rule**: Run `verify_ui_templates.py` before commit. Always verify tag balance and ensure that container elements with IDs or tabs are siblings in the DOM.

---

### 5. Multi-Statement SQL in SQLite / Alembic
- **Issue**: SQLite's Python driver `sqlite3` does not allow multiple SQL statements in a single `cursor.execute()`. Running migration scripts containing multiple `CREATE TABLE` and `CREATE INDEX` queries in a single `session.execute(text(...))` call raises `sqlite3.ProgrammingError: You can only execute one statement at a time`.
- **Rule**: Split multi-statement SQL strings by semicolon and execute statements individually.
