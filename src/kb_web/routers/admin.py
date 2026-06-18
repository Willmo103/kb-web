"""
FastAPI Router for administrative controls, configuration updates, and maintenance triggers.
"""

import json
from datetime import datetime
from typing import AsyncGenerator, Optional
from urllib.parse import unquote_plus, quote_plus, urlparse
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from ..base import (
    config,
    _jinja_env,
    _get_db,
    _get_ollama_client,
    COOKIE_NAME,
    verify_session_token,
    verify_auth,
)
from ..models import HTMLPage
from ..utils import (
    fetch_url,
    extract_first_url,
    extract_wiki_content,
    extract_tags_content,
    save_youtube_metadata_helper,
    update_article_embedding,
    serialize_page_for_db,
    extract_youtube_video_id,
    generate_gemma_embeddings_for_page,
)
from ..gotify import post_to_gotify

from bs4 import BeautifulSoup  # type: ignore

router = APIRouter()


# --- Background Tasks Routine ---


def run_bulk_description_maintenance() -> None:
    """Loops through historical page captures, prompting Ollama to rewrite pages lacking proper descriptions."""
    db = _get_db()
    if "fetched_pages" in db.table_names():
        rows = list(db.execute_returning_dicts("SELECT * FROM fetched_pages"))
        client = _get_ollama_client()
        for row in rows:
            desc = row.get("description", "")
            if not desc or "AI Processing skipped" in desc:
                try:
                    page_obj = HTMLPage(**row)
                    print(f"Running maintenance extraction for: {page_obj.url}")
                    wiki_text = extract_wiki_content(page_obj, config, client)
                    db["fetched_pages"].update(page_obj.url, {"description": wiki_text})
                except Exception as e:
                    print(f"Failed background processing for {row.get('url')}: {e}")
                    continue


def run_bulk_embedding_maintenance() -> None:
    """Loops through all fetched pages, generating embeddings for any that are missing."""
    db = _get_db()
    if "fetched_pages" in db.table_names():
        rows = list(db.execute_returning_dicts("SELECT url FROM fetched_pages"))
        client = _get_ollama_client()
        for row in rows:
            url = row["url"]
            exists = False
            if "article_embeddings" in db.table_names():
                try:
                    db["article_embeddings"].get(url)
                    exists = True
                except Exception:
                    pass

            if not exists:
                update_article_embedding(db, url, config, client)


# --- Router Endpoints ---


