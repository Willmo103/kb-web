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

---

### 6. `nh3` HTML Sanitizer & `link_rel` Attribute Trap
- **Issue**: When using `nh3.clean()` in Python, `link_rel="noopener noreferrer"` is enabled by default for `<a>` tags. Specifying `"rel"` inside `attributes={"a": {"href", "rel", ...}}` triggers `ValueError: "rel" attribute is not allowed for tag "a" when link_rel is set; pass link_rel=None to manage the "rel" attribute directly`.
- **Rule**: Omit `"rel"` from the `attributes["a"]` set and let `nh3` manage safe `link_rel` values automatically, or explicitly pass `link_rel=None` if custom `rel` values are required.

---

### 7. Git CLI Subprocess Invocation & Argument Injection
- **Issue**: Passing user-supplied URLs to `git clone` with `shell=True` on Windows or without the `--` argument delimiter allows argument injection (e.g. `--upload-pack=...`) and local repository/file exfiltration (`file://...`).
- **Rule**: Always validate URLs with protocol allowlists (`https://`, `http://`, `ssh://`, `git@`), forbid leading dashes, resolve the binary with `shutil.which("git")`, pass `shell=False`, and invoke git with `-c protocol.file.allow=never` and `--` delimiters before positional arguments.

