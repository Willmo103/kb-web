## Release v0.5.13 (Staging Production -> Master)

This draft pull request tracks the next stage of verified increments (`v0.5.13`) staged on `production` for eventual promotion into `master` following the repository tiered release lifecycle.

### Baseline Release Synchronized (`v0.5.12`)
- **Raw READ-ONLY SQL Query Reports Gated by Decision Model (`routers/reports.py`, `templates/reports.j2.html`)**
- **Clickable Selection Cards on Import Crawl and Collection Operations (`templates/url_import.j2.html`, `templates/view_collection.j2.html`)**
- **Admin Server Restart Action with Optional Git Pull & UV Sync (`routers/admin.py`, `templates/admin.j2.html`, GitHub Issue #120)**

### Upcoming Increments (`v0.5.13`)
- Ongoing verified features and bugfixes merged from `development` -> `production` will accumulate in this PR prior to the next formal release cut.