@router.get("/import", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
def get_import_url_page() -> HTMLResponse:
    """Serves the primary admin entry page where URL import strings can be submitted."""
    template = _jinja_env.get_template("url_import.j2.html")
    return HTMLResponse(content=template.render(is_admin=True))


@router.get("/import/shared-url", dependencies=[Depends(verify_auth)], response_model=None)
def handle_incoming_mobile_share(
    request: Request,
    url: Optional[str] = Query(None),
    text: Optional[str] = Query(None),
) -> RedirectResponse | HTMLResponse:
    """Filters incoming share targets from mobile actions and displays a prefilled import form."""
    target_link = url or text
    if not target_link:
        return RedirectResponse(url="/import")

    target_link = extract_first_url(target_link)

    template = _jinja_env.get_template("url_import.j2.html")
    return HTMLResponse(
        content=template.render(prefilled_url=target_link, is_admin=True)
    )


@router.post("/import/url", dependencies=[Depends(verify_auth)], response_model=None)
def handle_url_import(
    request: Request, url: str = Form(...)
) -> StreamingResponse:
    """Processes URL ingestion, downloads content, rewrites with LLM, and logs to database."""
    cleaned_url = extract_first_url(url)

    async def stream_ingestion():
        # Yield the initial HTML layout of the progress page
        yield """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ingestion Pipeline Progress</title>
    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Outfit', sans-serif; background-color: #F4EFEA; }
    </style>
</head>
<body class="text-gray-850 min-h-screen antialiased flex flex-col justify-center items-center">
    <div class="w-full max-w-xl bg-white p-8 rounded-xl border border-gray-200 shadow-lg mx-4">
        <div class="flex items-center gap-3 mb-4">
            <span class="text-2xl animate-spin">🔄</span>
            <h1 class="text-xl font-bold text-gray-900">Ingestion Pipeline In Progress</h1>
        </div>
        <p class="text-sm text-gray-500 mb-6" id="status-text">Initializing pipeline...</p>
        
        <div class="w-full bg-gray-200 rounded-full h-3.5 mb-6 overflow-hidden">
            <div id="progress-bar" class="bg-indigo-650 h-3.5 rounded-full transition-all duration-300" style="width: 5%"></div>
        </div>
        
        <div class="bg-gray-950 text-gray-200 font-mono text-xs p-4 rounded-lg h-48 overflow-y-auto space-y-1 border border-gray-800" id="terminal-logs">
            <div class="text-gray-500">[SYSTEM] Initializing pipeline...</div>
        </div>
    </div>
    
    <script>
        const progressBar = document.getElementById('progress-bar');
        const statusText = document.getElementById('status-text');
        const terminalLogs = document.getElementById('terminal-logs');
        
        function updateProgress(message, percentage) {
            statusText.innerText = message;
            progressBar.style.width = percentage + '%';
            addLog(message);
        }
        
        function addLog(text) {
            const div = document.createElement('div');
            div.innerText = "[" + new Date().toLocaleTimeString() + "] " + text;
            terminalLogs.appendChild(div);
            terminalLogs.scrollTop = terminalLogs.scrollHeight;
        }
        
        function showError(message) {
            statusText.innerText = "Error: " + message;
            statusText.className = "text-sm text-red-600 font-bold mb-6";
            progressBar.className = "bg-red-500 h-3.5 rounded-full";
            const btn = document.createElement('button');
            btn.className = "mt-4 w-full bg-gray-200 hover:bg-gray-300 text-gray-800 text-xs font-bold py-2.5 px-4 rounded transition shadow-sm";
            btn.innerText = "Back to Importer";
            btn.onclick = () => window.location.href = "/import";
            document.querySelector('.w-full.max-w-xl').appendChild(btn);
            addLog("ERROR: " + message);
        }
    </script>
"""

        db = _get_db()
        client = _get_ollama_client()

        # Step 1: Fetch
        msg = f"Fetching content from URL: {cleaned_url}..."
        yield f"<script>updateProgress({json.dumps(msg)}, 20);</script>\n"
        try:
            page_data = fetch_url(cleaned_url)
            yield "<script>addLog('Successfully fetched target URL content.');</script>\n"
        except Exception as e:
            err_msg = f"Fetch failed: {str(e)}"
            yield f"<script>showError({json.dumps(err_msg)});</script>\n"
            return

        # Step 2: Rewrite Wiki
        yield "<script>updateProgress('Running Ollama prompt extraction pipeline...', 55);</script>\n"
        try:
            wiki_entry = extract_wiki_content(page_data, config, client)
            page_data.description = wiki_entry
            yield "<script>addLog('Ollama wiki entry generated successfully.');</script>\n"
        except Exception as e:
            err_msg = f"Ollama wiki generation failed: {str(e)}"
            yield f"<script>showError({json.dumps(err_msg)});</script>\n"
            return

        # Step 3: Extract Title
        title = cleaned_url
        soup = BeautifulSoup(page_data.html_content, "html5lib")
        if soup.title:
            title = soup.title.string
        if not title:
            title = urlparse(cleaned_url).netloc or cleaned_url

        if wiki_entry.strip().startswith("#"):
            first_line = wiki_entry.strip().split("\n")[0]
            title = first_line.replace("#", "").strip()
        page_data.title = title

        # Step 4: Extract Tags
        yield "<script>updateProgress('Extracting category tags via Ollama...', 75);</script>\n"
        try:
            tags = extract_tags_content(page_data, config, client)
            page_data.tags = tags
            log_msg = f"Tags extracted: {tags}"
            yield f"<script>addLog({json.dumps(log_msg)});</script>\n"
        except Exception as e:
            err_msg = f"Failed to extract tags: {str(e)}"
            yield f"<script>addLog({json.dumps(err_msg)});</script>\n"

        # Step 5: Embeddings & Database Ops
        yield "<script>updateProgress('Generating embeddings and committing database changes...', 90);</script>\n"
        try:
            base_url = str(request.base_url).rstrip("/")
            view_url = f"{base_url}/view/page?url={page_data.safe_url}"

            serialized, creator = serialize_page_for_db(page_data)
            db["fetched_pages"].upsert(serialized, pk="url")
            save_youtube_metadata_helper(db, page_data.url, creator)
            
            # Generate default description embedding
            update_article_embedding(db, page_data.url, config, client)
            
            # Generate new embeddinggemma chunk embeddings and description embedding
            generate_gemma_embeddings_for_page(db, page_data.url, config, client)
            db.conn.commit()
            
            # Post to Gotify
            post_to_gotify(config, _jinja_env, page_data, view_url)
            
            yield "<script>addLog('Successfully updated database records and embeddings.');</script>\n"
            yield f"<script>updateProgress('Done!', 100); setTimeout(() => {{ window.location.href = '{view_url}'; }}, 1000);</script>\n"
        except Exception as e:
            err_msg = f"Database sync/embedding failed: {str(e)}"
            yield f"<script>showError({json.dumps(err_msg)});</script>\n"
            return
            
    return StreamingResponse(
        stream_ingestion(),
        media_type="text/html",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


@router.get("/admin", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
def get_admin_dashboard(msg: Optional[str] = Query(None)) -> HTMLResponse:
    """Serves the admin page containing DB backups, imports, and maintenance triggers."""
    db = _get_db()
    count = 0
    if "fetched_pages" in db.table_names():
        count = sum(
            1
            for r in db["fetched_pages"].rows
            if not r.get("description")
            or "AI Processing skipped" in r.get("description", "")
        )

    template = _jinja_env.get_template("admin.j2.html")
    return HTMLResponse(
        content=template.render(
            unprocessed_count=count,
            completion_message=msg,
            config=config,
            is_admin=True,
        )
    )


@router.post("/admin/config", dependencies=[Depends(verify_auth)], response_model=None)
def handle_config_update(
    ollama_host: str = Form(...),
    ollama_model: str = Form(...),
    ollama_embedding_model: str = Form(...),
    api_key: str = Form(None),
    gotify_url: str = Form(None),
    gotify_token: str = Form(None),
    qdrant_host_url: str = Form(None),
    qdrant_api_key: str = Form(None),
    wiki_prompt: str = Form(...),
    youtube_wiki_prompt: str = Form(...),
    max_input_length: int = Form(20000),
) -> RedirectResponse:
    """Saves updated server settings (Ollama, Gotify, and Qdrant parameters) to config file."""
    config.ollama_host = ollama_host
    config.ollama_model = ollama_model
    config.ollama_embedding_model = ollama_embedding_model
    config.api_key = api_key
    config.gotify_url = gotify_url or None
    config.gotify_token = gotify_token or None
    config.qdrant_host_url = qdrant_host_url or None
    config.qdrant_api_key = qdrant_api_key or None
    config.wiki_prompt = wiki_prompt
    config.youtube_wiki_prompt = youtube_wiki_prompt
    config.max_input_length = max_input_length
    config.save()

    return RedirectResponse(
        url="/admin?msg=Configurations+successfully+saved+and+reloaded.",
        status_code=303,
    )


@router.post("/admin/test-gotify", dependencies=[Depends(verify_auth)])
def test_gotify(
    gotify_url: Optional[str] = Form(None),
    gotify_token: Optional[str] = Form(None),
) -> dict:
    """Sends a test notification to verify Gotify settings without saving them."""
    if not gotify_url or not gotify_token:
        return {
            "status": "error",
            "message": "Both Gotify Server URL and App Token are required.",
        }
    try:
        from kb_core.notifier import Gotify

        notifier = Gotify(token=gotify_token, url=gotify_url)
        notifier.send_notification(
            "Gotify Connection Test",
            "This is a test notification from the Knowledge Base Web Importer.",
        )
        return {"status": "success", "message": "Test notification sent successfully."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to send notification: {str(e)}"}


@router.post("/admin/test-ollama", dependencies=[Depends(verify_auth)])
def test_ollama(
    ollama_host: Optional[str] = Form(None),
    ollama_model: Optional[str] = Form(None),
) -> dict:
    """Tests connection to Ollama server and checks available models."""
    if not ollama_host or not ollama_model:
        return {
            "status": "error",
            "message": "Both Ollama Host URL and Model are required.",
        }
    try:
        import ollama as ollama_lib

        client = ollama_lib.Client(host=ollama_host)
        models_response = client.list()
        model_names = []
        if isinstance(models_response, dict):
            models_list = models_response.get("models", [])
            for m in models_list:
                if isinstance(m, dict):
                    model_names.append(m.get("name", ""))
                else:
                    model_names.append(str(m))
        elif hasattr(models_response, "models"):
            for m in models_response.models:
                if hasattr(m, "model"):
                    model_names.append(m.model)
                elif hasattr(m, "name"):
                    model_names.append(m.name)
                else:
                    model_names.append(str(m))
        else:
            model_names = [str(m) for m in models_response]

        return {
            "status": "success",
            "message": f"Successfully connected to Ollama server. Available models: {', '.join(model_names[:5])}",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to connect to Ollama server: {str(e)}",
        }


@router.post(
    "/admin/regenerate/wiki", dependencies=[Depends(verify_auth)], response_model=None
)
def handle_regenerate_wiki(url: str = Query(...)) -> RedirectResponse:
    """Triggers the Ollama wiki page re-generation process for a page."""
    db = _get_db()
    decoded_url = unquote_plus(url)
    try:
        row = db["fetched_pages"].get(decoded_url)
        page_obj = HTMLPage(**row)
    except Exception:
        raise HTTPException(status_code=404, detail="Ingested page profile missing.")

    client = _get_ollama_client()
    wiki_entry = extract_wiki_content(page_obj, config, client)

    title = page_obj.title or page_obj.url
    if wiki_entry.strip().startswith("#"):
        first_line = wiki_entry.strip().split("\n")[0]
        title = first_line.replace("#", "").strip()

    db["fetched_pages"].update(decoded_url, {"description": wiki_entry, "title": title})
    update_article_embedding(db, decoded_url, config, client)
    return RedirectResponse(
        url=f"/view/page?url={quote_plus(decoded_url)}", status_code=303
    )


@router.post(
    "/admin/regenerate/youtube-metadata", dependencies=[Depends(verify_auth)], response_model=None
)
def handle_regenerate_youtube_metadata(url: str = Query(...)) -> RedirectResponse:
    """Triggers re-fetching and updating YouTube video metadata for a page."""
    db = _get_db()
    decoded_url = unquote_plus(url)
    video_id = extract_youtube_video_id(decoded_url)
    if not video_id:
        return RedirectResponse(
            url=f"/view/page?url={quote_plus(decoded_url)}&error=Not+a+valid+YouTube+video+URL.",
            status_code=303,
        )

    try:
        save_youtube_metadata_helper(db, decoded_url, force_fetch=True)
    except Exception as e:
        return RedirectResponse(
            url=f"/view/page?url={quote_plus(decoded_url)}&error=Failed+to+regenerate+video+metadata:+{quote_plus(str(e))}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/view/page?url={quote_plus(decoded_url)}&msg=YouTube+metadata+successfully+regenerated.",
        status_code=303,
    )


@router.post(
    "/admin/regenerate/tags", dependencies=[Depends(verify_auth)], response_model=None
)
def handle_regenerate_tags(url: str = Query(...)) -> RedirectResponse:
    """Triggers the Ollama tags extraction routine for a page."""
    db = _get_db()
    decoded_url = unquote_plus(url)
    try:
        row = db["fetched_pages"].get(decoded_url)
        page_obj = HTMLPage(**row)
    except Exception:
        raise HTTPException(status_code=404, detail="Ingested page profile missing.")

    client = _get_ollama_client()
    tags = extract_tags_content(page_obj, config, client)
    db["fetched_pages"].update(decoded_url, {"tags": json.dumps(tags)})
    update_article_embedding(db, decoded_url, config, client)
    return RedirectResponse(
        url=f"/view/page?url={quote_plus(decoded_url)}", status_code=303
    )


@router.post(
    "/admin/update/tags", dependencies=[Depends(verify_auth)], response_model=None
)
def handle_update_tags(
    url: str = Form(...), tags_csv: str = Form(...)
) -> RedirectResponse:
    """Receives manually configured tags list from UI form and logs to database."""
    db = _get_db()
    client = _get_ollama_client()
    tags = [t.strip().lower() for t in tags_csv.split(",") if t.strip()]
    db["fetched_pages"].update(url, {"tags": json.dumps(tags)})
    update_article_embedding(db, url, config, client)
    return RedirectResponse(url=f"/view/page?url={quote_plus(url)}", status_code=303)


@router.post(
    "/admin/refetch/page", dependencies=[Depends(verify_auth)], response_model=None
)
def handle_refetch_page(
    request: Request,
    url: str = Query(...),
) -> RedirectResponse:
    """Re-fetches the page URL. If successful, archives the current version and updates."""
    db = _get_db()
    decoded_url = unquote_plus(url)
    try:
        page_data = fetch_url(decoded_url)
    except Exception as e:
        print(f"Administrative Refetch Failure: {e}")
        return RedirectResponse(
            url=f"/view/page?url={quote_plus(decoded_url)}&error=Failed+to+re-fetch+source+page:+{quote_plus(str(e))}",
            status_code=303,
        )

    # Archive the old page data into page_versions if it existed
    try:
        current_row = db["fetched_pages"].get(decoded_url)
        db["page_versions"].insert(
            {
                "url": current_row["url"],
                "title": current_row.get("title"),
                "html_content": current_row.get("html_content"),
                "md_content": current_row.get("md_content"),
                "links": current_row.get("links"),
                "html_content_hash": current_row.get("html_content_hash"),
                "md_content_hash": current_row.get("md_content_hash"),
                "fetched_at": current_row.get("fetched_at"),
                "description": current_row.get("description"),
                "keywords": current_row.get("keywords"),
                "tags": current_row.get("tags"),
            }
        )
    except Exception as exc:
        print(f"Failed to archive version: {exc}")

    client = _get_ollama_client()
    wiki_entry = extract_wiki_content(page_data, config, client)
    page_data.description = wiki_entry

    title = decoded_url
    soup = BeautifulSoup(page_data.html_content, "html5lib")
    if soup.title:
        title = soup.title.string
    if not title:
        title = urlparse(decoded_url).netloc or decoded_url

    if wiki_entry.strip().startswith("#"):
        first_line = wiki_entry.strip().split("\n")[0]
        title = first_line.replace("#", "").strip()

    page_data.title = title
    tags = extract_tags_content(page_data, config, client)
    page_data.tags = tags

    # Retain collection_id on refetch if it was set
    try:
        current_row = db["fetched_pages"].get(decoded_url)
        page_data.collection_id = current_row.get("collection_id")
    except Exception:
        pass

    serialized, creator = serialize_page_for_db(page_data)
    db["fetched_pages"].upsert(serialized, pk="url")
    save_youtube_metadata_helper(db, decoded_url, creator)
    update_article_embedding(db, decoded_url, config, client)

    base_url = str(request.base_url).rstrip("/")
    view_url = f"{base_url}/view/page?url={page_data.safe_url}"
    post_to_gotify(config, _jinja_env, page_data, view_url)

    return RedirectResponse(
        url=f"/view/page?url={quote_plus(decoded_url)}&msg=Source+page+successfully+re-fetched+and+new+version+created.",
        status_code=303,
    )


@router.post(
    "/admin/delete/page", dependencies=[Depends(verify_auth)], response_model=None
)
def handle_delete_page(url: str = Form(...)) -> RedirectResponse:
    """Deletes an ingested page profile and all its archived versions from the database."""
    db = _get_db()
    try:
        db["fetched_pages"].delete(url)
        if "page_versions" in db.table_names():
            db.execute("DELETE FROM page_versions WHERE url = ?", [url])
        if "article_embeddings" in db.table_names():
            db.execute("DELETE FROM article_embeddings WHERE url = ?", [url])
        print(f"Administrative Delete: Removed {url} and all archived versions from database.")
    except Exception:
        raise HTTPException(status_code=404, detail="Target page profile not found.")
    return RedirectResponse(url="/", status_code=303)


@router.post("/admin/trigger-describe", dependencies=[Depends(verify_auth)])
def trigger_bulk_description(background_tasks: BackgroundTasks) -> RedirectResponse:
    """Initiates an asynchronous background job processing pages missing LLM descriptions."""
    background_tasks.add_task(run_bulk_description_maintenance)
    return RedirectResponse(
        url="/admin?msg=Background+AI+maintenance+processing+loop+successfully+initiated.",
        status_code=303,
    )


@router.post("/admin/trigger-embeddings", dependencies=[Depends(verify_auth)])
def trigger_bulk_embeddings(background_tasks: BackgroundTasks) -> RedirectResponse:
    """Initiates an asynchronous background job generating missing article embeddings."""
    background_tasks.add_task(run_bulk_embedding_maintenance)
    return RedirectResponse(
        url="/admin?msg=Background+embedding+generation+loop+successfully+initiated.",
        status_code=303,
    )


@router.get("/admin/export", dependencies=[Depends(verify_auth)], response_model=None)
async def export_database() -> StreamingResponse:
    """Generates and streams out database contents as a downloadable JSON file."""
    db = _get_db()

    async def generate_json() -> AsyncGenerator[str, None]:
        yield "{\n"
        tables = db.table_names()
        for idx, table_name in enumerate(tables):
            yield f"  {json.dumps(table_name)}: [\n"
            rows = list(db[table_name].rows)
            first_row = True
            for row in rows:
                if not first_row:
                    yield ",\n"
                
                # Preprocess row values to serialize raw bytes to hex strings
                clean_row = {}
                for k, v in row.items():
                    if isinstance(v, bytes):
                        try:
                            # Try to decode as UTF-8 string first (text columns)
                            clean_row[k] = v.decode("utf-8")
                        except UnicodeDecodeError:
                            # Fallback to hex string representation with prefix
                            clean_row[k] = f"hex:{v.hex()}"
                    else:
                        clean_row[k] = v
                
                yield "    " + json.dumps(clean_row)
                first_row = False
            yield "\n  ]"
            if idx < len(tables) - 1:
                yield ",\n"
        yield "\n}"

    return StreamingResponse(
        generate_json(),
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=kb_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        },
    )


@router.websocket("/admin/ws/import")
async def websocket_import(websocket: WebSocket) -> None:
    """Accepts chunks of JSON file imports over a WebSocket connection."""
    await websocket.accept()

    token = websocket.cookies.get(COOKIE_NAME)
    is_valid = bool(token and verify_session_token(token))

    if not is_valid:
        await websocket.send_text("AUTH_FAILED")
        await websocket.close(code=1008)
        return

    try:
        data_chunks = []
        while True:
            chunk = await websocket.receive_text()
            if chunk == "EOF":
                break
            data_chunks.append(chunk)

        full_json = "".join(data_chunks)
        data = json.loads(full_json)

        db = _get_db()
        success_count = 0

        # Initialize schema tables to be safe
        from ..db import init_db
        init_db(db)

        if isinstance(data, dict):
            # Full database multi-table backup
            for table_name, raw_rows in data.items():
                if raw_rows:
                    # Clean rows to convert hex strings back to bytes
                    cleaned_rows = []
                    for r in raw_rows:
                        clean_r = {}
                        for k, v in r.items():
                            if isinstance(v, str) and v.startswith("hex:"):
                                try:
                                    clean_r[k] = bytes.fromhex(v[4:])
                                except ValueError:
                                    clean_r[k] = v
                            else:
                                clean_r[k] = v
                        cleaned_rows.append(clean_r)
                        
                    try:
                        pk = db[table_name].pks
                        if not pk:
                            db[table_name].insert_all(cleaned_rows)
                        else:
                            db[table_name].insert_all(cleaned_rows, pk=pk, replace=True)
                        success_count += len(cleaned_rows)
                    except Exception as e:
                        print(f"WS Import: Failed to restore table {table_name}: {e}")
                        # Fallback row-by-row
                        for cr in cleaned_rows:
                            try:
                                db[table_name].insert(cr, replace=True)
                                success_count += 1
                            except Exception as err:
                                print(f"WS Import Row Error in {table_name}: {err}")
            msg = f"SUCCESS: Restored database. Imported {success_count} total records across tables."
        elif isinstance(data, list):
            # Legacy fetched_pages list format
            for record in data:
                try:
                    page_obj = HTMLPage(**record)
                    serialized, creator = serialize_page_for_db(page_obj)
                    db["fetched_pages"].upsert(serialized, pk="url")
                    if creator:
                        save_youtube_metadata_helper(db, page_obj.url, creator)
                    success_count += 1
                except Exception as e:
                    print(f"Skipping record {record.get('url')} due to validation error: {e}")
            msg = f"SUCCESS: Imported {success_count} legacy records into fetched_pages."
        else:
            msg = "ERROR: Unsupported import file format."

        await websocket.send_text(msg)
        await websocket.close()

    except WebSocketDisconnect:
        print("Client disconnected during upload.")
    except Exception as e:
        try:
            await websocket.send_text(f"ERROR: {str(e)}")
            await websocket.close(code=1011)
        except Exception:
            pass


@router.get("/admin/logs", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
def get_logs_view(limit: int = Query(1000, ge=1, le=10000)) -> HTMLResponse:
    """Renders the tail end of the application server log file."""
    log_file = config.configs_dir.parent / "logs" / "kb-web.log"
    log_content = ""
    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                log_content = "".join(lines[-limit:])
        except Exception as e:
            log_content = f"Error reading logs: {e}"
    else:
        log_content = "Log file does not exist yet."

    template = _jinja_env.get_template("logs.j2.html")
    return HTMLResponse(content=template.render(log_content=log_content, is_admin=True, limit=limit))


@router.get("/admin/logs/download", dependencies=[Depends(verify_auth)])
def download_logs(limit: int = Query(1000, ge=1, le=10000)) -> StreamingResponse:
    """Streams the log file contents as a downloadable text file."""
    log_file = config.configs_dir.parent / "logs" / "kb-web.log"
    
    def generate_logs():
        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    selected_lines = lines[-limit:]
                    for line in selected_lines:
                        yield line
            except Exception as e:
                yield f"Error reading logs: {e}"
        else:
            yield "Log file does not exist yet."

    return StreamingResponse(
        generate_logs(),
        media_type="text/plain",
        headers={
            "Content-Disposition": f"attachment; filename=kb_web_logs_{limit}.txt"
        },
    )

