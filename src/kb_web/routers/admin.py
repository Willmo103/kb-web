"""
FastAPI Router for administrative controls, configuration updates, and maintenance triggers.
"""

import os
import json
import logging
import time
from datetime import datetime
from typing import AsyncGenerator, Optional
from urllib.parse import unquote_plus, quote_plus, urlparse
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, FileResponse

from ..base import (
    config,
    _jinja_env,
    _get_ollama_client,
    COOKIE_NAME,
    verify_session_token,
    verify_auth,
    db_session,
)
from ..models import HTMLPage
from ..models_orm import (
    Base,
    FetchedPage,
    PageVersion,
    YouTubeVideo,
    ArticleEmbedding,
    TitleEmbedding,
    VideoEmbedding,
    ChunkEmbedding,
    Collection,
    CollectionItem,
    AgentPrompt,
    CliApiKey,
    RegisteredClient,
    SystemLog,
)
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
from ..config import DEFAULT_RAG_SYSTEM_PROMPT, DEFAULT_TAXONOMY_SYSTEM_PROMPT

from bs4 import BeautifulSoup  # type: ignore

router = APIRouter()


# --- Background Tasks Routine ---


def run_bulk_description_maintenance() -> None:
    """Loops through historical page captures, prompting Ollama to rewrite pages lacking proper descriptions."""
    client = _get_ollama_client()
    with db_session() as session:
        rows = session.query(FetchedPage).all()
        for row in rows:
            desc = row.description or ""
            if not desc or "AI Processing skipped" in desc:
                try:
                    p_dict = {col.name: getattr(row, col.name) for col in row.__table__.columns}
                    for fld in ("links", "keywords", "tags"):
                        if p_dict.get(fld):
                            try:
                                p_dict[fld] = json.loads(p_dict[fld])
                            except Exception:
                                p_dict[fld] = []
                        else:
                            p_dict[fld] = []
                    page_obj = HTMLPage(**p_dict)
                    print(f"Running maintenance extraction for: {page_obj.url}")
                    wiki_text = extract_wiki_content(page_obj, config, client)
                    row.description = wiki_text
                except Exception as e:
                    print(f"Failed background processing for {row.url}: {e}")
                    continue


def run_bulk_embedding_maintenance() -> None:
    """Loops through all fetched pages, generating embeddings for any that are missing."""
    client = _get_ollama_client()
    with db_session() as session:
        rows = session.query(FetchedPage).all()
        for row in rows:
            url = row.url
            art_emb = session.query(ArticleEmbedding).filter_by(url=url).first()
            tit_emb = session.query(TitleEmbedding).filter_by(url=url).first()

            if not art_emb or not tit_emb:
                update_article_embedding(None, url, config, client)


# --- Router Endpoints ---


logger = logging.getLogger("kb_web")


