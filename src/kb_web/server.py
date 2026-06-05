"""
Server entry point for the Knowledge Base Web Importer application.
"""

import hashlib
import json
import math
import re
import secrets
import time
from datetime import datetime
from typing import AsyncGenerator, Optional
from urllib.parse import quote_plus, unquote_plus, urljoin, urlparse

import httpx
import jinja2
import markdown
import ollama
import sqlite_utils
from bs4 import BeautifulSoup  # type: ignore
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
    FileResponse,
)
from html2text import HTML2Text
from pydantic import BaseModel

from .config import Config
from .db import get_db
from .models import HTMLPage

app = FastAPI(title="Knowledge Base Web Importer")

# Instantiate configuration and load shared DB
config = Config()

# Set up Jinja2 environment utilizing PackageLoader for clean packaging
_jinja_env = jinja2.Environment(loader=jinja2.Environment().loader)
_jinja_env = jinja2.Environment(loader=jinja2.PackageLoader("kb_web", "templates"))


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

COOKIE_NAME = "kb_session"
ACTIVE_SESSIONS: dict[str, float] = {}
SESSION_EXPIRATION_SECONDS = 3600 * 24  # 24 hours


DEFAULT_TAGS_PROMPT = (
    "You are a professional categorization assistant. Analyze the following web page content "
    "and generate a list of 5 to 10 relevant tags, keywords, or labels for cataloging it. "
    "Respond ONLY with a comma-separated list of tags (e.g., 'python, web-development, tutorial'). "
    "Do not reply with any filler headers, introductory remarks, or formatting."
)


def _get_db():
    """Helper dependency to retrieve a clean database handle.

    Returns:
        sqlite_utils.Database: Connection wrapper to ~/.kb/kb.db.
    """
    return get_db(config)


def _get_ollama_client() -> ollama.Client:
    """Helper to dynamically instantiate the Ollama client based on configured host.

    Returns:
        ollama.Client: Dynamic client instance.
    """
    return ollama.Client(host=config.ollama_host)


def clear_expired_tokens() -> None:
    """Evicts expired login tokens from memory state."""
    current_time = time.time()
    expired_keys = [
        token for token, expiry in ACTIVE_SESSIONS.items() if expiry < current_time
    ]
    for key in expired_keys:
        del ACTIVE_SESSIONS[key]


def verify_auth(request: Request) -> None:
    """Security route guard ensuring requests contain a valid session cookie.

    Raises an HTTP 303 Redirect to /login if credentials are unauthorized or missing.

    Args:
        request (Request): Incoming FastAPI HTTP request.
    """
    clear_expired_tokens()
    token = request.cookies.get(COOKIE_NAME)
    if not token or token not in ACTIVE_SESSIONS:
        # Redirect directly to login form, preserving destination
        redirect_url = f"/login?next={quote_plus(str(request.url))}"
        raise HTTPException(status_code=303, headers={"Location": redirect_url})


def verify_api_key(request: Request) -> None:
    """Security guard verifying API Key header matching KB_API_KEY.

    Args:
        request (Request): Incoming FastAPI HTTP request.

    Raises:
        HTTPException: 401 Unauthorized if API key is invalid or missing.
    """
    api_key_header = request.headers.get("X-API-Key")
    if not api_key_header:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            api_key_header = auth_header[7:]
        else:
            api_key_header = auth_header

    if config.api_key:
        if api_key_header != config.api_key:
            raise HTTPException(
                status_code=401, detail="Unauthorized: Invalid API key."
            )


# --- Public Web Share Target Metadata Endpoints ---


@app.get("/icon.png", response_model=None)
def get_local_icon() -> FileResponse:
    """Serves the local manifest icon.png."""
    import os

    icon_path = os.path.join(os.path.dirname(__file__), "templates", "icon.png")
    if os.path.exists(icon_path):
        return FileResponse(icon_path)
    raise HTTPException(status_code=404, detail="Icon not found.")


@app.get("/favicon.ico", response_model=None)
def get_favicon() -> FileResponse:
    """Serves the local favicon.ico."""
    import os

    favicon_path = os.path.join(os.path.dirname(__file__), "templates", "favicon.ico")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    raise HTTPException(status_code=404, detail="Favicon not found.")


@app.get("/manifest.json")
def get_manifest() -> dict:
    """Returns the PWA manifest permitting mobile devices to register a Web Share Target

    routing URLs to our application directly.

    Returns:
        dict: Manifest metadata definition.
    """
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
    """Serves a blank Service Worker required by mobile PWA client specifications.

    Returns:
        HTMLResponse: JS code block.
    """
    return HTMLResponse(
        content="self.addEventListener('fetch', function(event) {});",
        media_type="application/javascript",
    )


# --- Helper Functions for URL Handling & YouTube Scraping ---


def extract_first_url(text: str) -> str:
    """Extracts the first web URL from a block of text, supporting common copy-paste errors."""
    text = text.strip()
    # Find any sequence containing http:// or https:// or even http: / https:
    match = re.search(r"https?:/*\S+", text)
    if match:
        url = match.group(0)
        # Standardize scheme if it's like http:example.com
        if url.startswith("http:") and not url.startswith("http://"):
            url = "http://" + url[5:]
        elif url.startswith("https:") and not url.startswith("https://"):
            url = "https://" + url[6:]
        # Strip trailing punctuation
        url = url.rstrip(".,;()[]{}\"\"''")
        return url

    # Fallback search for a bare domain with path, e.g. example.com/article
    match_domain = re.search(r"[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/\S*)?", text)
    if match_domain:
        url = match_domain.group(0)
        url = url.rstrip(".,;()[]{}\"\"''")
        return "https://" + url

    return text


