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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

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
) -> HTMLResponse | RedirectResponse:
    """Processes URL ingestion, downloads content, rewrites with LLM, and logs to database."""
    db = _get_db()
    url = extract_first_url(url)
    try:
        page_data = fetch_url(url)
    except RuntimeError as e:
        return HTMLResponse(
            content=_jinja_env.get_template("url_import.j2.html").render(
                error_message=str(e), prefilled_url=url, is_admin=True
            )
        )

    client = _get_ollama_client()
    wiki_entry = extract_wiki_content(page_data, config, client)
    page_data.description = wiki_entry

    title = url
    soup = BeautifulSoup(page_data.html_content, "html5lib")
    if soup.title:
        title = soup.title.string
    if not title:
        title = urlparse(url).netloc or url

    if wiki_entry.strip().startswith("#"):
        first_line = wiki_entry.strip().split("\n")[0]
        title = first_line.replace("#", "").strip()

    page_data.title = title
    tags = extract_tags_content(page_data, config, client)
    page_data.tags = tags

    base_url = str(request.base_url).rstrip("/")
    view_url = f"{base_url}/view/page?url={page_data.safe_url}"

    serialized, creator = serialize_page_for_db(page_data)
    db["fetched_pages"].upsert(serialized, pk="url")
    save_youtube_metadata_helper(db, page_data.url, creator)
    update_article_embedding(db, page_data.url, config, client)
    post_to_gotify(config, _jinja_env, page_data, view_url)
    return RedirectResponse(url=view_url, status_code=303)


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
    wiki_prompt: str = Form(...),
    youtube_wiki_prompt: str = Form(...),
    max_input_length: int = Form(20000),
) -> RedirectResponse:
    """Saves updated server settings (Ollama and Gotify parameters) to config file."""
    config.ollama_host = ollama_host
    config.ollama_model = ollama_model
    config.ollama_embedding_model = ollama_embedding_model
    config.api_key = api_key
    config.gotify_url = gotify_url or None
    config.gotify_token = gotify_token or None
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
async def export_database() -> JSONResponse | StreamingResponse:
    """Generates and streams out database contents as a downloadable JSON file."""
    db = _get_db()
    if "fetched_pages" not in db.table_names():
        return JSONResponse(content=[], status_code=200)

    async def generate_json() -> AsyncGenerator[str, None]:
        yield "[\n"
        first = True
        for row in db.execute_returning_dicts("SELECT * FROM fetched_pages"):
            if not first:
                yield ",\n"
            yield json.dumps(row)
            first = False
        yield "\n]"

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
        records = json.loads(full_json)

        db = _get_db()
        success_count = 0
        for record in records:
            try:
                page_obj = HTMLPage(**record)
                serialized, creator = serialize_page_for_db(page_obj)
                db["fetched_pages"].upsert(serialized, pk="url")
                if creator:
                    save_youtube_metadata_helper(db, page_obj.url, creator)
                success_count += 1
            except Exception as e:
                print(f"Skipping record {record.get('url')} due to validation error: {e}")

        await websocket.send_text(
            f"SUCCESS: Imported {success_count} records into the Knowledge Base."
        )
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
def get_logs_view() -> HTMLResponse:
    """Renders the tail end of the application server log file."""
    log_file = config.configs_dir.parent / "logs" / "kb-web.log"
    log_content = ""
    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                log_content = "".join(lines[-200:])
        except Exception as e:
            log_content = f"Error reading logs: {e}"
    else:
        log_content = "Log file does not exist yet."

    template = _jinja_env.get_template("logs.j2.html")
    return HTMLResponse(content=template.render(log_content=log_content, is_admin=True))