@router.get("/import", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
def get_import_url_page() -> HTMLResponse:
    """Serves the primary admin entry page where URL import strings can be submitted."""
    with db_session() as session:
        collections = [
            {col.name: getattr(c, col.name) for col in c.__table__.columns}
            for c in session.query(Collection).all()
        ]
    template = _jinja_env.get_template("url_import.j2.html")
    return HTMLResponse(content=template.render(is_admin=True, collections=collections))


@router.get(
    "/import/shared-url", dependencies=[Depends(verify_auth)], response_model=None
)
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

    with db_session() as session:
        collections = [
            {col.name: getattr(c, col.name) for col in c.__table__.columns}
            for c in session.query(Collection).all()
        ]

    template = _jinja_env.get_template("url_import.j2.html")
    return HTMLResponse(
        content=template.render(
            prefilled_url=target_link, is_admin=True, collections=collections
        )
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

        client = _get_ollama_client()
        from fastapi.concurrency import run_in_threadpool

        logger.info(
            f"Ingestion started for URL: {cleaned_url} (collection: {collection_id}, new title: {new_collection_title})"
        )

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
            logger.error(
                f"Ingestion fetch failed for: {cleaned_url} - Error: {str(e)}",
                exc_info=True,
            )
            return

        # Check duplicate
        with db_session() as session:
            existing = session.query(FetchedPage).filter_by(url=cleaned_url).first()
            if existing:
                if existing.md_content_hash == page_data.md_content_hash:
                    yield f"<script>addLog({json.dumps('Content hash matches existing record. Ingestion skipped.')});</script>\n"
                    time.sleep(1)
                    # Redirect
                    yield f"<script>window.location.href = '/view/page?url={quote_plus(cleaned_url)}&msg=Content+unchanged.+Skipping+ingestion.';</script>\n"
                    return
                else:
                    yield f"<script>addLog({json.dumps('Content changed. Archiving current version...')});</script>\n"
                    session.add(
                        PageVersion(
                            url=existing.url,
                            title=existing.title,
                            html_content=existing.html_content,
                            md_content=existing.md_content,
                            links=existing.links,
                            html_content_hash=existing.html_content_hash,
                            md_content_hash=existing.md_content_hash,
                            fetched_at=existing.fetched_at,
                            description=existing.description,
                            keywords=existing.keywords,
                            tags=existing.tags,
                        )
                    )

        # Step 2: Extraction LLM
        msg = "Extracting details and summary with Ollama..."
        yield f"<script>updateProgress({json.dumps(msg)}, 40);</script>\n"
        try:
            wiki_entry = await run_in_threadpool(
                extract_wiki_content, page_data, config, client
            )
            page_data.description = wiki_entry
            yield f"<script>addLog({json.dumps('LLM profile summary generation complete.')});</script>\n"
        except Exception as e:
            err_msg = f"LLM Summary Extraction failed: {str(e)}"
            yield f"<script>showError({json.dumps(err_msg)});</script>\n"
            logger.error(
                f"LLM Summary Extraction failed for: {cleaned_url} - Error: {str(e)}",
                exc_info=True,
            )
            return

        # Determine Title
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

        # Step 3: Extract Tags
        msg = "Extracting auto tags with Ollama..."
        yield f"<script>updateProgress({json.dumps(msg)}, 60);</script>\n"
        try:
            tags = await run_in_threadpool(
                extract_tags_content, page_data, config, client
            )
            page_data.tags = tags
            yield f"<script>addLog({json.dumps(f'Tags generation complete: {tags}')});</script>\n"
        except Exception as e:
            yield f"<script>addLog({json.dumps(f'Tags warning: {e}')});</script>\n"

        # Step 4: Save & Embed
        msg = "Saving profiles and computing embeddings..."
        yield f"<script>updateProgress({json.dumps(msg)}, 85);</script>\n"

        # Resolve Collections
        resolved_col_id = None
        with db_session() as session:
            if new_collection_title and new_collection_title.strip():
                col_title = new_collection_title.strip()
                col = session.query(Collection).filter_by(title=col_title).first()
                if not col:
                    col = Collection(
                        title=col_title,
                        visibility="public",
                        rag_system_prompt=DEFAULT_RAG_SYSTEM_PROMPT,
                        taxonomy_system_prompt=DEFAULT_TAXONOMY_SYSTEM_PROMPT,
                        general_system_context="{}",
                        created_at=datetime.now().isoformat(),
                    )
                    session.add(col)
                    session.flush()
                resolved_col_id = col.id
            elif collection_id and collection_id.isdigit():
                resolved_col_id = int(collection_id)

        page_data.collection_id = resolved_col_id
        serialized, creator = serialize_page_for_db(page_data)

        with db_session() as session:
            page = session.query(FetchedPage).filter_by(url=cleaned_url).first()
            if page:
                for k, v in serialized.items():
                    setattr(page, k, v)
            else:
                session.add(FetchedPage(**serialized))

            # Associate to Collection
            if resolved_col_id:
                existing_item = session.query(CollectionItem).filter_by(collection_id=resolved_col_id, source_id=cleaned_url).first()
                if not existing_item:
                    is_video = extract_youtube_video_id(cleaned_url) is not None
                    source_type = "videos" if is_video else "articles"
                    # Determine next item order
                    from sqlalchemy import func
                    max_order = session.query(func.max(CollectionItem.item_order)).filter_by(collection_id=resolved_col_id).scalar() or 0
                    session.add(
                        CollectionItem(
                            collection_id=resolved_col_id,
                            source_type=source_type,
                            source_id=cleaned_url,
                            item_note="",
                            taxonomy_path="",
                            item_order=max_order + 1,
                            added_at=datetime.now().isoformat(),
                        )
                    )

        # Sync youtube metadata and embeddings
        await run_in_threadpool(save_youtube_metadata_helper, None, page_data.url, creator)
        await run_in_threadpool(update_article_embedding, None, page_data.url, config, client)
        await run_in_threadpool(generate_gemma_embeddings_for_page, None, page_data.url, config, client)

        # Background download check
        video_id = extract_youtube_video_id(cleaned_url)
        if download_video == "true" and video_id:
            background_tasks.add_task(
                background_video_downloader, video_id, page_data.url, config
            )
            yield f"<script>addLog({json.dumps('Spawning background downloader for YouTube video file...')});</script>\n"

        base_url = str(request.base_url).rstrip("/")
        view_url = f"{base_url}/view/page?url={page_data.safe_url}"
        post_to_gotify(config, _jinja_env, page_data, view_url)

        yield f"<script>updateProgress({json.dumps('Ingestion pipeline complete!')}, 100);</script>\n"
        time.sleep(1)
        yield f"<script>window.location.href = '/view/page?url={quote_plus(cleaned_url)}&msg=Ingestion+successful.';</script>\n"

    return StreamingResponse(
        stream_ingestion(),
        media_type="text/html",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/admin", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
def get_admin_dashboard(msg: Optional[str] = Query(None)) -> HTMLResponse:
    """Serves the admin page containing DB backups, imports, and maintenance triggers."""
    count = 0
    wiki_prompts_history = []
    youtube_prompts_history = []
    cli_keys = []
    registered_clients = []

    with db_session() as session:
        all_pages = session.query(FetchedPage).all()
        count = sum(
            1
            for r in all_pages
            if not r.description
            or "AI Processing skipped" in r.description
        )

        try:
            wiki_prompts_history = [
                {col.name: getattr(p, col.name) for col in p.__table__.columns}
                for p in session.query(AgentPrompt)
                .filter_by(prompt_type="wiki_prompt")
                .order_by(AgentPrompt.version.desc())
                .all()
            ]
            youtube_prompts_history = [
                {col.name: getattr(p, col.name) for col in p.__table__.columns}
                for p in session.query(AgentPrompt)
                .filter_by(prompt_type="youtube_wiki_prompt")
                .order_by(AgentPrompt.version.desc())
                .all()
            ]
        except Exception as e:
            print(f"Failed to fetch prompt history: {e}")

        try:
            cli_keys = [
                {col.name: getattr(k, col.name) for col in k.__table__.columns}
                for k in session.query(CliApiKey).order_by(CliApiKey.created_at.desc()).all()
            ]
        except Exception as e:
            print(f"Failed to fetch CLI keys: {e}")

        try:
            registered_clients = [
                {col.name: getattr(c, col.name) for col in c.__table__.columns}
                for c in session.query(RegisteredClient)
                .order_by(RegisteredClient.registered_at.desc())
                .all()
            ]
        except Exception as e:
            print(f"Failed to fetch registered clients: {e}")

    # Enumerate local JSON database backups
    backups = []
    try:
        config.backups_dir.mkdir(parents=True, exist_ok=True)
        for f in config.backups_dir.glob("*.json"):
            st = f.stat()
            backups.append({
                "filename": f.name,
                "size_mb": round(st.st_size / (1024 * 1024), 2),
                "created_at": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
        backups.sort(key=lambda x: x["created_at"], reverse=True)
    except Exception as e:
        print(f"Failed to list local backups: {e}")

    # Enumerate local YouTube video backups and count on disk
    video_backups = []
    video_files_count = 0
    try:
        from ..video_manager import list_video_backups, get_media_dir
        video_backups = list_video_backups(config)
        media_dir = get_media_dir(config)
        video_files_count = len([
            f for f in media_dir.iterdir()
            if f.is_file() and f.suffix.lower() in {".mp4", ".webm", ".mkv", ".m4v"}
        ])
    except Exception as e:
        print(f"Failed to list video backups: {e}")

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
            backups=backups,
            video_backups=video_backups,
            video_files_count=video_files_count,
        )
    )


@router.post("/admin/prompts/set-head", dependencies=[Depends(verify_auth)])
def set_prompt_head(
    prompt_id: int = Form(...),
    prompt_type: str = Form(...),
) -> RedirectResponse:
    """Sets a specific historical version of a system prompt as the current active HEAD prompt."""
    try:
        with db_session() as session:
            # 1. Update is_head = 0 for all prompts of this type
            session.query(AgentPrompt).filter_by(prompt_type=prompt_type).update({"is_head": 0})
            # 2. Update is_head = 1 for the target prompt id
            target = session.query(AgentPrompt).filter_by(id=prompt_id).first()
            if target:
                target.is_head = 1
                session.flush()

                # 3. Retrieve the prompt text and sync with the active Config attributes
                if prompt_type == "wiki_prompt":
                    config._wiki_prompt = target.prompt_text
                elif prompt_type == "youtube_wiki_prompt":
                    config._youtube_wiki_prompt = target.prompt_text
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
    gotify_url: str = Form(...), gotify_token: str = Form(...)
) -> dict:
    """Sends a test validation notification to the specified Gotify server."""
    if not gotify_url or not gotify_token:
        return {"status": "error", "message": "Missing Gotify configuration URL/Token."}

    payload = {
        "title": "KB Web Core Connection Test",
        "message": f"Successfully connected Gotify integration at {datetime.now().isoformat()}",
        "priority": 5,
    }
    url_target = gotify_url.rstrip("/") + "/message"
    headers = {"X-Gotify-Key": gotify_token}
    try:
        res = httpx.post(url_target, headers=headers, json=payload, timeout=10.0)
        res.raise_for_status()
        return {"status": "success", "message": "Notification successfully sent."}
    except Exception as e:
        return {
            "status": "error",
            "message": f"Gotify notification delivery failed: {str(e)}",
        }


@router.post("/admin/test-ollama", dependencies=[Depends(verify_auth)])
def test_ollama() -> dict:
    """Queries the Ollama server validation tags endpoint to verify connectivity."""
    client = _get_ollama_client()
    try:
        models_data = client.list()
        model_names = [m.model for m in models_data.models]
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
    decoded_url = unquote_plus(url)
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=decoded_url).first()
        if not page:
            raise HTTPException(status_code=404, detail="Ingested page profile missing.")

        p_dict = {col.name: getattr(page, col.name) for col in page.__table__.columns}
        for fld in ("links", "keywords", "tags"):
            if p_dict.get(fld):
                try:
                    p_dict[fld] = json.loads(p_dict[fld])
                except Exception:
                    p_dict[fld] = []
            else:
                p_dict[fld] = []
        page_obj = HTMLPage(**p_dict)

        client = _get_ollama_client()
        wiki_entry = extract_wiki_content(page_obj, config, client)

        title = page_obj.title or page_obj.url
        if wiki_entry.strip().startswith("#"):
            first_line = wiki_entry.strip().split("\n")[0]
            title = first_line.replace("#", "").strip()

        page.description = wiki_entry
        page.title = title

    update_article_embedding(None, decoded_url, config, client)
    return RedirectResponse(
        url=f"/view/page?url={quote_plus(decoded_url)}", status_code=303
    )


@router.post(
    "/admin/regenerate/youtube-metadata",
    dependencies=[Depends(verify_auth)],
    response_model=None,
)
def handle_regenerate_youtube_metadata(url: str = Query(...)) -> RedirectResponse:
    """Triggers re-fetching and updating YouTube video metadata for a page."""
    decoded_url = unquote_plus(url)
    video_id = extract_youtube_video_id(decoded_url)
    if not video_id:
        return RedirectResponse(
            url=f"/view/page?url={quote_plus(decoded_url)}&error=Not+a+valid+YouTube+video+URL.",
            status_code=303,
        )

    try:
        save_youtube_metadata_helper(None, decoded_url, force_fetch=True)
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
    decoded_url = unquote_plus(url)
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=decoded_url).first()
        if not page:
            raise HTTPException(status_code=404, detail="Ingested page profile missing.")

        p_dict = {col.name: getattr(page, col.name) for col in page.__table__.columns}
        for fld in ("links", "keywords", "tags"):
            if p_dict.get(fld):
                try:
                    p_dict[fld] = json.loads(p_dict[fld])
                except Exception:
                    p_dict[fld] = []
            else:
                p_dict[fld] = []
        page_obj = HTMLPage(**p_dict)

        client = _get_ollama_client()
        tags = extract_tags_content(page_obj, config, client)
        page.tags = json.dumps(tags)

    update_article_embedding(None, decoded_url, config, client)
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
    client = _get_ollama_client()
    tags = [t.strip().lower() for t in tags_csv.split(",") if t.strip()]
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=url).first()
        if page:
            page.tags = json.dumps(tags)
    update_article_embedding(None, url, config, client)
    return RedirectResponse(url=f"/view/page?url={quote_plus(url)}", status_code=303)


