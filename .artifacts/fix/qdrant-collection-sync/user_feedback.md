# User Feedback - Turn 2026-09-13T20:24:40-05:00

## User Request
> "The next issue is that the QDrant export is broken it just says failed. I think it may be because there is not an API key
> 
> ```
> [2026-09-14T01:22:46.215054] INFO in server: Incoming request: GET http://kb.willmo.dev/admin/logs from 192.168.0.33
> [2026-09-14T01:22:43.111466] INFO in h11_impl: 192.168.0.33:57536 - "GET /manifest.json HTTP/1.1" 200
> [2026-09-14T01:22:43.105871] INFO in server: Completed request: GET http://kb.willmo.dev/manifest.json - Status: 200 - Duration: 0.004s
> [2026-09-14T01:22:43.101806] INFO in server: Incoming request: GET http://kb.willmo.dev/manifest.json from 192.168.0.33
> [2026-09-14T01:22:42.294444] INFO in h11_impl: 192.168.0.33:57536 - "GET /admin HTTP/1.1" 200
> [2026-09-14T01:22:42.291371] INFO in server: Completed request: GET http://kb.willmo.dev/admin - Status: 200 - Duration: 0.066s
> [2026-09-14T01:22:42.225765] INFO in server: Incoming request: GET http://kb.willmo.dev/admin from 192.168.0.33
> [2026-09-14T01:22:35.036333] INFO in h11_impl: 192.168.0.33:33344 - "POST /collections/view/1/sync HTTP/1.1" 404
> [2026-09-14T01:22:35.025603] INFO in server: Completed request: POST http://kb.willmo.dev/collections/view/1/sync - Status: 404 - Duration: 0.004s
> [2026-09-14T01:22:35.021755] INFO in server: Incoming request: POST http://kb.willmo.dev/collections/view/1/sync from 192.168.0.33
> ```
> 
> The API endpoint needs to **create** the collection in the server and then syn the data "

## Attached Screenshots
- User uploaded an image of modal dialog on `/collections/view/1`:
  - Title: "Sync Failed/Deferred"
  - Body: "undefined"
  - Button: "Close"

## Analysis & Requirements
1. **Missing Endpoint**:
   - `src/kb_web/templates/view_collection.j2.html` invokes `POST /collections/view/{{ collection.id }}/sync`.
   - FastAPI server currently only registered `@router.post("/collections/action/sync-qdrant")` with Form data, returning 404 for `POST /collections/view/{collection_id}/sync`.
2. **Frontend Error Handling**:
   - `view_collection.j2.html` blindly reads `data.message`. When FastAPI returns 404, `detail` is returned, causing `data.message` to be `undefined`.
   - Update error parsing in JavaScript to prioritize `data.message || data.detail || res.statusText`.
3. **Qdrant Collection Creation & Vector Synchronization**:
   - User specification: "It should also create a collection on the server if there is not a collection that exists with that name."
   - Both on the kb-web PostgreSQL server and on the Qdrant vector server:
     - If the collection does not exist in the database, automatically create it on the server.
     - If the collection does not exist in Qdrant, create it with `PUT /collections/{collection_name}` with Cosine distance and appropriate vector dimensions.
   - Synchronize chunk vector embeddings and item payloads to Qdrant.
   - Gracefully support unauthenticated Qdrant servers when `QDRANT_API_KEY` is empty/blank without failing.