def extract_youtube_video_id(url: str) -> Optional[str]:
    """Helper to parse out YouTube video ID from various link structures."""
    try:
        parsed = urlparse(url)
        if parsed.hostname in ("youtu.be", "www.youtu.be"):
            return parsed.path.lstrip("/")
        if parsed.hostname in ("youtube.com", "www.youtube.com", "m.youtube.com"):
            if parsed.path == "/watch":
                from urllib.parse import parse_qs

                return parse_qs(parsed.query).get("v", [None])[0]
            if parsed.path.startswith(("/embed/", "/v/")):
                return parsed.path.split("/")[2]
    except Exception:
        pass
    return None


def fetch_youtube_video_page(url: str, video_id: str) -> HTMLPage:
    """Retrieves YouTube video metadata and pulls subtitle transcripts to construct custom HTML/markdown documents."""
    title = f"YouTube Video {video_id}"
    description = ""

    # 1. Fetch metadata using yt-dlp
    try:
        import yt_dlp

        class QuietLogger:
            def debug(self, msg):
                pass

            def warning(self, msg):
                pass

            def error(self, msg):
                pass

        ydl_opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "logger": QuietLogger(),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", title)
            description = info.get("description", "")
    except Exception as e:
        print(f"yt-dlp metadata extraction failed: {e}")
        # fallback to basic BeautifulSoup title fetching
        try:
            res = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=10)
            soup = BeautifulSoup(res.text, "html5lib")
            if soup.title:
                title = soup.title.string.replace(" - YouTube", "")
        except Exception:
            pass

    # 2. Retrieve transcripts using youtube-transcript-api
    transcript = None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        # Support both classmethod-based (older) and instance-based (newer) APIs
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        else:
            transcript_list = YouTubeTranscriptApi().fetch(video_id)

        # Format timestamps into transcripts
        transcript_lines = []
        for entry in transcript_list:
            # Handle both list of dicts (older) and list of FetchedTranscriptSnippet objects (newer)
            if hasattr(entry, "start"):
                start_sec = int(entry.start)
            else:
                start_sec = int(entry.get("start", 0))

            if hasattr(entry, "text"):
                text_content = entry.text
            else:
                text_content = entry.get("text", "")

            minutes = start_sec // 60
            seconds = start_sec % 60
            timestamp = f"[{minutes:02d}:{seconds:02d}]"
            transcript_lines.append(f"{timestamp} {text_content}")
        transcript = "\n".join(transcript_lines)
    except Exception as e:
        print(f"youtube-transcript-api retrieval failed for {video_id}: {e}")

    # 3. Assemble document markdown and custom HTML
    if transcript:
        md_content = f"# {title}\n\n## Video Description\n{description}\n\n## Transcript\n{transcript}"
    else:
        md_content = f"# {title}\n\n## Video Description\n{description}\n\n*(Transcript not available)*"

    html_content = f"""
    <html>
    <head><title>{title}</title></head>
    <body>
        <h1>{title}</h1>
        <div class="video-container" style="margin: 20px 0;">
            <iframe width="560" height="315" src="https://www.youtube.com/embed/{video_id}" frameborder="0" allowfullscreen></iframe>
        </div>
        <h2>Description</h2>
        <pre style="white-space: pre-wrap;">{description}</pre>
        <h2>Transcript</h2>
        <pre style="white-space: pre-wrap;">{transcript or "No transcript available."}</pre>
    </body>
    </html>
    """

    return HTMLPage(
        url=url,
        title=title,
        html_content=html_content,
        md_content=md_content,
        links=[],
        html_content_hash=hashlib.sha256(html_content.encode("utf-8")).hexdigest(),
        md_content_hash=hashlib.sha256(md_content.encode("utf-8")).hexdigest(),
        fetched_at=datetime.now().isoformat(),
        description="",
        keywords=[],
        tags=[],
    )


# --- Core Ingestion Logic & Safety Fallbacks ---


def fetch_url(url: str) -> HTMLPage:
    """Downloads content from a specified URL and extracts its markdown representation,

    hyperlinks, and cryptographic hashes.

    Args:
        url (str): Remote address to ingest.

    Returns:
        HTMLPage: Pydantic model populated with download information.

    Raises:
        RuntimeError: If download fails or format is invalid.
    """
    video_id = extract_youtube_video_id(url)
    if video_id:
        try:
            return fetch_youtube_video_page(url, video_id)
        except Exception as e:
            raise RuntimeError(f"YouTube transcript extraction failed: {e}")

    try:
        response = httpx.get(url, timeout=15, follow_redirects=True, headers=HEADERS)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"The web server returned an error status: {e.response.status_code}"
        )
    except (httpx.RequestError, Exception) as e:
        raise RuntimeError(
            f"Target server is completely unreachable or actively blocking requests: {e}"
        )

    try:
        html_content = response.text
        content_type = response.headers.get("content-type", "").lower()
        if "text" not in content_type and "html" not in content_type:
            raise RuntimeError(
                f"Target link returned non-text material ({content_type})."
            )

        h = HTML2Text()
        h.ignore_links = True
        md_content = h.handle(html_content)

        soup = BeautifulSoup(html_content, "html5lib")
        links = [a.get("href") for a in soup.find_all("a", href=True)]
        links = [urljoin(url, link) if link.startswith("/") else link for link in links]

        return HTMLPage(
            url=url,
            title=url,
            html_content=html_content,
            md_content=md_content,
            links=links,
            html_content_hash=hashlib.sha256(html_content.encode("utf-8")).hexdigest(),
            md_content_hash=hashlib.sha256(md_content.encode("utf-8")).hexdigest(),
            fetched_at=datetime.now().isoformat(),
            description="",
            keywords=[],
            tags=[],
        )
    except Exception as e:
        raise RuntimeError(f"Failed to cleanly convert webpage elements: {str(e)}")


