# Implementation Plan: HTML Boilerplate Stripper & Markdown Cleaner

## 1. Overview & Problem Statement
Currently, `kb-web` converts imported HTML documents directly via `HTML2Text().handle(raw_html)` without stripping webpage boilerplate. This pulls navigation bars, search headers, cookie banners, menus, and footers into `md_content`, cluttering the markdown and making articles noisy.

We will build a dedicated HTML cleaning and markdown synthesis pipeline that:
1. Parses raw HTML with BeautifulSoup and strips non-content tags (`header`, `nav`, `footer`, `aside`, `script`, `style`, `noscript`, `svg`, `form`, etc.) and boilerplate class/id containers (cookie/consent banners, social share bars).
2. Extracts core semantic content containers (`<article>` or `<main>`), falling back to cleaned `<body>`.
3. Converts the sanitized HTML to clean Markdown with optimal formatting (`body_width = 0`, no link spam).
4. Provides a **safe, dry-run preview tool** that compares before-and-after markdown across actual database records with metrics (character reduction, line count reduction) and generates an interactive side-by-side comparison artifact before any database records are modified.
5. Provides a controlled `--apply` batch command that creates audit backups in `page_versions` before updating `md_content`.
6. Integrates the cleaner into the live ingestion pipeline (`fetch_url` and `/api/import/html`).

---

## 2. Proposed Architecture & Component Design

### A. Core Sanitizer: `src/kb_web/html_cleaner.py`
- `strip_boilerplate_elements(soup: BeautifulSoup) -> BeautifulSoup`:
  - Decomposes tags: `["header", "nav", "footer", "aside", "script", "style", "noscript", "svg", "form", "iframe", "button"]`.
  - Removes common banner/modal/ad containers matching regex patterns `(cookie|consent|banner|newsletter|sidebar|social-share|ad-|advertisement|popup|modal)`.
- `extract_primary_content_container(soup: BeautifulSoup) -> Tag`:
  - Inspects `<article>` and `<main>`. If either contains substantive text (>250 chars), isolates it. Otherwise falls back to cleaned `<body>`.
- `html_to_clean_markdown(raw_html: str) -> str`:
  - Runs HTML cleanup.
  - Passes sanitized markup to `HTML2Text` configured with `body_width = 0` (no awkward 78-col hard wrapping), `ignore_links = False`, `protect_links = True`, `skip_internal_links = True`.
  - Post-processes markdown: collapses redundant whitespace and blank lines.

### B. Dry-Run Preview & Batch Migration Tool
- `scripts/preview_html_cleaning.py` / CLI integration:
  - `--url <url>`: Test against a specific URL in the database.
  - `--sample <N>`: Sample N real imported HTML records from `fetched_pages` (default: 5).
  - `--output-report <path>`: Generates an interactive side-by-side HTML comparison artifact (`before` vs `after`, diff summary, reduction %).
  - `--dry-run`: Default mode! No database changes.
  - `--apply`: Only executes database update when explicitly commanded:
    - Protects `is_frozen == 1` pages.
    - Archives current record into `page_versions` for full rollback safety.
    - Updates `md_content` and recalculates `md_content_hash`.

### C. Live Pipeline Integration
- Update `src/kb_web/utils.py` (`fetch_url`) and `src/kb_web/routers/api.py` (`/api/import/html`) to utilize `html_to_clean_markdown` for future imports.

---

## 3. User Review & Acceptance Checklist
- [ ] Safe dry-run sampling against real database rows.
- [ ] Visual side-by-side comparison report generated for user review.
- [ ] Preserves all code blocks, tables, images, and content headings within actual articles.
- [ ] Protects frozen records and archives old markdown in `page_versions`.
- [ ] Full test coverage and pre-commit checks.