@router.post(
    "/admin/refetch/page", dependencies=[Depends(verify_auth)], response_model=None
)
def handle_refetch_page(
    request: Request,
    url: str = Query(...),
) -> RedirectResponse:
    """Re-fetches the page URL. If successful, archives the current version and updates."""
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
        with db_session() as session:
            current_row = session.query(FetchedPage).filter_by(url=decoded_url).first()
            if current_row:
                session.add(
                    PageVersion(
                        url=current_row.url,
                        title=current_row.title,
                        html_content=current_row.html_content,
                        md_content=current_row.md_content,
                        links=current_row.links,
                        html_content_hash=current_row.html_content_hash,
                        md_content_hash=current_row.md_content_hash,
                        fetched_at=current_row.fetched_at,
                        description=current_row.description,
                        keywords=current_row.keywords,
                        tags=current_row.tags,
                    )
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
        with db_session() as session:
            current_row = session.query(FetchedPage).filter_by(url=decoded_url).first()
            if current_row:
                page_data.collection_id = current_row.collection_id
    except Exception:
        pass

    serialized, creator = serialize_page_for_db(page_data)
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=decoded_url).first()
        if page:
            for k, v in serialized.items():
                setattr(page, k, v)
        else:
            session.add(FetchedPage(**serialized))

    save_youtube_metadata_helper(None, decoded_url, creator)
    update_article_embedding(None, decoded_url, config, client)

    base_url = str(request.base_url).rstrip("/")
    view_url = f"/view/page?url={page_data.safe_url}"
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
    try:
        with db_session() as session:
            session.query(FetchedPage).filter_by(url=url).delete()
            session.query(PageVersion).filter_by(url=url).delete()
            session.query(ArticleEmbedding).filter_by(url=url).delete()
            session.query(TitleEmbedding).filter_by(url=url).delete()
        print(
            f"Administrative Delete: Removed {url} and all archived versions from database."
        )
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
def export_database() -> FileResponse:
    """Generates a full database backup JSON file, saves it locally to Config.backups_dir, and returns it for download."""
    config.backups_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_file = config.backups_dir / f"kb_backup_{ts}.json"

    from ..scripts.db_snapshot import create_database_snapshot
    create_database_snapshot(target="default", config=config, out_path=dest_file)

    return FileResponse(
        path=dest_file,
        filename=dest_file.name,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={dest_file.name}"},
    )