def extract_wiki_content(html_page: HTMLPage) -> str:
    """Queries Ollama to clean, restructure, and digest raw markdown into wiki formats.

    Args:
        html_page (HTMLPage): Input scraped page model.

    Returns:
        str: Summarized or cleaned Markdown wiki entry.
    """
    try:
        client = _get_ollama_client()
        response = client.chat(
            model=config.ollama_model,
            messages=[
                {"role": "system", "content": config.wiki_prompt},
                {
                    "role": "user",
                    "content": f"URL: {html_page.url}\n\nRAW CONTENT:\n{html_page.md_content}",
                },
            ],
        )
        return response.message.content
    except Exception as e:
        print(f"Ollama extraction failed: {e}")
        return f"# Ingestion Backup \n\nAI Processing skipped or failed. Raw layout captured below.\n\n {html_page.md_content[:2000]}"


def extract_tags_content(html_page: HTMLPage) -> list[str]:
    """Queries Ollama to extract descriptive tags from markdown content.

    Args:
        html_page (HTMLPage): Input page model.

    Returns:
        list[str]: Array of extracted tags.
    """
    try:
        client = _get_ollama_client()
        response = client.chat(
            model=config.ollama_model,
            messages=[
                {"role": "system", "content": DEFAULT_TAGS_PROMPT},
                {
                    "role": "user",
                    "content": f"URL: {html_page.url}\n\nRAW CONTENT:\n{html_page.md_content}",
                },
            ],
        )
        tags_str = response.message.content
        tags = [t.strip().lower() for t in tags_str.split(",") if t.strip()]
        return [t for t in tags if t]
    except Exception as e:
        print(f"Ollama tagging failed: {e}")
        return []


def post_to_gotify(page: HTMLPage, view_url: str) -> None:
    """Dispatches Gotify notifications using the configuration helper.

    Args:
        page (HTMLPage): Saved HTMLPage metadata.
        view_url (str): Local/remote address to view the page.
    """
    try:
        template = _jinja_env.get_template("url_import_notification.j2.txt")
        message = template.render({"page": page, "view_url": view_url})
        notifier = config.get_notifier()
        notifier.send_notification("Scraped Wiki Ingestion", message)
    except Exception as e:
        print(f"Failed to post to Gotify: {e}")


# --- Background Tasks Routine ---


def run_bulk_description_maintenance() -> None:
    """Loops through historical page captures, prompting Ollama to rewrite pages

    lacking proper descriptions.
    """
    db = _get_db()
    if "fetched_pages" in db.table_names():
        # Read records into memory first to avoid holding locks during network LLM requests
        rows = list(db.execute_returning_dicts("SELECT * FROM fetched_pages"))
        for row in rows:
            desc = row.get("description", "")
            if not desc or "AI Processing skipped" in desc:
                try:
                    page_obj = HTMLPage(**row)
                    print(f"Running maintenance extraction for: {page_obj.url}")
                    wiki_text = extract_wiki_content(page_obj)
                    db["fetched_pages"].update(page_obj.url, {"description": wiki_text})
                except Exception as e:
                    print(f"Failed background processing for {row.get('url')}: {e}")
                    continue


# --- Authentication & Access Routes ---


@app.get("/login", response_class=HTMLResponse)
def get_login_page(next: Optional[str] = Query(None)) -> HTMLResponse:
    """Serves the login page to the user.

    Returns:
        HTMLResponse: Rendered login page.
    """
    template = _jinja_env.get_template("login.j2.html")
    return HTMLResponse(content=template.render(is_admin=False, next=next))


@app.post("/login", response_model=None)
def handle_login(
    password: str = Form(...), next: Optional[str] = Form(None)
) -> HTMLResponse | RedirectResponse:
    """Processes credential inputs, establishing cookie session records on success.

    Args:
        password (str): Form password entry.
        next (str, optional): Target URL to redirect to after successful authentication.

    Returns:
        HTMLResponse | RedirectResponse: Redirection to target/home or error output page.
    """
    if password == config.admin_password:
        session_token = secrets.token_hex(32)
        ACTIVE_SESSIONS[session_token] = time.time() + SESSION_EXPIRATION_SECONDS

        redirect_target = next if next else "/"
        if redirect_target.startswith("http://") or redirect_target.startswith(
            "https://"
        ):
            parsed_next = urlparse(redirect_target)
            redirect_target = parsed_next.path
            if parsed_next.query:
                redirect_target += f"?{parsed_next.query}"
            if not redirect_target.startswith("/"):
                redirect_target = "/" + redirect_target

        response = RedirectResponse(url=redirect_target, status_code=303)
        response.set_cookie(
            key=COOKIE_NAME,
            value=session_token,
            httponly=True,
            samesite="lax",
            max_age=SESSION_EXPIRATION_SECONDS,
        )
        return response

    return HTMLResponse(
        content=_jinja_env.get_template("login.j2.html").render(
            error="Invalid security credentials.", is_admin=False, next=next
        )
    )


# --- UNPROTECTED PUBLIC ROUTES (Accessible to Anyone) ---


