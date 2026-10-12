# Walkthrough: HTML Boilerplate Stripper & Clean Markdown Generator

This document summarizes the architecture, implementation, verification, and usage of the HTML boilerplate cleaning engine implemented for `kb-web`.

---

## 1. Problem & Objectives
Previously, imported HTML documents were passed directly into `HTML2Text().handle(raw_html)` without decomposing structural navigation, headers, footers, and advertising chrome. This resulted in messy, noisy markdown containing website menus, breadcrumbs, search boxes, and cookie banners.

The new cleaner pipeline:
1. Decomposes non-content structural elements (`<header>`, `<nav>`, `<footer>`, `<aside>`, `<script>`, `<style>`, `<noscript>`, `<svg>`, `<form>`, `<button>`).
2. Strips boilerplate containers matching patterns like cookie/consent banners, social share bars, and advertisement widgets.
3. Automatically detects and prioritizes substantive article containers (`<article>` or `<main>`), falling back to the sanitized `<body>`.
4. Synthesizes high-density Markdown using `HTML2Text` with `body_width = 0` (preventing artificial 78-character line wrapping) and custom link formatting.
5. Provides a **safe dry-run inspection tool** (`scripts/preview_html_cleaning.py`) that generates side-by-side visual HTML comparison reports without modifying database records.

---

## 2. Component Reference

### A. Core Sanitizer ([src/kb_web/html_cleaner.py](file:///C:/src/kb-web/src/kb_web/html_cleaner.py))
- `strip_boilerplate_elements(soup)`: Decomposes noise tags and banner containers in place.
- `extract_primary_content_container(soup)`: Extracts the primary article body (`<article>` or `<main>`) if substantive text (>250 chars) exists.
- `html_to_clean_markdown(raw_html)`: Sanitizes HTML and generates clean, whitespace-collapsed Markdown.
- `compare_markdown_cleaning(raw_html, original_md)`: Computes character differences, line count differences, and noise reduction percentages.

### B. Ingestion Pipeline Integration
- [src/kb_web/utils.py](file:///C:/src/kb-web/src/kb_web/utils.py#L435-L440): Updated `fetch_url()` to use `html_to_clean_markdown(html_content)`.
- [src/kb_web/routers/api.py](file:///C:/src/kb-web/src/kb_web/routers/api.py#L55-L65): Updated `/api/import/html` to use `html_to_clean_markdown(html_content)`.

### C. Safe Dry-Run & Batch Preview Tool ([scripts/preview_html_cleaning.py](file:///C:/src/kb-web/scripts/preview_html_cleaning.py))
- **Dry-run Mode (Default)**: Inspects database records safely without making any writes.
- **Live URL Testing**: Pass `--fetch-url <url>` to fetch and test live web pages on the fly.
- **Sample Mode**: Pass `--sample <N>` to sample $N$ pages from `fetched_pages`.
- **Apply Mode**: Pass `--apply` to commit cleaned markdown to the database. Automatically skips frozen articles (`is_frozen = 1`) and archives the old record into `page_versions`.
- **Side-by-side Report**: Outputs an interactive visual comparison HTML report at `.artifacts/feature-html-boilerplate-stripper-and-cleaner/html_cleaning_preview.html`.

---

## 3. Verification & Live Results

### Unit Tests
All 6 tests in [tests/test_html_cleaner.py](file:///C:/src/kb-web/tests/test_html_cleaner.py) passed:
- `test_strip_boilerplate_tags`: Verifies decomposition of header, nav, footer, script, and style tags.
- `test_strip_cookie_and_ad_containers`: Verifies removal of banners, sidebars, and newsletter modals.
- `test_extract_primary_content_container`: Verifies `<article>` and `<main>` prioritization.
- `test_html_to_clean_markdown`: Verifies markdown conversion and heading preservation.
- `test_compare_markdown_cleaning_metrics`: Verifies metric calculation.
- `test_empty_or_whitespace_html`: Handles edge cases gracefully.

### Live URL Test Results
| Target | Raw HTML2Text | Cleaned Markdown | Reduction |
|---|---|---|---|
| FastAPI First Steps (`fastapi.tiangolo.com`) | 22,016 chars (851 lines) | 14,342 chars (484 lines) | **-34.86%** (-7,674 chars) |
| Cloudflare Pingora (`blog.cloudflare.com`) | 5,611 chars (186 lines) | 1,748 chars (61 lines) | **-68.85%** (-3,863 chars) |
| Python `difflib` Docs (`docs.python.org`) | 35,676 chars (1,092 lines) | 34,536 chars (748 lines) | **-3.20%** (-1,140 chars) |