@router.post("/admin/backups/create", dependencies=[Depends(verify_auth)])
def create_local_backup() -> RedirectResponse:
    """Creates a local database JSON backup file in Config.backups_dir."""
    try:
        config.backups_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_file = config.backups_dir / f"kb_backup_{ts}.json"
        from ..scripts.db_snapshot import create_database_snapshot
        create_database_snapshot(target="default", config=config, out_path=dest_file)
        return RedirectResponse(
            url=f"/admin?msg=Backup+{quote_plus(dest_file.name)}+successfully+created+on+server.",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin?msg=Failed+to+create+backup:+{quote_plus(str(e))}",
            status_code=303,
        )


@router.get("/admin/backups/download/{filename}", dependencies=[Depends(verify_auth)], response_model=None)
def download_local_backup(filename: str) -> FileResponse:
    """Downloads a local database backup JSON from Config.backups_dir."""
    safe_name = os.path.basename(filename)
    target = config.backups_dir / safe_name
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Backup file not found on server.")
    return FileResponse(
        path=target,
        filename=safe_name,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={safe_name}"},
    )


@router.post("/admin/backups/restore", dependencies=[Depends(verify_auth)])
def restore_local_backup(filename: str = Form(...)) -> RedirectResponse:
    """Restores database contents from a local JSON backup in Config.backups_dir."""
    try:
        safe_name = os.path.basename(filename)
        target = config.backups_dir / safe_name
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="Selected backup file not found.")

        from ..scripts.db_snapshot import restore_database_snapshot
        stats = restore_database_snapshot(target, target="default", config=config)
        total = sum(stats.values())
        return RedirectResponse(
            url=f"/admin?msg=Successfully+restored+{total}+records+from+{quote_plus(safe_name)}.",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin?msg=Failed+to+restore+backup:+{quote_plus(str(e))}",
            status_code=303,
        )