@app.get("/", response_class=HTMLResponse)
@app.get("/pages", response_class=HTMLResponse)
def view_all_pages(request: Request, q: Optional[str] = Query(None)) -> HTMLResponse:
    """Lists historically captured records, showing parsed title tags or links.

    Returns:
        HTMLResponse: Grid page list.
    """
    db = _get_db()
    pages_list = []
    if "fetched_pages" in db.table_names():
        if q:
            rows = db.execute_returning_dicts(
                "SELECT * FROM fetched_pages WHERE title LIKE ? OR tags LIKE ? ORDER BY ROWID DESC",
                [f"%{q}%", f"%{q}%"],
            )
        else:
            rows = db.execute_returning_dicts(
                "SELECT * FROM fetched_pages ORDER BY ROWID DESC"
            )
        for row in rows:
            try:
                pages_list.append(HTMLPage(**row))
            except Exception as e:
                # Log issues but try to continue loading other rows
                print(f"Database row validation error: {e}")
                continue

    # Check if user is logged in as an administrator
    clear_expired_tokens()
    token = request.cookies.get(COOKIE_NAME)
    is_admin = token in ACTIVE_SESSIONS and ACTIVE_SESSIONS[token] >= time.time()

    template = _jinja_env.get_template("pages_list.j2.html")
    return HTMLResponse(
        content=template.render(pages=pages_list, is_admin=is_admin, q=q or "")
    )


@app.get("/view/page", response_class=HTMLResponse)
def view_saved_page(
    request: Request,
    url: str = Query(...),
    version_id: Optional[int] = Query(None),
    msg: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
) -> HTMLResponse:
    """Renders the AI-cleaned or raw markdown page view as rendered HTML.

    Args:
        request (Request): FastAPI request context.
        url (str): Key matching requested page.
        version_id (int, optional): Specific version ID to load.
        msg (str, optional): Alert message.
        error (str, optional): Alert error message.

    Returns:
        HTMLResponse: Formatted document output.
    """
    db = _get_db()
    decoded_url = unquote_plus(url)
    page_obj = None

    if version_id:
        try:
            row = db["page_versions"].get(int(version_id))
            page_obj = HTMLPage(**row)
        except (sqlite_utils.db.NotFoundError, ValueError):
            pass

    if not page_obj:
        try:
            row = db["fetched_pages"].get(decoded_url)
            page_obj = HTMLPage(**row)
        except sqlite_utils.db.NotFoundError:
            return HTMLResponse(
                content="<h1>Wiki Article Profile Missing</h1>", status_code=404
            )

    # Check if user is logged in as an administrator
    clear_expired_tokens()
    token = request.cookies.get(COOKIE_NAME)
    is_admin = token in ACTIVE_SESSIONS and ACTIVE_SESSIONS[token] >= time.time()

    current_fetched_at = None
    try:
        current_row = db["fetched_pages"].get(decoded_url)
        current_fetched_at = current_row.get("fetched_at")
    except sqlite_utils.db.NotFoundError:
        pass

    versions = []
    if "page_versions" in db.table_names():
        versions = list(
            db["page_versions"].rows_where("url = ? ORDER BY id ASC", [decoded_url])
        )

    similar_pages = get_similar_articles(db, decoded_url)

    rendered_wiki_html = markdown.markdown(
        page_obj.description or "", extensions=["fenced_code", "tables"]
    )
    template = _jinja_env.get_template("view_page.j2.html")
    return HTMLResponse(
        content=template.render(
            page=page_obj,
            rendered_wiki_html=rendered_wiki_html,
            is_admin=is_admin,
            versions=versions,
            active_version_id=version_id,
            current_fetched_at=current_fetched_at,
            msg=msg,
            error=error,
            similar_pages=similar_pages,
        )
    )


# --- PROTECTED ADMIN ROUTES (Passphrase Required) ---


