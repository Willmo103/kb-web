"""
Database-backed image caching and public asset synchronization for kb-web.

Caches external images referenced in ingested Markdown/HTML pages by their
SHA-256 binary hash, stores the binary payload in PostgreSQL (`cached_images`),
syncs them to the public `/static/cached_images` directory, and rewrites
article links to reference the local cached assets.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy.orm import Session

from .models_orm import CachedImage
from .utils import HEADERS, utc_now_iso, validate_target_url

STATIC_CACHED_IMAGES_DIR = Path(__file__).resolve().parent / "static" / "cached_images"
PUBLIC_IMAGE_URL_PREFIX = "/static/cached_images"

CONTENT_TYPE_TO_EXT: Dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/avif": "avif",
    "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
    "image/bmp": "bmp",
}

# Matches Markdown images: ![alt](url) or ![alt](url "title")
_MD_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)(\s+"[^"]*")?\)')
# Matches HTML <img ... src="..."> tags
_HTML_IMG_RE = re.compile(r'(<img\b[^>]*?\bsrc=)(["\'])([^"\']+)\2', re.IGNORECASE)


def _infer_extension(content_type: str, url: str) -> str:
    """Determines a safe file extension from Content-Type or URL path."""
    ct_clean = (content_type or "").split(";")[0].strip().lower()
    if ct_clean in CONTENT_TYPE_TO_EXT:
        return CONTENT_TYPE_TO_EXT[ct_clean]

    path = urlparse(url).path.lower()
    for ext in ("png", "jpg", "jpeg", "gif", "webp", "svg", "avif", "ico", "bmp"):
        if path.endswith(f".{ext}"):
            return "jpg" if ext == "jpeg" else ext
    return "png"


def ensure_image_on_disk(image_hash: str, extension: str, data: bytes) -> Path:
    """Writes image binary to static/cached_images/<hash>.<ext> if not present."""
    STATIC_CACHED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    target = STATIC_CACHED_IMAGES_DIR / f"{image_hash}.{extension}"
    if not target.exists():
        target.write_bytes(data)
    return target


def sync_cached_images_to_disk(session: Session) -> int:
    """Syncs all CachedImage rows from the database into static/cached_images/."""
    STATIC_CACHED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for row in session.query(CachedImage).yield_per(50):
        target = STATIC_CACHED_IMAGES_DIR / f"{row.image_hash}.{row.extension}"
        if not target.exists() and row.data:
            target.write_bytes(row.data)
            written += 1
    return written


def cache_image_from_url(
    image_url: str,
    session: Session,
    base_url: Optional[str] = None,
    max_bytes: int = 10485760,
    allow_internal: bool = False,
) -> Optional[str]:
    """Downloads an image, stores its binary in `cached_images` keyed by SHA-256,
    syncs it to `static/cached_images/`, and returns the public local URL path.
    """
    if not image_url or not isinstance(image_url, str):
        return None

    raw = image_url.strip()
    if not raw or raw.startswith(("data:", PUBLIC_IMAGE_URL_PREFIX, "#")):
        return None

    resolved_url = urljoin(base_url, raw) if base_url else raw
    parsed = urlparse(resolved_url)
    if parsed.scheme.lower() not in ("http", "https"):
        return None

    # Fast check: already cached by original_url
    existing_by_url = (
        session.query(CachedImage)
        .filter(CachedImage.original_url == resolved_url)
        .first()
    )
    if existing_by_url:
        ensure_image_on_disk(
            existing_by_url.image_hash,
            existing_by_url.extension,
            existing_by_url.data,
        )
        return f"{PUBLIC_IMAGE_URL_PREFIX}/{existing_by_url.image_hash}.{existing_by_url.extension}"

    try:
        validate_target_url(resolved_url, allow_internal=allow_internal)
    except ValueError:
        return None

    try:
        resp = httpx.get(
            resolved_url,
            timeout=15,
            follow_redirects=True,
            headers=HEADERS,
        )
        if resp.status_code != 200:
            return None
        data = resp.content
        if not data or len(data) > max_bytes:
            return None

        content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type and not content_type.startswith("image/"):
            return None
        if not content_type:
            content_type = "image/png"
    except Exception:
        return None

    image_hash = hashlib.sha256(data).hexdigest()
    ext = _infer_extension(content_type, resolved_url)

    existing_by_hash = (
        session.query(CachedImage)
        .filter(CachedImage.image_hash == image_hash)
        .first()
    )
    if not existing_by_hash:
        record = CachedImage(
            image_hash=image_hash,
            original_url=resolved_url,
            content_type=content_type,
            extension=ext,
            data=data,
            size_bytes=len(data),
            created_at=utc_now_iso(),
        )
        session.add(record)
        session.flush()
    else:
        ext = existing_by_hash.extension

    ensure_image_on_disk(image_hash, ext, data)
    return f"{PUBLIC_IMAGE_URL_PREFIX}/{image_hash}.{ext}"


def has_external_images(content: str) -> bool:
    """Returns True if markdown/HTML content contains external http(s) image links."""
    if not content:
        return False
    for match in _MD_IMAGE_RE.finditer(content):
        url = match.group(2).strip()
        if url.startswith(("http://", "https://")) or (
            not url.startswith(("data:", PUBLIC_IMAGE_URL_PREFIX, "/static/", "#"))
            and "://" not in url
        ):
            return True
    for match in _HTML_IMG_RE.finditer(content):
        url = match.group(3).strip()
        if url.startswith(("http://", "https://")):
            return True
    return False


def cache_and_rewrite_markdown_images(
    md_content: str,
    base_url: str,
    session: Session,
    max_bytes: int = 10485760,
    allow_internal: bool = False,
) -> Tuple[str, int]:
    """Finds all image URLs in Markdown/HTML content, caches them to DB & disk,
    and replaces the URLs with local `/static/cached_images/<hash>.<ext>` paths.
    """
    if not md_content:
        return md_content, 0

    url_map: Dict[str, str] = {}
    cached_count = 0

    def _resolve_and_cache(raw_url: str) -> str:
        nonlocal cached_count
        if raw_url in url_map:
            return url_map[raw_url]
        local_path = cache_image_from_url(
            raw_url,
            session=session,
            base_url=base_url,
            max_bytes=max_bytes,
            allow_internal=allow_internal,
        )
        if local_path:
            url_map[raw_url] = local_path
            cached_count += 1
            return local_path
        url_map[raw_url] = raw_url
        return raw_url

    def _replace_md(match: re.Match) -> str:
        alt = match.group(1)
        raw_url = match.group(2)
        title_part = match.group(3) or ""
        new_url = _resolve_and_cache(raw_url)
        return f"![{alt}]({new_url}{title_part})"

    def _replace_html(match: re.Match) -> str:
        prefix = match.group(1)
        quote = match.group(2)
        raw_url = match.group(3)
        new_url = _resolve_and_cache(raw_url)
        return f"{prefix}{quote}{new_url}{quote}"

    updated = _MD_IMAGE_RE.sub(_replace_md, md_content)
    updated = _HTML_IMG_RE.sub(_replace_html, updated)
    return updated, cached_count
