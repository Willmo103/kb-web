"""
Server entry point for the Knowledge Base Web Importer application.
"""

import os
import logging
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

from .base import config
from .gotify import post_error_to_gotify

# Setup logging using SQLite database table system_logs
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers = []
    
    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    ))
    logger.addHandler(console_handler)
    
    # SQLite Database Logging Handler
    try:
        from .base import SQLiteLogHandler
        db_handler = SQLiteLogHandler(config.db_path)
        db_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(db_handler)
    except Exception as e:
        print(f"Warning: Failed to setup SQLiteLogHandler: {e}")
    
    logging.getLogger("kb_web").setLevel(logging.INFO)

setup_logging()
logger = logging.getLogger("kb_web")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run database migrations on startup
    try:
        from scripts.deploy_migrations import deploy
        deploy()
    except Exception as e:
        logger.error(f"Failed to run database migrations on startup: {e}")
    yield


# Instantiate core application
app = FastAPI(title="Knowledge Base Web Importer", lifespan=lifespan)


# Request logging middleware to trace request lifecycle and performance
@app.middleware("http")
async def log_request_middleware(request: Request, call_next):
    import time
    start_time = time.time()
    method = request.method
    url = str(request.url)
    client_host = request.client.host if request.client else "unknown"
    
    logger.info(f"Incoming request: {method} {url} from {client_host}")
    
    try:
        response = await call_next(request)
        duration = time.time() - start_time
        logger.info(f"Completed request: {method} {url} - Status: {response.status_code} - Duration: {duration:.3f}s")
        return response
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Failed request: {method} {url} - Error: {str(e)} - Duration: {duration:.3f}s", exc_info=True)
        raise e



# Exception handler posting internal errors to Gotify
@app.exception_handler(Exception)
async def gotify_error_logging_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    logger.error(f"Uncaught exception: {exc}\n{tb}")
    
    try:
        post_error_to_gotify(config, exc, tb, request)
    except Exception as e:
        logger.error(f"Failed to post traceback to Gotify: {e}")
        
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred."}
        )
    return HTMLResponse(
        content="<h1>Internal Server Error</h1><p>An unexpected error occurred. Logged to admin console.</p>",
        status_code=500
    )


# --- Public metadata endpoints ---

@app.get("/icon.png", response_model=None)
def get_local_icon() -> FileResponse:
    """Serves the local manifest icon.png."""
    icon_path = os.path.join(os.path.dirname(__file__), "templates", "icon.png")
    if os.path.exists(icon_path):
        return FileResponse(icon_path)
    raise HTTPException(status_code=404, detail="Icon not found.")


@app.get("/favicon.ico", response_model=None)
def get_favicon() -> FileResponse:
    """Serves the local favicon.ico."""
    favicon_path = os.path.join(os.path.dirname(__file__), "templates", "favicon.ico")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    raise HTTPException(status_code=404, detail="Favicon not found.")


@app.get("/manifest.json")
def get_manifest() -> dict:
    """Returns the PWA manifest permitting mobile devices to register a Web Share Target."""
    return {
        "short_name": "KB Wiki",
        "name": "Knowledge Base Wiki Engine",
        "icons": [
            {
                "src": "/icon.png",
                "type": "image/png",
                "sizes": "512x512",
            }
        ],
        "start_url": "/pages",
        "background_color": "#F9FAFB",
        "theme_color": "#4F46E5",
        "display": "standalone",
        "share_target": {
            "action": "/import/shared-url",
            "method": "GET",
            "params": {"title": "title", "text": "text", "url": "url"},
        },
    }


@app.get("/sw.js", response_class=HTMLResponse)
def get_service_worker() -> HTMLResponse:
    """Serves a blank Service Worker required by mobile PWA client specifications."""
    return HTMLResponse(
        content="self.addEventListener('fetch', function(event) {});",
        media_type="application/javascript",
    )


# Serve media files (e.g. downloaded YouTube videos)
from fastapi.staticfiles import StaticFiles
media_dir = config.configs_dir.parent / "media"
media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")


# Import and register routers
from .routers import auth, pages, sites, admin, api, collections, graph, cli_api, links  # noqa: E402

app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(sites.router)
app.include_router(admin.router)
app.include_router(api.router)
app.include_router(collections.router)
app.include_router(graph.router)
app.include_router(cli_api.router)
app.include_router(links.router)


# --- Re-export utility functions for backward test compatibility ---
from .utils import (  # noqa: E402
    fetch_url as fetch_url,
    extract_first_url as extract_first_url,
    preprocess_markdown as preprocess_markdown,
    get_url_basename as get_url_basename,
    get_similar_articles as get_similar_articles,
    chunk_text as chunk_text,
    save_youtube_metadata_helper as save_youtube_metadata_helper,
    update_article_embedding as update_article_embedding,
    extract_youtube_video_id as extract_youtube_video_id,
    extract_wiki_content as extract_wiki_content,
    extract_tags_content as extract_tags_content,
    generate_gemma_embeddings_for_page as generate_gemma_embeddings_for_page,
)