@router.post("/admin/backups/delete/{filename}", dependencies=[Depends(verify_auth)])
def delete_local_backup(filename: str) -> RedirectResponse:
    """Deletes a local backup JSON from Config.backups_dir."""
    try:
        safe_name = os.path.basename(filename)
        target = config.backups_dir / safe_name
        if target.exists() and target.is_file():
            target.unlink()
        return RedirectResponse(
            url=f"/admin?msg=Backup+file+{quote_plus(safe_name)}+deleted.",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin?msg=Failed+to+delete+backup:+{quote_plus(str(e))}",
            status_code=303,
        )


@router.post("/admin/backups/upload", dependencies=[Depends(verify_auth)])
async def upload_local_backup(
    file: UploadFile = File(...), restore_now: bool = Form(False)
) -> RedirectResponse:
    """Uploads a backup JSON file to Config.backups_dir and optionally restores it immediately."""
    try:
        config.backups_dir.mkdir(parents=True, exist_ok=True)
        safe_name = os.path.basename(file.filename or f"kb_backup_upload_{int(time.time())}.json")
        dest = config.backups_dir / safe_name
        content = await file.read()
        with open(dest, "wb") as f:
            f.write(content)

        msg = f"Backup+{quote_plus(safe_name)}+successfully+uploaded."
        if restore_now:
            from ..scripts.db_snapshot import restore_database_snapshot
            stats = restore_database_snapshot(dest, target="default", config=config)
            total = sum(stats.values())
            msg += f"+Restored+{total}+records."

        return RedirectResponse(url=f"/admin?msg={msg}", status_code=303)
    except Exception as e:
        return RedirectResponse(
            url=f"/admin?msg=Upload+failed:+{quote_plus(str(e))}",
            status_code=303,
        )


