# User Feedback & Requirements

**Date**: 2026-10-09
**Branch**: `feature/html-boilerplate-stripper-and-cleaner`

## User Request Summary
The user noted:
1. Markdown is the primary medium in the knowledge base, but existing markdown from imported web pages is cluttered with navigation headers, menus, footers, scripts, and boilerplate tags ("all of the headers and shit glom up the rendered markdown").
2. The user wants to clean the raw HTML first by stripping unwanted tags (`header`, `nav`, `script`, `style`, `footer`, `aside`, etc.), and then converting the cleaned HTML into clean Markdown.
3. The user wants to iterate and test this transformation over imported HTML sources in the database to evaluate the quality before permanently overwriting database records ("I need to test this out though to see if I like it since it would be overriting data in the database").

## User Design Feedback & Decision Sign-Off (Interactive Modal)
- **Preview & Inspection Preference**:
  - **Selected**: *Generate a side-by-side HTML comparison preview of 5 real database articles*.
  - Rationale: The user can visually review actual database articles rendered side-by-side (Original Raw Markdown vs. Sanitized Clean Markdown) with line/character reduction metrics before deciding to apply any database changes.
- **Boilerplate Stripping Aggressiveness**:
  - **Selected**: *Balanced: Decompose header/nav/footer/aside/scripts/forms and cookie/ad containers, prioritizing `<article>`/`<main>`*.
  - Rationale: Preserves essential body content, code blocks, tables, and images while stripping UI navigation, tracking, and structural boilerplate.

## Key Requirements & Guardrails
- **Safe Testing / Dry-Run Mode**: Must support a preview and dry-run mode that samples actual imported HTML pages from the database, compares old vs. new Markdown, and outputs side-by-side diffs/metrics without modifying any database records.
- **Selective Source Filtering**: Only target genuine HTML pages (`html_content IS NOT NULL AND length(html_content) > 100`), skipping synthetic sources like pure Markdown notes (`note://`), Git codebases (`repo://`), and frozen records (`is_frozen = 1`).
- **Reversibility & Auditability**: When the user decides to apply the cleaner, archive the existing Markdown into `page_versions` before updating `md_content`, ensuring no data loss.
- **Modern HTML2Text Configuration**: Remove word-wrap artifacts (`body_width = 0`), drop navigation link farms, decompose boilerplate tags, and clean up excessive empty lines.
