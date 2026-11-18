#!/usr/bin/env python3
"""
Standalone Webpage Fetcher & Markdown Extractor Script (Typer CLI).

Extracted from kb-web (pipeline.py, html_cleaner.py, utils.py, models.py).
Provides full URL validation, SSRF guardrails, HTTP fetching with custom headers,
boilerplate/script stripping, link extraction, and clean Markdown distillation.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import parse_qs, urljoin, urlparse, urlsplit

try:
    import httpx
except ImportError:
    httpx = None

try:
    from bs4 import BeautifulSoup, Comment, Tag
except ImportError:
    BeautifulSoup = None

try:
    from html2text import HTML2Text
except ImportError:
    HTML2Text = None

from pydantic import BaseModel, Field, field_validator
import typer


# ==============================================================================
# Domain Models & Classes
# ==============================================================================

class ParsedUrl(BaseModel):
    """Decomposed components of a URL."""
    scheme: str
    netloc: str
    path: Optional[str] = None
    fragments: Optional[str] = None
    query: Optional[str] = None
    port: Optional[int] = None
    hostname: Optional[str] = None

    @classmethod
    def from_url(cls, url: str) -> "ParsedUrl":
        parsed = urlparse(url)
        try:
            port = parsed.port
        except (ValueError, TypeError):
            port = None

        try:
            hostname = parsed.hostname
        except (ValueError, TypeError):
            hostname = None

        return cls(
            scheme=parsed.scheme,
            netloc=parsed.netloc,
            path=parsed.path,
            fragments=parsed.fragment,
            query=parsed.query,
            port=port,
            hostname=hostname,
        )


class HTMLPage(BaseModel):
    """Scraped and distilled web page representation."""
    url: str
    title: Optional[str] = None
    html_content: Optional[str] = ""
    md_content: Optional[str] = ""
    links: List[str] = Field(default_factory=list)
    html_content_hash: Optional[str] = ""
    md_content_hash: Optional[str] = ""
    fetched_at: Optional[str] = ""
    description: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    status_code: Optional[int] = 200
    content_length: Optional[int] = 0

    @field_validator("links", mode="before")
    @classmethod
    def ensure_links_list(cls, v: Any, info: Any) -> List[str]:
        url = ""
        if hasattr(info, "data") and isinstance(info.data, dict):
            url = info.data.get("url", "")
        if isinstance(v, str):
            try:
                links_list = json.loads(v)
                if isinstance(links_list, list):
                    return [
                        urljoin(url, link) if link.startswith("/") else link
                        for link in links_list
                    ]
            except json.JSONDecodeError:
                return [urljoin(url, v) if v.startswith("/") else v]
        elif isinstance(v, list):
            return [urljoin(url, str(link)) if str(link).startswith("/") else str(link) for link in v]
        return []


# ==============================================================================
# HTML Boilerplate Stripping & Sanitization
# ==============================================================================

BOILERPLATE_TAGS = [
    "script",
    "style",
    "noscript",
    "header",
    "nav",
    "footer",
    "aside",
    "svg",
    "form",
    "iframe",
    "button",
    "canvas",
    "dialog",
]

BOILERPLATE_ATTR_PATTERN = re.compile(
    r"(cookie|consent|banner|newsletter|sidebar|social-share|ad-|advertisement|popup|modal|breadcrumb|widget|share-buttons|flyout)",
    re.IGNORECASE,
)

PRIMARY_CONTAINER_TEXT_THRESHOLD = 250


def get_configured_html2text() -> HTML2Text:
    """Configures HTML2Text for dense, readable Markdown output without line-wrapping."""
    if HTML2Text is None:
        raise RuntimeError("html2text is required. Install with: pip install html2text")
    h = HTML2Text()
    h.body_width = 0  # Disable line wrapping at 78 columns
    h.ignore_links = False
    h.ignore_images = False
    h.ignore_emphasis = False
    h.protect_links = True
    h.wrap_links = False
    h.single_line_break = False
    h.skip_internal_links = True
    h.inline_links = True
    return h


def strip_boilerplate_elements(soup: BeautifulSoup) -> None:
    """Decomposes script, style, navigation, footer, and boilerplate elements in place."""
    # 1. Remove comments
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()

    # 2. Remove boilerplate tags
    for tag_name in BOILERPLATE_TAGS:
        for element in soup.find_all(tag_name):
            element.decompose()

    # 3. Remove common boilerplate containers by class / id
    for element in list(soup.find_all(True)):
        if getattr(element, "decomposed", False):
            continue
        classes = " ".join(element.get("class", [])) if isinstance(element.get("class"), list) else str(element.get("class", ""))
        el_id = str(element.get("id", ""))
        combined_attr = f"{classes} {el_id}"

        if element.name in ("html", "body", "main", "article"):
            continue

        if BOILERPLATE_ATTR_PATTERN.search(combined_attr):
            if not element.find(["article", "main"]):
                element.decompose()


def extract_primary_content_container(soup: BeautifulSoup) -> Tag:
    """Finds the most specific substantive article container (<article> or <main>)."""
    for article in soup.find_all("article"):
        if len(article.get_text(strip=True)) >= PRIMARY_CONTAINER_TEXT_THRESHOLD:
            return article

    for main in soup.find_all("main"):
        if len(main.get_text(strip=True)) >= PRIMARY_CONTAINER_TEXT_THRESHOLD:
            return main

    for role_el in soup.find_all(attrs={"role": re.compile(r"^(main|article)$", re.I)}):
        if len(role_el.get_text(strip=True)) >= PRIMARY_CONTAINER_TEXT_THRESHOLD:
            return role_el

    return soup.body or soup


# ==============================================================================
# WebpageFetcher Engine Class
# ==============================================================================

class WebpageFetcher:
    """
    Production-grade webpage fetcher with SSRF validation, boilerplate stripping,
    hyperlink extraction, and markdown conversion.
    """

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 kb-web/1.0"
    )

    HEADERS = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    }

    def __init__(self, timeout: int = 30, allow_internal: bool = False):
        self.timeout = timeout
        self.allow_internal = allow_internal

    @staticmethod
    def is_internal_ip(ip_str: str) -> bool:
        """Determines whether an IP address belongs to private or loopback ranges."""
        try:
            ip = ipaddress.ip_address(ip_str)
            return (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
            )
        except ValueError:
            return False

    def validate_url(self, url: str) -> None:
        """Validates the target URL to prevent SSRF against loopback or private networks."""
        if not url or not isinstance(url, str):
            raise ValueError("URL must be a non-empty string.")

        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme '{scheme}'. Only http and https are permitted.")

        hostname = parsed.hostname
        if not hostname:
            raise ValueError("URL must contain a valid hostname.")

        if self.allow_internal:
            return

        low_host = hostname.lower()
        if (
            low_host in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "metadata.google.internal")
            or low_host.endswith(".local")
            or low_host.endswith(".internal")
        ):
            raise ValueError(f"Fetching from internal host '{hostname}' is blocked for security.")

        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for _, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                if self.is_internal_ip(ip_str):
                    raise ValueError(f"Host '{hostname}' resolves to restricted internal IP '{ip_str}'.")
        except socket.gaierror:
            pass

    def extract_links(self, raw_html: str, base_url: str = "") -> List[str]:
        """
        Extracts all hyperlinks (<a> tags) from raw HTML BEFORE boilerplate removal.
        Resolves relative paths against base_url and discards javascript/anchor links.
        """
        if not raw_html or not raw_html.strip() or BeautifulSoup is None:
            return []

        soup = BeautifulSoup(raw_html, "html5lib" if "html5lib" in sys.modules else "html.parser")
        raw_links = [a.get("href") for a in soup.find_all("a", href=True)]
        resolved_links: List[str] = []
        seen: Set[str] = set()

        for href in raw_links:
            if not href:
                continue
            href = str(href).strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "data:", "sms:", "#")):
                continue
            if base_url:
                resolved = urljoin(base_url, href) if href.startswith("/") or "://" not in href else href
            else:
                resolved = href
            if resolved and resolved not in seen:
                seen.add(resolved)
                resolved_links.append(resolved)

        return resolved_links

    def html_to_markdown(self, raw_html: str) -> str:
        """Sanitizes raw HTML and converts the substantive container into clean Markdown."""
        if not raw_html or not raw_html.strip():
            return ""

        if BeautifulSoup is None:
            return raw_html

        soup = BeautifulSoup(raw_html, "html5lib" if "html5lib" in sys.modules else "html.parser")
        strip_boilerplate_elements(soup)
        primary_container = extract_primary_content_container(soup)
        cleaned_html = str(primary_container)

        h = get_configured_html2text()
        md_content = h.handle(cleaned_html)

        # Collapse excessive blank lines (3+ down to 2)
        md_content = re.sub(r"\n{3,}", "\n\n", md_content)
        return md_content.strip()

    def fetch(self, url: str) -> HTMLPage:
        """
        Downloads a webpage, extracts raw hyperlinks, strips boilerplate,
        converts to clean Markdown, and computes cryptographic hashes.
        """
        if httpx is None:
            raise RuntimeError("httpx is required. Install with: pip install httpx")
        if BeautifulSoup is None:
            raise RuntimeError("beautifulsoup4 is required. Install with: pip install beautifulsoup4 html5lib")

        self.validate_url(url)

        try:
            response = httpx.get(
                url,
                timeout=self.timeout,
                follow_redirects=True,
                headers=self.HEADERS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"HTTP error {e.response.status_code} fetching {url}") from e
        except Exception as e:
            raise RuntimeError(f"Connection error fetching {url}: {e}") from e

        html_content = response.text
        content_type = response.headers.get("content-type", "").lower()
        if "text" not in content_type and "html" not in content_type:
            raise RuntimeError(f"Target URL returned non-text content type: {content_type}")

        # 1. Extract hyperlinks from raw untouched HTML
        links = self.extract_links(html_content, base_url=url)

        # 2. Clean and convert to Markdown
        md_content = self.html_to_markdown(html_content)

        # 3. Extract title and description
        soup = BeautifulSoup(html_content, "html5lib" if "html5lib" in sys.modules else "html.parser")
        title = url
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        og_desc = ""
        meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        if meta_desc and meta_desc.get("content"):
            og_desc = meta_desc["content"].strip()

        # 4. Compute SHA-256 hashes
        html_hash = hashlib.sha256(html_content.encode("utf-8")).hexdigest()
        md_hash = hashlib.sha256(md_content.encode("utf-8")).hexdigest()

        return HTMLPage(
            url=str(response.url),
            title=title,
            html_content=html_content,
            md_content=md_content,
            links=links,
            html_content_hash=html_hash,
            md_content_hash=md_hash,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            description=og_desc or None,
            status_code=response.status_code,
            content_length=len(md_content),
        )


# ==============================================================================
# Typer CLI Application
# ==============================================================================

app = typer.Typer(
    help="CLI for fetching webpages, stripping boilerplate, and converting to clean Markdown.",
    no_args_is_help=True,
)


@app.command(name="fetch", help="Fetch a webpage, clean HTML, extract links, and convert to clean Markdown.")
def fetch_cmd(
    url: str = typer.Argument(..., help="Target URL to fetch (http or https)."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="File path to save the output (default: stdout)."
    ),
    markdown_only: bool = typer.Option(
        False, "--markdown-only", "-m", help="Print only clean Markdown content without headers or metadata."
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="Output complete structured JSON payload."
    ),
    allow_internal: bool = typer.Option(
        False, "--allow-internal", help="Allow loopback or internal private IP addresses (disables SSRF check)."
    ),
    timeout: int = typer.Option(
        30, "--timeout", "-t", help="HTTP connection timeout in seconds."
    ),
) -> None:
    """Downloads webpage content, strips boilerplate noise, and produces clean Markdown."""
    fetcher = WebpageFetcher(timeout=timeout, allow_internal=allow_internal)

    try:
        page = fetcher.fetch(url)
    except Exception as e:
        typer.secho(f"Error fetching {url}: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if markdown_only:
        output_text = page.md_content or ""
    elif json_output:
        output_text = json.dumps(page.model_dump(), indent=2)
    else:
        output_text = (
            f"# {page.title}\n"
            f"- URL: {page.url}\n"
            f"- Fetched At: {page.fetched_at}\n"
            f"- HTTP Status: {page.status_code}\n"
            f"- Extracted Links: {len(page.links)}\n"
            f"- Markdown Length: {page.content_length} chars\n\n"
            f"## Clean Markdown Content\n\n"
            f"{page.md_content}\n"
        )

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(output_text, encoding="utf-8")
        typer.secho(f"Successfully saved output to {output}", fg=typer.colors.GREEN)
    else:
        typer.echo(output_text)


@app.command(name="links", help="Extract and list all hyperlinks from a webpage without boilerplate filtering.")
def links_cmd(
    url: str = typer.Argument(..., help="Target URL to extract links from."),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="Output links as a JSON array."
    ),
    allow_internal: bool = typer.Option(
        False, "--allow-internal", help="Allow loopback or internal private IP addresses."
    ),
    timeout: int = typer.Option(
        30, "--timeout", "-t", help="HTTP connection timeout in seconds."
    ),
) -> None:
    """Scrapes raw HTML and extracts all resolved hyperlinks."""
    fetcher = WebpageFetcher(timeout=timeout, allow_internal=allow_internal)

    try:
        page = fetcher.fetch(url)
    except Exception as e:
        typer.secho(f"Error extracting links from {url}: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(json.dumps(page.links, indent=2))
    else:
        typer.secho(f"Found {len(page.links)} links on {url}:", fg=typer.colors.CYAN)
        for link in page.links:
            typer.echo(f"  - {link}")


@app.command(name="clean", help="Convert a local HTML file into clean Markdown using boilerplate removal.")
def clean_cmd(
    html_file: Path = typer.Argument(..., help="Path to local HTML file."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="File path to save the cleaned Markdown (default: stdout)."
    ),
) -> None:
    """Reads local HTML, removes boilerplate, and prints or saves clean Markdown."""
    if not html_file.exists():
        typer.secho(f"File not found: {html_file}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    raw_html = html_file.read_text(encoding="utf-8", errors="ignore")
    fetcher = WebpageFetcher()
    md_content = fetcher.html_to_markdown(raw_html)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(md_content, encoding="utf-8")
        typer.secho(f"Successfully cleaned and saved Markdown to {output}", fg=typer.colors.GREEN)
    else:
        typer.echo(md_content)


def main():
    # If the user passes a URL directly without a subcommand, default to 'fetch'
    known_commands = {"fetch", "links", "clean", "--help", "-h"}
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-") and sys.argv[1] not in known_commands:
        sys.argv.insert(1, "fetch")
    app()


if __name__ == "__main__":
    main()
