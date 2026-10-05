"""
Server entry point for the Knowledge Base Web Importer application.
"""

import os
import logging
import traceback
from contextlib import asynccontextmanager
from urllib.parse import quote_plus
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .base import config, is_request_authenticated
from .gotify import post_error_to_gotify, record_server_error


# Setup logging using system_logs database table
def setup_logging():
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Console Handler
    if not any(isinstance(h, logging.StreamHandler) and h.__class__.__name__ != "DatabaseLogHandler" for h in root_logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
        )
        root_logger.addHandler(console_handler)

    # Database Logging Handler
    try:
        from .base import DatabaseLogHandler

        db_handler = DatabaseLogHandler()
        db_handler.setFormatter(logging.Formatter("%(message)s"))

        # Attach to root if not already present
        if not any(isinstance(h, DatabaseLogHandler) for h in root_logger.handlers):
            root_logger.addHandler(db_handler)

        # Attach directly to application and server loggers to survive worker process resets
        for logger_name in ("kb_web", "uvicorn", "uvicorn.error", "uvicorn.access"):
            lg = logging.getLogger(logger_name)
            lg.disabled = False
            lg.setLevel(logging.INFO)
            if not any(isinstance(h, DatabaseLogHandler) for h in lg.handlers):
                lg.addHandler(db_handler)
    except Exception as e:
        print(f"Warning: Failed to setup DatabaseLogHandler: {e}")


setup_logging()
logger = logging.getLogger("kb_web")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database logging handlers remain attached after worker process initialization
    setup_logging()

    # Run database migrations on startup
    try:
        from kb_web.scripts.deploy_migrations import deploy

        deploy()
    except Exception as e:
        logger.error(f"Failed to run database migrations on startup: {e}")

    # Security posture check on startup
    if config.admin_password == "admin123":
        logger.warning(
            "CRITICAL SECURITY WARNING: Default administrator password ('admin123') is active! "
            "Because this server is accessible on the open internet, change your password immediately."
        )
    if config.api_key == "kb-secret-key":
        logger.warning(
            "SECURITY NOTICE: Default API key ('kb-secret-key') is active. "
            "Please configure a unique KB_API_KEY in production."
        )

    yield


# Instantiate core application
app = FastAPI(title="Knowledge Base Web Importer", lifespan=lifespan)


# Public exact paths that do not require prior session authentication
PUBLIC_EXACT_PATHS = {
    "/login",
    "/logout",
    "/favicon.ico",
    "/icon.png",
    "/manifest.json",
    "/sw.js",
    "/api/health",
}


@app.get("/api/health")
def health_check():
    """Health check endpoint for CLI restart polling, service checks, and monitors."""
    return {"status": "ok", "app": "kb-web"}


def _inject_security_headers(response: Response) -> None:
    """Injects industry-standard HTTP security headers onto all outgoing responses."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"


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
        logger.info(
            f"Completed request: {method} {url} - Status: {response.status_code} - Duration: {duration:.3f}s"
        )
        return response
    except Exception as e:
        duration = time.time() - start_time
        logger.error(
            f"Failed request: {method} {url} - Error: {str(e)} - Duration: {duration:.3f}s",
            exc_info=True,
        )
        raise e


# Global site security and authentication guard middleware
@app.middleware("http")
async def security_and_auth_middleware(request: Request, call_next):
    path = request.url.path

    # 1. Allow public metadata and login/logout paths
    if path in PUBLIC_EXACT_PATHS:
        response = await call_next(request)
        _inject_security_headers(response)
        return response

    # 2. Check if request is authenticated via session cookie or valid API key
    if not is_request_authenticated(request):
        # API requests or JSON requests receive 401 Unauthorized JSON
        accept_header = request.headers.get("accept", "")
        if path.startswith("/api/") or "application/json" in accept_header:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized: Authentication required."},
            )
            _inject_security_headers(response)
            return response

        # Media requests receive 401 Unauthorized plain text
        if path.startswith("/media/"):
            response = Response(
                content="Unauthorized: Authentication required to access media assets.",
                status_code=401,
                media_type="text/plain",
            )
            _inject_security_headers(response)
            return response

        # Web browser navigation receives 303 redirect to /login?next={url}
        redirect_url = f"/login?next={quote_plus(str(request.url))}"
        response = RedirectResponse(url=redirect_url, status_code=303)
        _inject_security_headers(response)
        return response

    # Request is authenticated
    response = await call_next(request)
    _inject_security_headers(response)
    return response


# Exception handler posting internal errors to Gotify, storing in DB, and alerting maintenance agent
@app.exception_handler(Exception)
async def gotify_error_logging_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    logger.error(f"Uncaught exception: {exc}\n{tb}")

    error_id = None
    try:
        error_id = record_server_error(config, exc, tb, request)
    except Exception as e:
        logger.error(f"Failed to record server error and dispatch alerts: {e}")

    if "application/json" in request.headers.get("accept", "") or request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An internal server error occurred.",
                "error_id": error_id,
            },
        )
    return HTMLResponse(
        content=(
            f"<h1>Internal Server Error</h1>"
            f"<p>An unexpected error occurred. Logged to server incident tracker"
            f"{f' (Incident #{error_id})' if error_id else ''}.</p>"
        ),
        status_code=500,
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
            "enctype": "application/x-www-form-urlencoded",
            "params": {"title": "title", "text": "text", "url": "url"},
        },
    }


@app.get("/sw.js", response_class=HTMLResponse)
def get_service_worker() -> HTMLResponse:
    """Serves a blank Service Worker required by mobile PWA client specifications without no-op fetch warnings."""
    return HTMLResponse(
        content=(
            "self.addEventListener('install', function(event) { self.skipWaiting(); });\n"
            "self.addEventListener('activate', function(event) { event.waitUntil(clients.claim()); });\n"
        ),
        media_type="application/javascript",
    )


# Serve media files (e.g. downloaded YouTube videos)

media_dir = config.configs_dir.parent / "media"
media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")


# Import and register routers
from .routers import (  # noqa: E402
    auth,
    pages,
    sites,
    admin,
    api,
    collections,
    graph,
    cli_api,
    links,
    rest_api,
    conversations,
    embeddings,
    notes,
    reports,
    rag_reports,
    workspaces,
    taxonomy,
    agent_board,
    admin_batch,
    errors,
)

app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(sites.router)
app.include_router(admin.router)
app.include_router(api.router)
app.include_router(rest_api.router)
app.include_router(collections.router)
app.include_router(graph.router)
app.include_router(cli_api.router)
app.include_router(links.router)
app.include_router(conversations.router)
app.include_router(embeddings.router)
app.include_router(notes.router)
app.include_router(reports.router)
app.include_router(rag_reports.router)
app.include_router(workspaces.router)
app.include_router(taxonomy.router)
app.include_router(agent_board.router)
app.include_router(admin_batch.router)
app.include_router(errors.router)


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