@app.get("/import", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
def get_import_url_page() -> HTMLResponse:
    """Serves the primary admin entry page where URL import strings can be submitted.

    Returns:
        HTMLResponse: Ingestion form.
    """
    template = _jinja_env.get_template("url_import.j2.html")
    return HTMLResponse(content=template.render(is_admin=True))


@app.get("/import/shared-url", dependencies=[Depends(verify_auth)], response_model=None)
def handle_incoming_mobile_share(
    request: Request,
    url: Optional[str] = Query(None),
    text: Optional[str] = Query(None),
) -> RedirectResponse | HTMLResponse:
    """Filters incoming share targets from mobile actions and displays a prefilled import form.

    Args:
        request (Request): Share request context.
        url (str, optional): Shared URL directly.
        text (str, optional): Additional text matching the shared payload.

    Returns:
        RedirectResponse | HTMLResponse: Redirection or prefilled form template.
    """
    target_link = url or text
    if not target_link:
        return RedirectResponse(url="/import")

    target_link = extract_first_url(target_link)

    template = _jinja_env.get_template("url_import.j2.html")
    return HTMLResponse(
        content=template.render(prefilled_url=target_link, is_admin=True)
    )


@app.post("/import/url", dependencies=[Depends(verify_auth)], response_model=None)
def handle_url_import(
    request: Request, url: str = Form(...)
) -> HTMLResponse | RedirectResponse:
    """Processes URL ingestion, downloads content, rewrites with LLM, and logs to database.

    Args:
        request (Request): Origin web request context.
        url (str): Ingestion link.

    Returns:
        HTMLResponse | RedirectResponse: Redirection to article view on success.
    """
    db = _get_db()
    url = extract_first_url(url)
    try:
        page_data = fetch_url(url)
    except RuntimeError as e:
        # Show error feedback directly in form
        return HTMLResponse(
            content=_jinja_env.get_template("url_import.j2.html").render(
                error_message=str(e), prefilled_url=url, is_admin=True
            )
        )

    wiki_entry = extract_wiki_content(page_data)
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
    tags = extract_tags_content(page_data)
    page_data.tags = tags

    base_url = str(request.base_url).rstrip("/")
    view_url = f"{base_url}/view/page?url={page_data.safe_url}"

    # Dump Pydantic details as JSON strings to fit sqlite schema
    serialized = page_data.model_dump()
    serialized["links"] = json.dumps(serialized["links"])
    serialized["keywords"] = json.dumps(serialized["keywords"])
    serialized["tags"] = json.dumps(serialized["tags"])

    db["fetched_pages"].upsert(serialized, pk="url")
    update_article_embedding(db, page_data.url)
    post_to_gotify(page_data, view_url)
    return RedirectResponse(url=view_url, status_code=303)


@app.get("/admin", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
def get_admin_dashboard(msg: Optional[str] = Query(None)) -> HTMLResponse:
    """Serves the admin page containing DB backups, imports, and maintenance triggers.

    Args:
        msg (str, optional): Feedback string from async executions.

    Returns:
        HTMLResponse: Admin interface page.
    """
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


@app.post("/admin/config", dependencies=[Depends(verify_auth)], response_model=None)
def handle_config_update(
    ollama_host: str = Form(...),
    ollama_model: str = Form(...),
    ollama_embedding_model: str = Form(...),
    api_key: str = Form(None),
    gotify_url: str = Form(None),
    gotify_token: str = Form(None),
    wiki_prompt: str = Form(...),
) -> RedirectResponse:
    """Saves updated server settings (Ollama and Gotify parameters) to config file.

    Args:
        ollama_host (str): host endpoint.
        ollama_model (str): LLM model name.
        ollama_embedding_model (str): embedding model name.
        api_key (str): Chrome extension credential.
        gotify_url (str): Gotify url endpoint.
        gotify_token (str): Gotify application token.
        wiki_prompt (str): System prompt.

    Returns:
        RedirectResponse: Redirection to admin panel with success feedback message.
    """
    config.ollama_host = ollama_host
    config.ollama_model = ollama_model
    config.ollama_embedding_model = ollama_embedding_model
    config.api_key = api_key
    config.gotify_url = gotify_url or None
    config.gotify_token = gotify_token or None
    config.wiki_prompt = wiki_prompt
    config.save()

    return RedirectResponse(
        url="/admin?msg=Configurations+successfully+saved+and+reloaded.",
        status_code=303,
    )


@app.post("/admin/test-gotify", dependencies=[Depends(verify_auth)])
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


@app.post("/admin/test-ollama", dependencies=[Depends(verify_auth)])
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
        import ollama

        client = ollama.Client(host=ollama_host)
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


@app.post(
    "/admin/regenerate/wiki", dependencies=[Depends(verify_auth)], response_model=None
)
def handle_regenerate_wiki(url: str = Query(...)) -> RedirectResponse:
    """Triggers the Ollama wiki page re-generation process for a page.

    Args:
        url (str): target article URL.

    Returns:
        RedirectResponse: Redirects to the viewing portal.
    """
    db = _get_db()
    decoded_url = unquote_plus(url)
    try:
        row = db["fetched_pages"].get(decoded_url)
        page_obj = HTMLPage(**row)
    except sqlite_utils.db.NotFoundError:
        raise HTTPException(status_code=404, detail="Ingested page profile missing.")

    wiki_entry = extract_wiki_content(page_obj)

    title = page_obj.title or page_obj.url
    if wiki_entry.strip().startswith("#"):
        first_line = wiki_entry.strip().split("\n")[0]
        title = first_line.replace("#", "").strip()

    db["fetched_pages"].update(decoded_url, {"description": wiki_entry, "title": title})
    update_article_embedding(db, decoded_url)
    return RedirectResponse(
        url=f"/view/page?url={quote_plus(decoded_url)}", status_code=303
    )


@app.post(
    "/admin/regenerate/tags", dependencies=[Depends(verify_auth)], response_model=None
)
def handle_regenerate_tags(url: str = Query(...)) -> RedirectResponse:
    """Triggers the Ollama tags extraction routine for a page.

    Args:
        url (str): target article URL.

    Returns:
        RedirectResponse: Redirects to the viewing portal.
    """
    db = _get_db()
    decoded_url = unquote_plus(url)
    try:
        row = db["fetched_pages"].get(decoded_url)
        page_obj = HTMLPage(**row)
    except sqlite_utils.db.NotFoundError:
        raise HTTPException(status_code=404, detail="Ingested page profile missing.")

    tags = extract_tags_content(page_obj)
    db["fetched_pages"].update(decoded_url, {"tags": json.dumps(tags)})
    update_article_embedding(db, decoded_url)
    return RedirectResponse(
        url=f"/view/page?url={quote_plus(decoded_url)}", status_code=303
    )


@app.post(
    "/admin/update/tags", dependencies=[Depends(verify_auth)], response_model=None
)
def handle_update_tags(
    url: str = Form(...), tags_csv: str = Form(...)
) -> RedirectResponse:
    """Receives manually configured tags list from UI form and logs to database.

    Args:
        url (str): target page URL.
        tags_csv (str): Comma separated tag labels.

    Returns:
        RedirectResponse: Redirects to the viewing portal.
    """
    db = _get_db()
    tags = [t.strip().lower() for t in tags_csv.split(",") if t.strip()]
    db["fetched_pages"].update(url, {"tags": json.dumps(tags)})
    update_article_embedding(db, url)
    return RedirectResponse(url=f"/view/page?url={quote_plus(url)}", status_code=303)


@app.get("/logout")
def handle_logout() -> RedirectResponse:
    """Clears session state authentication credentials."""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.post(
    "/admin/change-password", dependencies=[Depends(verify_auth)], response_model=None
)
def handle_change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
) -> RedirectResponse:
    """Validates the current password and saves a new admin passcode."""
    if current_password != config.admin_password:
        return RedirectResponse(
            url="/admin?msg=Error:+Current+password+is+incorrect.",
            status_code=303,
        )

    config.admin_password = new_password
    config.save()
    return RedirectResponse(
        url="/admin?msg=Password+successfully+updated.",
        status_code=303,
    )


@app.post(
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
    except sqlite_utils.db.NotFoundError:
        pass

    # Process and clean the newly fetched content
    wiki_entry = extract_wiki_content(page_data)
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
    tags = extract_tags_content(page_data)
    page_data.tags = tags

    # Write back the current latest details
    serialized = page_data.model_dump()
    serialized["links"] = json.dumps(serialized["links"])
    serialized["keywords"] = json.dumps(serialized["keywords"])
    serialized["tags"] = json.dumps(serialized["tags"])

    db["fetched_pages"].upsert(serialized, pk="url")
    update_article_embedding(db, decoded_url)

    # Send notifier alerts
    base_url = str(request.base_url).rstrip("/")
    view_url = f"{base_url}/view/page?url={page_data.safe_url}"
    post_to_gotify(page_data, view_url)

    return RedirectResponse(
        url=f"/view/page?url={quote_plus(decoded_url)}&msg=Source+page+successfully+re-fetched+and+new+version+created.",
        status_code=303,
    )


@app.post(
    "/admin/delete/page", dependencies=[Depends(verify_auth)], response_model=None
)
def handle_delete_page(url: str = Form(...)) -> RedirectResponse:
    """Deletes an ingested page profile and all its archived versions from the database.

    Args:
        url (str): target page URL to remove.

    Returns:
        RedirectResponse: Redirection back to main archive library list.
    """
    db = _get_db()
    try:
        db["fetched_pages"].delete(url)
        if "page_versions" in db.table_names():
            db.execute("DELETE FROM page_versions WHERE url = ?", [url])
        if "article_embeddings" in db.table_names():
            db.execute("DELETE FROM article_embeddings WHERE url = ?", [url])
        print(
            f"Administrative Delete: Removed {url} and all archived versions/embeddings from database."
        )
    except sqlite_utils.db.NotFoundError:
        raise HTTPException(status_code=404, detail="Target page profile not found.")
    return RedirectResponse(url="/", status_code=303)


@app.post("/admin/trigger-describe", dependencies=[Depends(verify_auth)])
def trigger_bulk_description(background_tasks: BackgroundTasks) -> RedirectResponse:
    """Initiates an asynchronous background job processing pages missing LLM descriptions.

    Args:
        background_tasks (BackgroundTasks): FastAPI async stack helper.

    Returns:
        RedirectResponse: Redirection to admin panel.
    """
    background_tasks.add_task(run_bulk_description_maintenance)
    return RedirectResponse(
        url="/admin?msg=Background+AI+maintenance+processing+loop+successfully+initiated.",
        status_code=303,
    )


@app.get("/admin/export", dependencies=[Depends(verify_auth)], response_model=None)
async def export_database() -> JSONResponse | StreamingResponse:
    """Generates and streams out database contents as a downloadable JSON file.

    Returns:
        StreamingResponse: Chunked JSON output.
    """
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


@app.websocket("/admin/ws/import", dependencies=[Depends(verify_auth)])
async def websocket_import(websocket: WebSocket) -> None:
    """Accepts chunks of JSON file imports over a WebSocket connection.

    Parses data and writes entries back to the database.

    Args:
        websocket (WebSocket): WebSocket stream socket.
    """
    await websocket.accept()

    # WebSocket Cookie-based authentication check
    token = websocket.cookies.get(COOKIE_NAME)
    if not token or token not in ACTIVE_SESSIONS:
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

        # Assemble and deserialize
        full_json = "".join(data_chunks)
        records = json.loads(full_json)

        db = _get_db()
        success_count = 0
        for record in records:
            try:
                # Standardize structures using Pydantic validation
                page_obj = HTMLPage(**record)
                serialized = page_obj.model_dump()
                serialized["links"] = json.dumps(serialized["links"])
                serialized["keywords"] = json.dumps(serialized["keywords"])
                serialized["tags"] = json.dumps(serialized["tags"])
                db["fetched_pages"].upsert(serialized, pk="url")
                success_count += 1
            except Exception as e:
                print(
                    f"Skipping record {record.get('url')} due to validation error: {e}"
                )

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


# --- SPECIFIC API ENDPOINT FOR BROWSER EXTENSION ---


class HTMLImportPayload(BaseModel):
    url: str
    html_content: str
    title: Optional[str] = None


@app.post(
    "/api/import/html", dependencies=[Depends(verify_api_key)], response_model=None
)
def handle_html_import(payload: HTMLImportPayload, request: Request) -> dict:
    """Accepts raw HTML posts directly from browser extensions and processes them.

    Args:
        payload (HTMLImportPayload): Input parameters (url and HTML string).
        request (Request): FastAPI request context.

    Returns:
        dict: Ingestion success payload.
    """
    db = _get_db()
    try:
        html_content = payload.html_content
        url = payload.url

        h = HTML2Text()
        h.ignore_links = True
        md_content = h.handle(html_content)

        soup = BeautifulSoup(html_content, "html5lib")
        links = [a.get("href") for a in soup.find_all("a", href=True)]
        links = [urljoin(url, link) if link.startswith("/") else link for link in links]

        # Extract pre-assigned title or page default title tag if available
        title = payload.title
        if not title and soup.title:
            title = soup.title.string
        if not title:
            title = urlparse(url).netloc or url

        page_data = HTMLPage(
            url=url,
            title=title,
            html_content=html_content,
            md_content=md_content,
            links=links,
            html_content_hash=hashlib.sha256(html_content.encode("utf-8")).hexdigest(),
            md_content_hash=hashlib.sha256(md_content.encode("utf-8")).hexdigest(),
            fetched_at=datetime.now().isoformat(),
            description="",
            keywords=[],
            tags=[],
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse page HTML: {e}")

    # Ingest wiki summary using LLM
    wiki_entry = extract_wiki_content(page_data)
    page_data.description = wiki_entry

    # Extract title from markdown H1 if available
    if wiki_entry.strip().startswith("#"):
        first_line = wiki_entry.strip().split("\n")[0]
        title = first_line.replace("#", "").strip()

    page_data.title = title

    # Automatically generate tags
    tags = extract_tags_content(page_data)
    page_data.tags = tags

    base_url = str(request.base_url).rstrip("/")
    view_url = f"{base_url}/view/page?url={page_data.safe_url}"

    # Dump properties to database
    serialized = page_data.model_dump()
    serialized["links"] = json.dumps(serialized["links"])
    serialized["keywords"] = json.dumps(serialized["keywords"])
    serialized["tags"] = json.dumps(serialized["tags"])

    db["fetched_pages"].upsert(serialized, pk="url")
    update_article_embedding(db, page_data.url)

    # Send dynamic Gotify push notification using the configured settings
    post_to_gotify(page_data, view_url)

    return {"status": "success", "url": url, "view_url": view_url}


@app.post(
    "/api/import/page", dependencies=[Depends(verify_api_key)], response_model=None
)
def handle_page_import(payload: HTMLPage, request: Request) -> dict:
    """Accepts full HTMLPage Pydantic payloads (e.g. from kb-rss) and processes/saves them."""
    db = _get_db()

    # If title is missing or generic, determine one
    if not payload.title:
        title = payload.url
        soup = BeautifulSoup(payload.html_content, "html5lib")
        if soup.title:
            title = soup.title.string
        if not title:
            title = urlparse(payload.url).netloc or payload.url
        payload.title = title

    # Generate description if empty
    if not payload.description:
        wiki_entry = extract_wiki_content(payload)
        payload.description = wiki_entry

        # Extract title from H1 if it was just generated
        if wiki_entry.strip().startswith("#"):
            first_line = wiki_entry.strip().split("\n")[0]
            payload.title = first_line.replace("#", "").strip()

    # Generate tags if empty
    if not payload.tags:
        payload.tags = extract_tags_content(payload)

    base_url = str(request.base_url).rstrip("/")
    view_url = f"{base_url}/view/page?url={payload.safe_url}"

    # Dump properties to database
    serialized = payload.model_dump()
    serialized["links"] = json.dumps(serialized["links"])
    serialized["keywords"] = json.dumps(serialized["keywords"])
    serialized["tags"] = json.dumps(serialized["tags"])

    db["fetched_pages"].upsert(serialized, pk="url")
    update_article_embedding(db, payload.url)

    # Send dynamic Gotify push notification
    post_to_gotify(payload, view_url)

    return {"status": "success", "url": payload.url, "view_url": view_url}


# --- Similarity Embeddings, Tags Listing, and Maintenance Pipelines ---


def ensure_model_available(client: ollama.Client, model_name: str) -> None:
    """Checks if the requested model is present in Ollama locally, pulling it if missing."""
    try:
        models_response = client.list()
        existing_models = []
        if isinstance(models_response, dict):
            models_list = models_response.get("models", [])
            for m in models_list:
                if isinstance(m, dict):
                    existing_models.append(m.get("name", ""))
                else:
                    existing_models.append(str(m))
        elif hasattr(models_response, "models"):
            for m in models_response.models:
                if hasattr(m, "model"):
                    existing_models.append(m.model)
                elif hasattr(m, "name"):
                    existing_models.append(m.name)
        else:
            existing_models = [str(m) for m in models_response]

        # Standardize matching to check tag presence
        if (
            model_name not in existing_models
            and f"{model_name}:latest" not in existing_models
        ):
            print(f"Ollama model '{model_name}' not found locally. Initiating pull...")
            client.pull(model_name)
            print(f"Successfully pulled Ollama model '{model_name}'")
    except Exception as e:
        print(f"Failed to automatically pull Ollama model '{model_name}': {e}")


def update_article_embedding(db, url: str) -> None:
    """Generates embedding for the article and saves/updates it in the database."""
    try:
        row = db["fetched_pages"].get(url)
        tags_json = row.get("tags") or "[]"
        try:
            tags = json.loads(tags_json)
        except Exception:
            tags = []
        description = row.get("description") or ""

        text_to_embed = f"Tags: {', '.join(tags)}\n\nDescription: {description}"
        if not text_to_embed.strip():
            return

        client = _get_ollama_client()
        emb_model = getattr(config, "ollama_embedding_model", "nomic-embed-text")

        ensure_model_available(client, emb_model)

        try:
            response = client.embeddings(model=emb_model, prompt=text_to_embed[:4000])
            embedding = response["embedding"]
        except Exception as e:
            print(
                f"Ollama embedding with model '{emb_model}' failed: {e}. Trying main model '{config.ollama_model}'..."
            )
            ensure_model_available(client, config.ollama_model)
            response = client.embeddings(
                model=config.ollama_model, prompt=text_to_embed[:4000]
            )
            embedding = response["embedding"]

        db["article_embeddings"].upsert(
            {
                "url": url,
                "embedding": json.dumps(embedding),
                "updated_at": datetime.now().isoformat(),
            },
            pk="url",
        )
        print(f"Successfully generated and stored embedding for: {url}")
    except Exception as e:
        print(f"Failed to generate embedding for {url}: {e}")


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Computes the cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    magnitude_v1 = math.sqrt(sum(a * a for a in v1))
    magnitude_v2 = math.sqrt(sum(a * a for a in v2))
    if magnitude_v1 == 0.0 or magnitude_v2 == 0.0:
        return 0.0
    return dot_product / (magnitude_v1 * magnitude_v2)


def get_similar_articles(db, current_url: str, limit: int = 5) -> list[dict]:
    """Calculates cosine similarity between current_url and all other articles.

    Returns:
        list[dict]: List of similar articles with title, url, tags, similarity score.
    """
    try:
        if "article_embeddings" not in db.table_names():
            return []

        try:
            current_row = db["article_embeddings"].get(current_url)
            current_emb = json.loads(current_row["embedding"])
        except (sqlite_utils.db.NotFoundError, ValueError, KeyError):
            return []

        all_embeddings = list(db["article_embeddings"].rows)
        similarities = []

        for row in all_embeddings:
            other_url = row["url"]
            if other_url == current_url:
                continue

            try:
                other_emb = json.loads(row["embedding"])
                similarity = cosine_similarity(current_emb, other_emb)

                page_row = db["fetched_pages"].get(other_url)
                tags_json = page_row.get("tags") or "[]"
                try:
                    tags = json.loads(tags_json)
                except Exception:
                    tags = []

                similarities.append(
                    {
                        "url": other_url,
                        "title": page_row.get("title") or other_url,
                        "tags": tags,
                        "similarity": round(similarity * 100, 1),
                    }
                )
            except Exception:
                continue

        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        return similarities[:limit]
    except Exception as e:
        print(f"Error computing similar articles: {e}")
        return []


def run_bulk_embedding_maintenance() -> None:
    """Loops through all fetched pages, generating embeddings for any that are missing."""
    db = _get_db()
    if "fetched_pages" in db.table_names():
        rows = list(db.execute_returning_dicts("SELECT url FROM fetched_pages"))
        for row in rows:
            url = row["url"]
            exists = False
            if "article_embeddings" in db.table_names():
                try:
                    db["article_embeddings"].get(url)
                    exists = True
                except sqlite_utils.db.NotFoundError:
                    pass

            if not exists:
                update_article_embedding(db, url)


@app.post("/admin/trigger-embeddings", dependencies=[Depends(verify_auth)])
def trigger_bulk_embeddings(background_tasks: BackgroundTasks) -> RedirectResponse:
    """Initiates an asynchronous background job generating missing article embeddings."""
    background_tasks.add_task(run_bulk_embedding_maintenance)
    return RedirectResponse(
        url="/admin?msg=Background+embedding+generation+loop+successfully+initiated.",
        status_code=303,
    )


@app.get("/tags", response_class=HTMLResponse)
def view_tags(request: Request, tag: Optional[str] = Query(None)) -> HTMLResponse:
    """Renders all tags with counts, and allows filtering articles by a selected tag."""
    db = _get_db()

    # Retrieve all tags and compute counts
    tag_counts = {}
    if "fetched_pages" in db.table_names():
        rows = db.execute_returning_dicts("SELECT tags FROM fetched_pages")
        for row in rows:
            tags_json = row.get("tags")
            if tags_json:
                try:
                    tags = json.loads(tags_json)
                    for t in tags:
                        t = t.strip().lower()
                        if t:
                            tag_counts[t] = tag_counts.get(t, 0) + 1
                except Exception:
                    continue

    # Sort tags by count descending, then alphabetically
    sorted_tags = dict(sorted(tag_counts.items(), key=lambda x: (-x[1], x[0])))

    # Filter pages by selected tag
    pages_list = []
    if tag:
        tag_lower = tag.strip().lower()
        if "fetched_pages" in db.table_names():
            rows = db.execute_returning_dicts(
                "SELECT * FROM fetched_pages ORDER BY ROWID DESC"
            )
            for row in rows:
                tags_json = row.get("tags")
                if tags_json:
                    try:
                        tags = json.loads(tags_json)
                        if any(t.strip().lower() == tag_lower for t in tags):
                            pages_list.append(HTMLPage(**row))
                    except Exception:
                        continue

    # Check if user is logged in as an administrator
    clear_expired_tokens()
    token = request.cookies.get(COOKIE_NAME)
    is_admin = token in ACTIVE_SESSIONS and ACTIVE_SESSIONS[token] >= time.time()

    template = _jinja_env.get_template("tags.j2.html")
    return HTMLResponse(
        content=template.render(
            tags_with_counts=sorted_tags,
            selected_tag=tag,
            pages=pages_list,
            is_admin=is_admin,
        )
    )