# --- Video Media Backup Routes ---


@router.post("/admin/backups/videos/create", dependencies=[Depends(verify_auth)])
def create_video_backup() -> RedirectResponse:
    """Creates a local ZIP backup of all videos in media/videos (retaining max 2 backups)."""
    try:
        from ..video_manager import create_video_backup_zip
        archive = create_video_backup_zip(config, max_backups=2)
        if archive and archive.exists():
            return RedirectResponse(
                url=f"/admin?msg=Video+backup+{quote_plus(archive.name)}+created+successfully.",
                status_code=303,
            )
        return RedirectResponse(
            url="/admin?msg=No+videos+found+to+backup.",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin?msg=Failed+to+create+video+backup:+{quote_plus(str(e))}",
            status_code=303,
        )


@router.get("/admin/backups/videos/download/{filename}", dependencies=[Depends(verify_auth)], response_model=None)
def download_video_backup(filename: str) -> FileResponse:
    """Downloads a video ZIP backup file from Config.backups_dir."""
    safe_name = os.path.basename(filename)
    target = config.backups_dir / safe_name
    if not target.exists() or not target.is_file() or not safe_name.startswith("kb_videos_backup_"):
        raise HTTPException(status_code=404, detail="Video backup archive not found.")
    return FileResponse(
        path=target,
        filename=safe_name,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={safe_name}"},
    )


@router.post("/admin/backups/videos/restore", dependencies=[Depends(verify_auth)])
def restore_video_backup(filename: str = Form(...)) -> RedirectResponse:
    """Restores videos from a ZIP backup and updates database index."""
    try:
        safe_name = os.path.basename(filename)
        from ..video_manager import restore_video_backup_zip
        target = config.backups_dir / safe_name
        count = restore_video_backup_zip(target, config=config)
        return RedirectResponse(
            url=f"/admin?msg=Successfully+restored+{count}+videos+from+{quote_plus(safe_name)}.",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin?msg=Failed+to+restore+videos:+{quote_plus(str(e))}",
            status_code=303,
        )


@router.post("/admin/backups/videos/delete/{filename}", dependencies=[Depends(verify_auth)])
def delete_video_backup(filename: str) -> RedirectResponse:
    """Deletes a video ZIP backup archive."""
    try:
        from ..video_manager import delete_video_backup_zip
        delete_video_backup_zip(filename, config=config)
        return RedirectResponse(
            url=f"/admin?msg=Video+backup+{quote_plus(filename)}+deleted.",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin?msg=Failed+to+delete+video+backup:+{quote_plus(str(e))}",
            status_code=303,
        )


@router.post("/admin/backups/videos/reindex", dependencies=[Depends(verify_auth)])
def reindex_videos_action() -> RedirectResponse:
    """Re-scans media/videos and updates youtube_videos.local_path in the database."""
    try:
        from ..video_manager import index_local_videos
        res = index_local_videos(config=config)
        return RedirectResponse(
            url=f"/admin?msg=Indexed+{res['indexed_count']}+local+videos+({res['total_files']}+files+found).",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin?msg=Failed+to+reindex+videos:+{quote_plus(str(e))}",
            status_code=303,
        )


