# User Feedback - UI Performance Evaluation, Pagination, & API Overhaul

## User Prompt & Feedback (Turn 1)
> "After the recent database migration the web UI is preforming much slower. I think that we need a UI overhaul. introducing pagination and reactive elements. Possibly shifting the backend to an API structure and the frontend to consume the API. I would also like to be able to use more of the routes as API routes for other applications like fetching articles or video transcripts, etc .
> 
> Evaluate how we can speed up the UI. Specifically the loading of the main page is the most laitent, I think it's because it is loading all of the articles.
> 
> I think that creating a database view or stored procedures to fetch and pre-process data might be an answer"

## User Feedback (Turn 2)
> "This all needs to be documented in an issue on the master branch before you start. The development should take place on a new branch of production. a new DRAFT pr should be opened from production into master (but not closed) Issues should be associated with the draft PR. 
> 
> Also we are phasing out the SQLITE support"

## Directives & Execution Constraints

1. **Document in an Issue on the `master` Branch**:
   - Check out `master`.
   - Document the issue in `issues.md` on `master` and commit/push.
   - Create the tracking issue in GitHub (`gh issue create`).

2. **Branching Strategy**:
   - Branch off `production`: Create feature branch `feature/ui-performance-api`.
   - All feature implementation, views, API routes, and reactive UI components will be developed on this branch.

3. **Draft Pull Request**:
   - Open a DRAFT Pull Request from `production` into `master` using `gh pr create --draft --base master --head production`.
   - Associate the newly created issue with the draft PR.
   - Keep the PR open (do NOT close or merge).

4. **Phasing Out SQLite Support**:
   - The architecture is shifting away from SQLite to PostgreSQL as the single standard production database engine.
   - Database views can leverage native PostgreSQL features (such as `string_agg` for collection aggregation, robust index scans, and JSON operators) without needing SQLite fallback parity.
