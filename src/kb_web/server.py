from datetime import datetime
import hashlib
import json
import os
import secrets
import time
from typing import Optional, AsyncGenerator
from urllib.parse import urlparse, urljoin, quote_plus, unquote_plus

from fastapi import (
    FastAPI,
    Form,
    Request,
    Query,
    Depends,
    HTTPException,
    BackgroundTasks,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    JSONResponse,
    StreamingResponse,
)
from html2text import HTML2Text
import httpx
import jinja2
import markdown
import ollama
from bs4 import BeautifulSoup  # type: ignore

from .config import Config
from .db import get_db
from .models import HTMLPage

app = FastAPI(title="Knowledge Base Web Importer")

# Instantiate configuration and load shared DB
config = Config()

# Set up Jinja2 environment utilizing PackageLoader for clean packaging
_jinja_env = jinja2.Environment(loader=jinja2.PackageLoader("kb_web", "templates"))

# Set up Ollama Client using configured host
_client = ollama.Client(host=config.ollama_host)


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

COOKIE_NAME = "kb_session"
ACTIVE_SESSIONS: dict[str, float] = {}
SESSION_EXPIRATION_SECONDS = 3600 * 24  # 24 hours


def _get_db():
    """Helper dependency to retrieve a clean database handle.

    Returns:
        sqlite_utils.Database: Connection wrapper to ~/.kb/kb.db.
    """
    return get_db(config)


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
        # Redirect directly to login form
        raise HTTPException(status_code=303, headers={"Location": "/login"})


# --- Public Web Share Target Metadata Endpoints ---


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
                "src": "https://cdn-icons-png.flaticon.com/512/2232/2232688.png",
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
            html_content=html_content,
            md_content=md_content,
            links=links,
            html_content_hash=hashlib.sha256(html_content.encode("utf-8")).hexdigest(),
            md_content_hash=hashlib.sha256(md_content.encode("utf-8")).hexdigest(),
            fetched_at=datetime.now().isoformat(),
            description="",
            keywords=[],
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
    sys_prompt = (
        "You are an expert knowledge-base engineer. Extract the core informational content "
        "from the provided web page markdown and rewrite it as a clean, highly structured, "
        "and objective wiki entry. Strip out all ads, clickbait, sidebars, navigation links, cookie banners, "
        "and user comments. Keep only the valuable data, analysis, code blocks, or technical tutorials. "
        "Output ONLY the final markdown text. Do not reply with conversational filler headers."
    )
    try:
        response = _client.chat(
            model="gemma4:latest",
            messages=[
                {"role": "system", "content": sys_prompt},
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
def get_login_page() -> HTMLResponse:
    """Serves the login page to the user.

    Returns:
        HTMLResponse: Rendered login page.
    """
    template = _jinja_env.get_template("login.j2.html")
    return HTMLResponse(content=template.render())


@app.post("/login", response_model=None)
def handle_login(password: str = Form(...)) -> HTMLResponse | RedirectResponse:
    """Processes credential inputs, establishing cookie session records on success.

    Args:
        password (str): Form password entry.

    Returns:
        HTMLResponse | RedirectResponse: Redirection to home or error output page.
    """
    if password == config.admin_password:
        session_token = secrets.token_hex(32)
        ACTIVE_SESSIONS[session_token] = time.time() + SESSION_EXPIRATION_SECONDS

        response = RedirectResponse(url="/", status_code=303)
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
            error="Invalid security credentials."
        )
    )


# --- UNPROTECTED PUBLIC ROUTES (Accessible to Anyone) ---


@app.get("/pages", response_class=HTMLResponse)
def view_all_pages() -> HTMLResponse:
    """Lists historically captured records, showing parsed information tiles.

    Returns:
        HTMLResponse: Grid page list.
    """
    db = _get_db()
    pages_list = []
    if "fetched_pages" in db.table_names():
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

    template = _jinja_env.get_template("pages_list.j2.html")
    return HTMLResponse(content=template.render(pages=pages_list))


@app.get("/view/page", response_class=HTMLResponse)
def view_saved_page(url: str = Query(...)) -> HTMLResponse:
    """Renders the AI-cleaned or raw markdown page view as rendered HTML.

    Args:
        url (str): Key matching requested page.

    Returns:
        HTMLResponse: Formatted document output.
    """
    db = _get_db()
    decoded_url = unquote_plus(url)
    try:
        row = db["fetched_pages"].get(decoded_url)
        page_obj = HTMLPage(**row)
    except sqlite_utils.db.NotFoundError:
        return HTMLResponse(
            content="<h1>Wiki Article Profile Missing</h1>", status_code=404
        )

    rendered_wiki_html = markdown.markdown(
        page_obj.description or "", extensions=["fenced_code", "tables"]
    )
    template = _jinja_env.get_template("view_page.j2.html")
    return HTMLResponse(
        content=template.render(page=page_obj, rendered_wiki_html=rendered_wiki_html)
    )


# --- PROTECTED ADMIN ROUTES (Passphrase Required) ---


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
def get_import_url_page() -> HTMLResponse:
    """Serves the primary admin entry page where URL import strings can be submitted.

    Returns:
        HTMLResponse: Ingestion form.
    """
    template = _jinja_env.get_template("url_import.j2.html")
    return HTMLResponse(content=template.render())


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
        return RedirectResponse(url="/")

    # Filter out lead description text if any exists
    if "http" in target_link:
        start_idx = target_link.find("http")
        target_link = target_link[start_idx:].split()[0]

    template = _jinja_env.get_template("url_import.j2.html")
    return HTMLResponse(content=template.render(prefilled_url=target_link))


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
    try:
        page_data = fetch_url(url)
    except RuntimeError as e:
        # Show error feedback directly in form
        return HTMLResponse(
            content=_jinja_env.get_template("url_import.j2.html").render(
                error_message=str(e), prefilled_url=url
            )
        )

    wiki_entry = extract_wiki_content(page_data)
    page_data.description = wiki_entry

    base_url = str(request.base_url).rstrip("/")
    view_url = f"{base_url}/view/page?url={page_data.safe_url}"

    # Dump Pydantic details as JSON strings to fit sqlite schema
    serialized = page_data.model_dump()
    serialized["links"] = json.dumps(serialized["links"])
    serialized["keywords"] = json.dumps(serialized["keywords"])

    db["fetched_pages"].upsert(serialized, pk="url")
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
        content=template.render(unprocessed_count=count, completion_message=msg)
    )


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
