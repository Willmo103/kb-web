# User Feedback - Build Audit, Responsive Mobile Nav, and Async Ingestion Pipeline

**Date**: 2026-10-12  
**Branch**: `feature/async-ingestion-mobile-nav-and-build-audit`  

---

## 1. User Feedback Summary

1. **Build Script Audit (`build.py`)**:
   - The user noticed unnecessary steps in `build.py` causing hangs and lag.
   - Specifically requested removing:
     - Building docker containers (`bootstrap_database` running docker-compose / socket waits).
     - Building packages (`uv build`, `python -m build`).
     - Copying packages to remote folder (`copy_artifacts`, `ARTIFACTS_ROOT`).
   - Keep `build.py` fast, focused on pre-commit environment validation and test verification.

2. **Mobile Navigation Screen Overflow (`base.j2.html`, `view_page.j2.html`)**:
   - On mobile phones, top navigation menu buttons stretch the screen horizontally.
   - Causes severe horizontal scrolling and broken viewports across article views and other pages.
   - Needs responsive layout: clean mobile hamburger/drawer menu, prevention of viewport blowout, proper flex wrapping, and responsive containment.

3. **Elimination of Synchronous Loading Page & Background Async Ingestion Pipeline**:
   - Large HTML pages and YouTube video imports frequently fail or get stuck on the synchronous streaming loading page (`/import/url`).
   - Scraped articles, transcripts, and metadata are lost when timeouts or failures occur during LLM extraction or network requests.
   - The loading page must be eliminated entirely.
   - All import processing must happen in the background with isolated, re-runnable stages:
     - **Save raw content & transcript immediately to DB** so data is never lost.
     - Isolate LLM wiki summarization, tag extraction, vector embeddings, and video downloading into individual resilient steps.
   - **LLM Timeout**: Increase LLM prompt timeout to 1000–1200 seconds so prompts never timeout prematurely.
   - **Notifications Section**: Provide a notifications section/feed in the UI informing the user of background progress:
     - Article fetched successfully
     - Article wiki described successfully
     - Tags / embeddings generated successfully
     - Detailed error alerts if an isolated step fails.

4. **Production Merge & Link Extraction Pre-requisite (Latest Feedback)**:
   - "merge the previous changes toproduction first." -> Completed via PR #84 (staged development -> production fast-forward).
   - "use the new html parsing for all of these changes." -> Ensure `html_to_clean_markdown` is universally applied.
   - "MAKE SURE THE GET THE LINKS OUT OF THE HTML BEFORE removing the nav and other sections from the import." -> Extract all hyperlinks from the untouched, raw HTML before stripping `<nav>`, `<header>`, `<footer>`, `<aside>`, or boilerplate containers.
