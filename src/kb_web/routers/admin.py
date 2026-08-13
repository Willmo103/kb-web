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
from .pages import background_video_downloader

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
            article_exists = False
            title_exists = False
            if "article_embeddings" in db.table_names():
                try:
                    db["article_embeddings"].get(url)
                    article_exists = True
                except Exception:
                    pass
            if "title_embeddings" in db.table_names():
                try:
                    db["title_embeddings"].get(url)
                    title_exists = True
                except Exception:
                    pass

            if not article_exists or not title_exists:
                update_article_embedding(db, url, config, client)


# --- Router Endpoints ---


import logging
logger = logging.getLogger("kb_web")


@router.get("/import", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
def get_import_url_page() -> HTMLResponse:
    """Serves the primary admin entry page where URL import strings can be submitted."""
    db = _get_db()
    collections = []
    if "collections" in db.table_names():
        collections = list(db["collections"].rows)
    template = _jinja_env.get_template("url_import.j2.html")
    return HTMLResponse(content=template.render(is_admin=True, collections=collections))


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

    db = _get_db()
    collections = []
    if "collections" in db.table_names():
        collections = list(db["collections"].rows)

    template = _jinja_env.get_template("url_import.j2.html")
    return HTMLResponse(
        content=template.render(prefilled_url=target_link, is_admin=True, collections=collections)
    )


@router.post("/import/url", dependencies=[Depends(verify_auth)], response_model=None)
def handle_url_import(
    request: Request,
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    collection_id: Optional[str] = Form(None),
    new_collection_title: Optional[str] = Form(None),
    download_video: Optional[str] = Form(None),
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

        from fastapi.concurrency import run_in_threadpool

        logger.info(f"Ingestion started for URL: {cleaned_url} (collection: {collection_id}, new title: {new_collection_title})")

        # Step 1: Fetch
        msg = f"Fetching content from URL: {cleaned_url}..."
        yield f"<script>updateProgress({json.dumps(msg)}, 20);</script>\n"
        try:
            page_data = await run_in_threadpool(fetch_url, cleaned_url)
            yield f"<script>addLog({json.dumps('Successfully fetched target URL content.')});</script>\n"
            logger.info(f"Ingestion fetch complete for: {cleaned_url}")
        except Exception as e:
            err_msg = f"Fetch failed: {str(e)}"
            yield f"<script>showError({json.dumps(err_msg)});</script>\n"
            logger.error(f"Ingestion fetch failed for: {cleaned_url} - Error: {str(e)}", exc_info=True)
            return

        # Check duplicate
        existing_rows = list(db["fetched_pages"].rows_where("url = ?", [cleaned_url]))
        if existing_rows:
            existing_row = existing_rows[0]
            if existing_row.get("md_content_hash") == page_data.md_content_hash:
                yield f"<script>addLog({json.dumps('URL already exists and content is identical. Skipping pipeline...')});</script>\n"
                
                target_col_id = None
                if collection_id == "new_collection" and new_collection_title:
                    from ..config import DEFAULT_RAG_SYSTEM_PROMPT, DEFAULT_TAXONOMY_SYSTEM_PROMPT
                    col_row = {
                        "title": new_collection_title,
                        "visibility": "public",
                        "rag_system_prompt": DEFAULT_RAG_SYSTEM_PROMPT,
                        "taxonomy_system_prompt": DEFAULT_TAXONOMY_SYSTEM_PROMPT,
                        "general_system_context": "{}",
                        "created_at": datetime.now().isoformat()
                    }
                    res = db["collections"].insert(col_row)
                    db.conn.commit()
                    target_col_id = res.last_pk
                    yield f"<script>addLog({json.dumps(f'Created new collection: {new_collection_title}')});</script>\n"
                elif collection_id:
                    try:
                        target_col_id = int(collection_id)
                    except ValueError:
                        pass
                
                if target_col_id:
                    existing_items = list(db["collection_items"].rows_where(
                        "collection_id = ? AND source_id = ?",
                        [target_col_id, cleaned_url]
                    ))
                    if not existing_items:
                        is_video = bool(extract_youtube_video_id(cleaned_url))
                        source_type = "videos" if is_video else "articles"
                        title_val = existing_row.get("title") or ""
                        db["collection_items"].insert({
                            "collection_id": target_col_id,
                            "source_type": source_type,
                            "source_id": cleaned_url,
                            "item_note": "",
                            "taxonomy_path": f"/uncategorized/{title_val[:20].replace(' ', '_')}.md" if title_val else f"/uncategorized/{target_col_id}.md",
                            "item_order": 0,
                            "added_at": datetime.now().isoformat()
                        })
                        db.conn.commit()
                        yield f"<script>addLog({json.dumps('Linked item to collection items.')});</script>\n"
                
                if download_video == "yes":
                    video_id = extract_youtube_video_id(cleaned_url)
                    if video_id:
                        yield f"<script>addLog({json.dumps('Spawning background task to download YouTube video...')});</script>\n"
                        background_tasks.add_task(
                            background_video_downloader,
                            video_id,
                            cleaned_url,
                            config
                        )
                
                base_url = str(request.base_url).rstrip("/")
                view_url = f"{base_url}/view/page?url={page_data.safe_url}"
                yield f"<script>updateProgress('Done!', 100); setTimeout(() => {{ window.location.href = '{view_url}'; }}, 1000);</script>\n"
                return
            else:
                yield f"<script>addLog({json.dumps('URL already exists but content has changed. Archiving current version to history...')});</script>\n"
                db["page_versions"].insert({
                    "url": existing_row["url"],
                    "title": existing_row.get("title"),
                    "html_content": existing_row.get("html_content"),
                    "md_content": existing_row.get("md_content"),
                    "links": existing_row.get("links"),
                    "html_content_hash": existing_row.get("html_content_hash"),
                    "md_content_hash": existing_row.get("md_content_hash"),
                    "fetched_at": existing_row.get("fetched_at"),
                    "description": existing_row.get("description"),
                    "keywords": existing_row.get("keywords"),
                    "tags": existing_row.get("tags"),
                })
                db.conn.commit()

        # Step 2: Rewrite Wiki
        yield f"<script>updateProgress({json.dumps('Running Ollama prompt extraction pipeline...')}, 55);</script>\n"
        try:
            wiki_entry = await run_in_threadpool(extract_wiki_content, page_data, config, client)
            page_data.description = wiki_entry
            yield f"<script>addLog({json.dumps('Ollama wiki entry generated successfully.')});</script>\n"
            logger.info(f"Ingestion wiki generated for: {cleaned_url}")
        except Exception as e:
            err_msg = f"Ollama wiki generation failed: {str(e)}"
            yield f"<script>showError({json.dumps(err_msg)});</script>\n"
            logger.error(f"Ingestion wiki generation failed for: {cleaned_url} - Error: {str(e)}", exc_info=True)
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
        yield f"<script>updateProgress({json.dumps('Extracting category tags via Ollama...')}, 75);</script>\n"
        try:
            tags = await run_in_threadpool(extract_tags_content, page_data, config, client)
            page_data.tags = tags
            log_msg = f"Tags extracted: {tags}"
            yield f"<script>addLog({json.dumps(log_msg)});</script>\n"
            logger.info(f"Ingestion tags extracted for: {cleaned_url} - Tags: {tags}")
        except Exception as e:
            err_msg = f"Failed to extract tags: {str(e)}"
            yield f"<script>addLog({json.dumps(err_msg)});</script>\n"
            logger.error(f"Ingestion tags extraction failed for: {cleaned_url} - Error: {str(e)}", exc_info=True)

        # Step 5: Embeddings & Database Ops
        yield "<script>updateProgress('Saving database records...', 90);</script>\n"
        try:
            from ..config import DEFAULT_RAG_SYSTEM_PROMPT, DEFAULT_TAXONOMY_SYSTEM_PROMPT

            target_col_id = None
            if collection_id == "new_collection" and new_collection_title:
                col_row = {
                    "title": new_collection_title,
                    "visibility": "public",
                    "rag_system_prompt": DEFAULT_RAG_SYSTEM_PROMPT,
                    "taxonomy_system_prompt": DEFAULT_TAXONOMY_SYSTEM_PROMPT,
                    "general_system_context": "{}",
                    "created_at": datetime.now().isoformat()
                }
                res = db["collections"].insert(col_row)
                db.conn.commit()
                target_col_id = res.last_pk
                yield f"<script>addLog({json.dumps(f'Created new collection: {new_collection_title}')});</script>\n"
                logger.info(f"Created new collection: {new_collection_title} (ID: {target_col_id}) during ingestion")
            elif collection_id:
                try:
                    target_col_id = int(collection_id)
                except ValueError:
                    pass

            base_url = str(request.base_url).rstrip("/")
            view_url = f"{base_url}/view/page?url={page_data.safe_url}"

            yield f"<script>addLog({json.dumps('Serializing page content...')});</script>\n"
            if target_col_id:
                page_data.collection_id = target_col_id

            serialized, creator = serialize_page_for_db(page_data)
            if target_col_id:
                serialized["collection_id"] = target_col_id
            
            yield f"<script>addLog({json.dumps('Upserting fetched_pages record...')});</script>\n"
            db["fetched_pages"].upsert(serialized, pk="url")
            db.conn.commit()
            yield f"<script>addLog({json.dumps('Committed fetched_pages record.')});</script>\n"
            logger.info(f"Upserted fetched_pages record for: {cleaned_url}")
            
            # Associate to collection_items if collection is chosen/created
            if target_col_id:
                try:
                    # check if already in collection_items
                    existing_items = list(db["collection_items"].rows_where(
                        "collection_id = ? AND source_id = ?",
                        [target_col_id, page_data.url]
                    ))
                    if not existing_items:
                        is_video = bool(extract_youtube_video_id(page_data.url))
                        source_type = "videos" if is_video else "articles"
                        
                        db["collection_items"].insert({
                            "collection_id": target_col_id,
                            "source_type": source_type,
                            "source_id": page_data.url,
                            "item_note": "",
                            "taxonomy_path": f"/uncategorized/{page_data.title[:20].replace(' ', '_')}.md" if page_data.title else f"/uncategorized/{target_col_id}.md",
                            "item_order": 0,
                            "added_at": datetime.now().isoformat()
                        })
                        db.conn.commit()
                        yield f"<script>addLog({json.dumps('Linked item to collection items.')});</script>\n"
                        logger.info(f"Linked page {cleaned_url} to collection {target_col_id}")
                except Exception as ci_err:
                    yield f"<script>addLog({json.dumps(f'Warning: failed to link to collection: {ci_err}')});</script>\n"
                    logger.error(f"Failed to link page {cleaned_url} to collection {target_col_id}: {str(ci_err)}", exc_info=True)
            
            if creator:
                yield f"<script>addLog({json.dumps(f'Saving YouTube metadata (creator: {creator})...')});</script>\n"
                await run_in_threadpool(save_youtube_metadata_helper, db, page_data.url, creator)
                db.conn.commit()
                logger.info(f"Saved YouTube metadata for video by creator: {creator}")
            
            yield f"<script>addLog({json.dumps('Generating default description embedding...')});</script>\n"
            await run_in_threadpool(update_article_embedding, db, page_data.url, config, client)
            db.conn.commit()
            
            yield f"<script>addLog({json.dumps('Generating chunk embeddings using embeddinggemma...')});</script>\n"
            await run_in_threadpool(generate_gemma_embeddings_for_page, db, page_data.url, config, client)
            db.conn.commit()
            logger.info(f"Generated embeddings for: {cleaned_url}")
            
            yield f"<script>addLog({json.dumps('Sending Gotify notification...')});</script>\n"
            await run_in_threadpool(post_to_gotify, config, _jinja_env, page_data, view_url)
            
            # Spawn video download if requested
            if download_video == "yes":
                video_id = extract_youtube_video_id(cleaned_url)
                if video_id:
                    yield f"<script>addLog({json.dumps('Spawning background task to download YouTube video...')});</script>\n"
                    background_tasks.add_task(
                        background_video_downloader,
                        video_id,
                        cleaned_url,
                        config
                    )

            yield f"<script>addLog({json.dumps('Successfully completed all database operations.')});</script>\n"
            yield f"<script>updateProgress('Done!', 100); setTimeout(() => {{ window.location.href = '{view_url}'; }}, 1000);</script>\n"
            logger.info(f"Ingestion fully completed successfully for: {cleaned_url}")
        except Exception as e:
            err_msg = f"Database sync/embedding failed: {str(e)}"
            import traceback
            print(f"Ingestion database sync failed: {e}\n{traceback.format_exc()}")
            yield f"<script>showError({json.dumps(err_msg)});</script>\n"
            logger.error(f"Ingestion database sync failed for: {cleaned_url} - Error: {str(e)}", exc_info=True)
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

    wiki_prompts_history = []
    youtube_prompts_history = []
    if "agent_prompts" in db.table_names():
        try:
            wiki_prompts_history = list(db["agent_prompts"].rows_where(
                "prompt_type = 'wiki_prompt' ORDER BY version DESC"
            ))
            youtube_prompts_history = list(db["agent_prompts"].rows_where(
                "prompt_type = 'youtube_wiki_prompt' ORDER BY version DESC"
            ))
        except Exception as e:
            print(f"Failed to fetch prompt history: {e}")

    cli_keys = []
    registered_clients = []
    if "cli_api_keys" in db.table_names():
        try:
            cli_keys = list(db["cli_api_keys"].rows_where("1=1 ORDER BY created_at DESC"))
        except Exception as e:
            print(f"Failed to fetch CLI keys: {e}")
    if "registered_clients" in db.table_names():
        try:
            registered_clients = list(db["registered_clients"].rows_where("1=1 ORDER BY registered_at DESC"))
        except Exception as e:
            print(f"Failed to fetch registered clients: {e}")

    template = _jinja_env.get_template("admin.j2.html")
    return HTMLResponse(
        content=template.render(
            unprocessed_count=count,
            completion_message=msg,
            config=config,
            is_admin=True,
            wiki_prompts_history=wiki_prompts_history,
            youtube_prompts_history=youtube_prompts_history,
            cli_keys=cli_keys,
            registered_clients=registered_clients,
        )
    )


@router.post("/admin/prompts/set-head", dependencies=[Depends(verify_auth)])
def set_prompt_head(
    prompt_id: int = Form(...),
    prompt_type: str = Form(...),
) -> RedirectResponse:
    """Sets a specific historical version of a system prompt as the current active HEAD prompt."""
    db = _get_db()
    try:
        # 1. Update is_head = 0 for all prompts of this type
        db.execute("UPDATE agent_prompts SET is_head = 0 WHERE prompt_type = ?", [prompt_type])
        
        # 2. Update is_head = 1 for the target prompt id
        db.execute("UPDATE agent_prompts SET is_head = 1 WHERE id = ?", [prompt_id])
        db.conn.commit()
        
        # 3. Retrieve the prompt text and sync with the active Config attributes
        row = db["agent_prompts"].get(prompt_id)
        if row:
            if prompt_type == "wiki_prompt":
                config._wiki_prompt = row["prompt_text"]
            elif prompt_type == "youtube_wiki_prompt":
                config._youtube_wiki_prompt = row["prompt_text"]
            config.save()
            
        return RedirectResponse(
            url="/admin?msg=Selected+prompt+version+successfully+restored+as+active+HEAD.",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin?msg=Error+restoring+prompt+version:+{quote_plus(str(e))}",
            status_code=303,
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
    ollama_think: bool = Form(False),
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
    config.ollama_think = ollama_think
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
def get_logs_view(
    request: Request,
    limit: Optional[int] = Query(None, ge=1, le=10000)
) -> HTMLResponse:
    """Renders the tail end of the application server database logs (most recent first)."""
    if limit is None:
        cookie_limit = request.cookies.get("log_limit")
        if cookie_limit:
            try:
                limit = int(cookie_limit)
            except ValueError:
                limit = 100
        else:
            limit = 100

    db = _get_db()
    log_content = ""
    try:
        if "system_logs" in db.table_names():
            rows = list(db.execute_returning_dicts(
                "SELECT * FROM system_logs ORDER BY rowid DESC LIMIT ?", [limit]
            ))
            
            lines = []
            for r in rows:
                ts = r.get("timestamp", "")
                lvl = r.get("level", "INFO")
                mod = r.get("module", "root")
                msg = r.get("message", "")
                tb = r.get("traceback", "")
                
                line = f"[{ts}] {lvl} in {mod}: {msg}"
                if tb:
                    line += f"\n{tb}"
                lines.append(line)
            log_content = "\n".join(lines)
        else:
            log_content = "No logs recorded in database yet."
    except Exception as e:
        log_content = f"Error reading logs from database: {e}"

    template = _jinja_env.get_template("logs.j2.html")
    response = HTMLResponse(content=template.render(log_content=log_content, is_admin=True, limit=limit))
    response.set_cookie("log_limit", str(limit), max_age=31536000, path="/")
    return response


@router.get("/admin/logs/download", dependencies=[Depends(verify_auth)])
def download_logs(
    request: Request,
    limit: Optional[int] = Query(None, ge=1, le=10000)
) -> StreamingResponse:
    """Streams the database logs as a downloadable text file (most recent first)."""
    if limit is None:
        cookie_limit = request.cookies.get("log_limit")
        if cookie_limit:
            try:
                limit = int(cookie_limit)
            except ValueError:
                limit = 100
        else:
            limit = 100
    
    def generate_logs():
        db = _get_db()
        try:
            if "system_logs" in db.table_names():
                rows = list(db.execute_returning_dicts(
                    "SELECT * FROM system_logs ORDER BY rowid DESC LIMIT ?", [limit]
                ))
                for r in rows:
                    ts = r.get("timestamp", "")
                    lvl = r.get("level", "INFO")
                    mod = r.get("module", "root")
                    msg = r.get("message", "")
                    tb = r.get("traceback", "")
                    
                    line = f"[{ts}] {lvl} in {mod}: {msg}\n"
                    if tb:
                        line += f"{tb}\n"
                    yield line
            else:
                yield "No logs recorded in database yet."
        except Exception as e:
            yield f"Error reading logs from database: {e}"

    return StreamingResponse(
        generate_logs(),
        media_type="text/plain",
        headers={
            "Content-Disposition": f"attachment; filename=kb_web_logs_{limit}.txt"
        },
    )


@router.post("/admin/cli/keys/create", dependencies=[Depends(verify_auth)])
def admin_create_cli_key(name: str = Form(...)) -> RedirectResponse:
    import uuid
    db = _get_db()
    new_key = str(uuid.uuid4()).replace("-", "")
    try:
        db["cli_api_keys"].insert({
            "key": new_key,
            "name": name,
            "created_at": datetime.now().isoformat()
        }, pk="key")
        db.conn.commit()
        return RedirectResponse(url="/admin?msg=New+CLI+API+Key+generated.", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/admin?msg=Error+generating+key:+{str(e)}", status_code=303)


@router.post("/admin/cli/keys/delete", dependencies=[Depends(verify_auth)])
def admin_delete_cli_key(key: str = Form(...)) -> RedirectResponse:
    db = _get_db()
    try:
        db["cli_api_keys"].delete_where("key = ?", [key])
        db.conn.commit()
        return RedirectResponse(url="/admin?msg=CLI+API+Key+revoked.", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/admin?msg=Error+revoking+key:+{str(e)}", status_code=303)


@router.post("/admin/cli/clients/delete", dependencies=[Depends(verify_auth)])
def admin_delete_cli_client(computer_name: str = Form(...)) -> RedirectResponse:
    db = _get_db()
    try:
        db["registered_clients"].delete_where("computer_name = ?", [computer_name])
        db.conn.commit()
        return RedirectResponse(url="/admin?msg=Registered+CLI+client+removed.", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/admin?msg=Error+removing+client:+{str(e)}", status_code=303)


