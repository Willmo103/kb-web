# User Feedback Record

**Sprint / Feature Branch**: `feature/mobile-views-articles-page-and-background-tasks`  
**Date**: 2026-10-12  
**Recorded By**: Antigravity Pair Programmer  

---

## 1. Summary of User Feedback Received

The user reported four key areas needing refinement and new capabilities:

### A. Mobile Views & Navigation Polish
1. **Header Brand Title on Mobile**:
   - *User Observation*: "The page title does not display I just see a stack of books emoji on the left side as though a icon, and no title."
   - *Requirement*: Make the brand title ("Knowledge Base") visible and responsive on mobile viewports rather than hiding it.
2. **Admin Portal Desktop Layout**:
   - *User Observation*: "on the *desktop* view--the layout is just bad. there needs to be margins on the lower sections. (photo attached)"
   - *Requirement*: Add proper spacing and margins (`space-y-8`, bottom padding/margins, clean section division) to the lower sections in `tab-backups` (Server Database Snapshots and Administrative Batch Operations & Content Purge).
3. **Admin Portal Mobile Tab Navigation**:
   - *User Observation*: "on the mobile version the admin page has a scroll bar for the page options and it is very uncool to use. I would prefer the links be static buttons for the mobile view"
   - *Requirement*: Replace the horizontally scrolling tab navigation bar (`overflow-x-auto`) with responsive static button cards/grid on mobile.
4. **Home Page Left Navigation Sidebar on Mobile**:
   - *User Observation*: "On the Home paage in the mobile view we need to make the left side nav bar hidden since the nav bar now expands and contracts hamburger style."
   - *Requirement*: Hide `<aside>` left navigation on mobile/tablet screens (`hidden lg:block`) since the global hamburger drawer already provides full navigation.

### B. Dedicated Articles Page
1. **Separate Articles Page**:
   - *User Observation*: "Create an articles page seperate from home, ensure the link to articles is accessable from all pages."
   - *Requirement*:
     - Create a dedicated `/articles` route and view specifically for articles.
     - Add `📄 Articles` to the top desktop navbar (`base.j2.html`), mobile hamburger drawer menu, and sidebar navigation on all pages.
     - Keep `/` as the primary Home Portal with overview/recent content and quick links.

### C. Background Server Autonomous Tasks & Worker Engine
1. **Periodic Ingestion Completion & Tagging**:
   - *User Observation*: "Since we can import pages that don't get wikis and shit right away, we need to create tasks that will run every X min or so that will look for things with out wikis and generates them, one at a time, failing gracefully. Should also look for things that need new tags."
2. **Extensible Autonomous Capabilities**:
   - *User Observation*: "this could aslo be something nice for creating index questions about articles, testing rag results, examining links and fetching more content autonomyously. these are just ideas, but this is sort of the thing that I want to do."
3. **Architecture Options Comparison**:
   - *User Observation*: "Maybe this should be like an n8n layer or something in supabase. give me my options for this in your implimentation plan."

---

## 2. Action Items & Resolution Plan
- [ ] Save feedback in `user_feedback.md` before code changes (completed).
- [ ] Detail and compare background worker architecture options (Native in-process worker vs. Sidecar systemd daemon vs. n8n workflow vs. Supabase pg_cron) in `implementation_plan.md`.
- [ ] Present implementation plan directly to the user.
- [ ] Implement mobile fixes in `base.j2.html`, `admin.j2.html`, and `pages_list.j2.html`.
- [ ] Implement dedicated `/articles` route and page.
- [ ] Implement autonomous background worker engine with graceful failure, single-item processing, notification logs, and admin dashboard controls.