@router.get("/admin/ws/import", response_class=HTMLResponse)
def websocket_import_diagnostic_fallback() -> HTMLResponse:
    """Diagnostic fallback for reverse proxies dropping the WebSocket Upgrade header."""
    return HTMLResponse(
        content="""
        <html>
        <head>
            <title>WebSocket Import Endpoint</title>
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 3rem; line-height: 1.6; max-width: 650px; margin: auto; }
                .box { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 1.5rem; margin-top: 1rem; }
                code { background: #e5e7eb; padding: 0.2rem 0.4rem; border-radius: 4px; font-size: 0.9em; }
                .btn { display: inline-block; background: #4f46e5; color: white; padding: 0.6rem 1.2rem; border-radius: 6px; text-decoration: none; margin-top: 1rem; font-weight: 500; }
            </style>
        </head>
        <body>
            <h2>WebSocket Import Endpoint Notice</h2>
            <p>This endpoint (<code>/admin/ws/import</code>) is designed for WebSocket connections (<code>ws://</code> or <code>wss://</code>).</p>
            <div class="box">
                <p><strong>Why did you see this page?</strong></p>
                <p>Your connection reached the server as a regular HTTP <code>GET</code> request. This typically happens when a reverse proxy (such as Nginx, Traefik, or Cloudflare) does not forward the <code>Upgrade: websocket</code> and <code>Connection: Upgrade</code> headers.</p>
                <p>You can use the direct <strong>HTTP File Upload</strong> or <strong>Local Server Backups</strong> on the Admin dashboard without needing WebSockets.</p>
            </div>
            <a href="/admin" class="btn">&larr; Return to Admin Dashboard</a>
        </body>
        </html>
        """,
        status_code=200,
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

        success_count = 0

        if isinstance(data, dict):
            # Full database multi-table backup
            with db_session() as session:
                for mapper in Base.registry.mappers:
                    model_cls = mapper.class_
                    table_name = model_cls.__tablename__

                    if table_name in data and data[table_name]:
                        raw_rows = data[table_name]
                        for r in raw_rows:
                            clean_r = {}
                            for k, v in r.items():
                                if isinstance(v, str):
                                    v = v.replace("\x00", "")
                                if isinstance(v, str) and v.startswith("hex:"):
                                    try:
                                        clean_r[k] = bytes.fromhex(v[4:])
                                    except ValueError:
                                        clean_r[k] = v
                                elif isinstance(v, str) and (k.endswith("embedding") or k.endswith("vector")):
                                    if v.startswith("[") and v.endswith("]"):
                                        try:
                                            clean_r[k] = json.loads(v)
                                        except Exception:
                                            clean_r[k] = v
                                    else:
                                        clean_r[k] = v
                                else:
                                    clean_r[k] = v

                            if model_cls in (ArticleEmbedding, TitleEmbedding, YouTubeVideo, VideoEmbedding):
                                url_val = clean_r.get("url")
                                if url_val:
                                    parent = session.query(FetchedPage).filter_by(url=url_val).first()
                                    if not parent:
                                        session.add(
                                            FetchedPage(
                                                url=url_val,
                                                title=f"Archived Item ({url_val})",
                                                fetched_at=datetime.now().isoformat(),
                                            )
                                        )
                                        session.flush()

                            pks = [c.name for c in model_cls.__table__.primary_key.columns]
                            pk_vals = {pk: clean_r[pk] for pk in pks if pk in clean_r}

                            try:
                                existing = None
                                if len(pk_vals) == len(pks):
                                    existing = session.query(model_cls).filter_by(**pk_vals).first()

                                if existing:
                                    for k, v in clean_r.items():
                                        setattr(existing, k, v)
                                else:
                                    session.add(model_cls(**clean_r))
                                success_count += 1
                            except Exception as err:
                                print(f"WS Import Error in {table_name}: {err}")

                from sqlalchemy import text
                if session.bind and "postgresql" in str(session.bind.url):
                    for mapper in Base.registry.mappers:
                        m_cls = mapper.class_
                        t_name = m_cls.__tablename__
                        pks = [c.name for c in m_cls.__table__.primary_key.columns]
                        if pks and len(pks) == 1:
                            col_obj = m_cls.__table__.columns[pks[0]]
                            if hasattr(col_obj.type, "python_type") and col_obj.type.python_type == int:
                                try:
                                    session.execute(
                                        text(
                                            f"SELECT setval(pg_get_serial_sequence('{t_name}', '{pks[0]}'), "
                                            f"COALESCE((SELECT MAX({pks[0]}) FROM {t_name}), 1));"
                                        )
                                    )
                                except Exception:
                                    pass

                from ..video_manager import index_local_videos
                index_local_videos(config)

            msg = f"SUCCESS: Restored database. Imported {success_count} total records across tables."
        elif isinstance(data, list):
            # Legacy fetched_pages list format
            with db_session() as session:
                for record in data:
                    try:
                        page_obj = HTMLPage(**record)
                        serialized, creator = serialize_page_for_db(page_obj)

                        page = session.query(FetchedPage).filter_by(url=page_obj.url).first()
                        if page:
                            for k, v in serialized.items():
                                setattr(page, k, v)
                        else:
                            session.add(FetchedPage(**serialized))

                        if creator:
                            save_youtube_metadata_helper(None, page_obj.url, creator)
                        success_count += 1
                    except Exception as e:
                        print(
                            f"Skipping record {record.get('url')} due to validation error: {e}"
                        )
            msg = (
                f"SUCCESS: Imported {success_count} legacy records into fetched_pages."
            )
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


@router.get(
    "/admin/logs", response_class=HTMLResponse, dependencies=[Depends(verify_auth)]
)
def get_logs_view(
    request: Request, limit: Optional[int] = Query(None, ge=1, le=10000)
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

    log_content = ""
    try:
        with db_session() as session:
            rows = session.query(SystemLog).order_by(SystemLog.id.desc()).limit(limit).all()

            lines = []
            for r in rows:
                ts = r.timestamp or ""
                lvl = r.level or "INFO"
                mod = r.module or "root"
                msg = r.message or ""
                tb = r.traceback or ""

                line = f"[{ts}] {lvl} in {mod}: {msg}"
                if tb:
                    line += f"\n{tb}"
                lines.append(line)
            log_content = "\n".join(lines)
    except Exception as e:
        log_content = f"Error reading logs from database: {e}"

    template = _jinja_env.get_template("logs.j2.html")
    response = HTMLResponse(
        content=template.render(log_content=log_content, is_admin=True, limit=limit)
    )
    response.set_cookie("log_limit", str(limit), max_age=31536000, path="/")
    return response


@router.get("/admin/logs/download", dependencies=[Depends(verify_auth)])
def download_logs(
    request: Request, limit: Optional[int] = Query(None, ge=1, le=10000)
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
        try:
            with db_session() as session:
                rows = session.query(SystemLog).order_by(SystemLog.id.desc()).limit(limit).all()
                for r in rows:
                    ts = r.timestamp or ""
                    lvl = r.level or "INFO"
                    mod = r.module or "root"
                    msg = r.message or ""
                    tb = r.traceback or ""

                    line = f"[{ts}] {lvl} in {mod}: {msg}\n"
                    if tb:
                        line += f"{tb}\n"
                    yield line
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

    new_key = str(uuid.uuid4()).replace("-", "")
    try:
        with db_session() as session:
            session.add(
                CliApiKey(
                    key=new_key,
                    name=name,
                    created_at=datetime.now().isoformat(),
                )
            )
        return RedirectResponse(
            url="/admin?msg=New+CLI+API+Key+generated.", status_code=303
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin?msg=Error+generating+key:+{str(e)}", status_code=303
        )


@router.post("/admin/cli/keys/delete", dependencies=[Depends(verify_auth)])
def admin_delete_cli_key(key: str = Form(...)) -> RedirectResponse:
    try:
        with db_session() as session:
            session.query(CliApiKey).filter_by(key=key).delete()
        return RedirectResponse(url="/admin?msg=CLI+API+Key+revoked.", status_code=303)
    except Exception as e:
        return RedirectResponse(
            url=f"/admin?msg=Error+revoking+key:+{str(e)}", status_code=303
        )


@router.post("/admin/cli/clients/delete", dependencies=[Depends(verify_auth)])
def admin_delete_cli_client(computer_name: str = Form(...)) -> RedirectResponse:
    try:
        with db_session() as session:
            session.query(RegisteredClient).filter_by(computer_name=computer_name).delete()
        return RedirectResponse(
            url="/admin?msg=Registered+CLI+client+removed.", status_code=303
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin?msg=Error+removing+client:+{str(e)}", status_code=303
        )
