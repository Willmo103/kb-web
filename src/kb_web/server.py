"""
Server entry point for the Knowledge Base Web Importer application.
"""

import os
import logging
import traceback
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

from .base import config
# from .cron_scheduler import run_cron_scheduler
from .gotify import post_error_to_gotify

# Setup logging targeting ~/.kb/logs/kb-web.log
def setup_logging():
    log_dir = config.configs_dir.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "kb-web.log"
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers = []
    
    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    ))
    logger.addHandler(console_handler)
    
    # File Handler
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    ))
    logger.addHandler(file_handler)
    
    logging.getLogger("kb_web").setLevel(logging.INFO)

setup_logging()
logger = logging.getLogger("kb_web")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


# Instantiate core application
app = FastAPI(title="Knowledge Base Web Importer", lifespan=lifespan)


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


# Import and register routers
from .routers import auth, pages, sites, admin, api, collections, graph  # noqa: E402

app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(sites.router)
app.include_router(admin.router)
app.include_router(api.router)
app.include_router(collections.router)
app.include_router(graph.router)


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
