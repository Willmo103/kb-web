"""
Obsidian Vault ZIP Export engine for kb-web.

Exports all ingested web articles and YouTube transcripts (excluding Obsidian
notes `note://`) into a structured ZIP archive with:
  - `_sources/<site>/<dot.joined.path>.md` (raw scraped markdown + date_scraped & version)
  - `articles/<collection>/<site>/<title>.md` (AI wiki markdown + full frontmatter,
    Obsidian inline #tags below title, source link under `/_sources/`, and
    nearest-neighbor backlinks under `/reference/articles/`)
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import operator
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, quote, urlparse

from sqlalchemy.orm import Session

from .config import Config
from .models_orm import (
    ArticleEmbedding,
    ChunkEmbedding,
    Collection,
    CollectionItem,
    FetchedPage,
    PageVersion,
    WikiVersion,
)


def _sanitize_fs_segment(name: str, fallback: str = "untitled") -> str:
    """Sanitizes a directory or filename segment for Windows/macOS/Linux filesystems."""
    cleaned = re.sub(r'[\\/*?:"<>|\r\n\t]+', " ", (name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        return fallback
    return cleaned[:150].strip(" .") or fallback


def format_source_filename(url: str) -> str:
    """Formats URL path parts into `<'.'.join(parts)>.md`, handling root & query strings."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    base = ".".join(parts) if parts else "index"

    if parsed.query:
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            base = f"{base}.{qs['v'][0]}"
        else:
            qhash = hashlib.sha256(parsed.query.encode("utf-8")).hexdigest()[:8]
            base = f"{base}.{qhash}"

    safe_base = _sanitize_fs_segment(base, fallback="index")
    return f"{safe_base}.md"


def format_obsidian_inline_tag(tag: str) -> str:
    """Converts a tag string into a valid Obsidian inline `#tag` token."""
    cleaned = re.sub(r"[^\w/-]+", "-", (tag or "").strip().lstrip("#"))
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-/")
    return f"#{cleaned}" if cleaned else ""


def _parse_tags_list(raw_tags: Any) -> List[str]:
    if not raw_tags:
        return []
    if isinstance(raw_tags, list):
        return [str(t).strip() for t in raw_tags if str(t).strip()]
    if isinstance(raw_tags, str):
        try:
            loaded = json.loads(raw_tags)
            if isinstance(loaded, list):
                return [str(t).strip() for t in loaded if str(t).strip()]
        except json.JSONDecodeError:
            return [t.strip() for t in raw_tags.split(",") if t.strip()]
    return []


def _parse_vector(raw_vec: Any) -> Optional[List[float]]:
    if raw_vec is None:
        return None
    if isinstance(raw_vec, list):
        return [float(x) for x in raw_vec]
    if isinstance(raw_vec, str):
        try:
            loaded = json.loads(raw_vec)
            if isinstance(loaded, list):
                return [float(x) for x in loaded]
        except Exception:
            return None
    try:
        return [float(x) for x in raw_vec]
    except Exception:
        return None


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return dot / (n1 * n2)


def resolve_title_conflict(
    base_title: str,
    wiki_content: str,
    url: str,
    used_titles: Set[str],
    config: Optional[Config] = None,
    ollama_client: Any = None,
) -> str:
    """Resolves a duplicate article title by asking the LLM for a distinct title,
    falling back to a deterministic URL hash suffix if the model is unavailable.
    """
    if ollama_client is not None or config is not None:
        try:
            if ollama_client is None and config is not None:
                from ollama import Client

                ollama_client = Client(host=config.ollama_host, timeout=15)

            if ollama_client is not None:
                model = (
                    getattr(config, "ollama_model", "gemma4:latest")
                    if config
                    else "gemma4:latest"
                )
                snippet = (wiki_content or "")[:600]
                prompt = (
                    f"The title '{base_title}' is already used by another document in the vault. "
                    f"Generate a concise, unique, descriptive alternative title (3 to 8 words) for "
                    f"this article from {url}.\n\nContent snippet:\n{snippet}\n\n"
                    f"Respond ONLY with the new title text, without quotes or markdown formatting."
                )
                resp = ollama_client.chat(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                )
                candidate = ""
                if isinstance(resp, dict):
                    candidate = resp.get("message", {}).get("content", "").strip()
                elif hasattr(resp, "message") and hasattr(resp.message, "content"):
                    candidate = resp.message.content.strip()

                candidate = _sanitize_fs_segment(candidate.strip("\"'# "), fallback="")
                if candidate and candidate.lower() not in used_titles:
                    return candidate
        except Exception:
            pass

    short_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:6]
    candidate = _sanitize_fs_segment(f"{base_title} ({short_hash})")
    counter = 2
    while candidate.lower() in used_titles:
        candidate = _sanitize_fs_segment(f"{base_title} ({short_hash}-{counter})")
        counter += 1
    return candidate


def _yaml_escape(value: str) -> str:
    escaped = (value or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _encode_vault_link(path_str: str) -> str:
    """Percent-encodes spaces for valid Markdown links while keeping slashes intact."""
    return quote(path_str, safe="/.-_~")


def _normalize_vector(vec: List[float]) -> Optional[List[float]]:
    if not vec:
        return None
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return None
    return [x / norm for x in vec]


def build_obsidian_vault_zip(
    session: Session,
    config: Optional[Config] = None,
    ollama_client: Any = None,
    neighbor_k: Optional[int] = None,
    url_filter: Optional[List[str]] = None,
) -> bytes:
    """Builds an in-memory ZIP archive of the Obsidian vault export."""
    k = (
        neighbor_k
        if neighbor_k is not None
        else (getattr(config, "obsidian_export_neighbor_k", 5) if config else 5)
    )

    # 1. Load all non-note FetchedPages (articles + YouTube transcripts)
    query = session.query(FetchedPage).filter(~FetchedPage.url.startswith("note://"))
    if url_filter is not None:
        query = query.filter(FetchedPage.url.in_(url_filter))
    pages: List[FetchedPage] = query.order_by(FetchedPage.fetched_at.asc()).all()
    included_url_set = {p.url for p in pages}

    # 2. Load collections mapping
    collections_by_id: Dict[int, str] = {
        c.id: _sanitize_fs_segment(c.title or f"Collection {c.id}")
        for c in session.query(Collection.id, Collection.title).all()
    }
    url_to_collection: Dict[str, str] = {}
    if included_url_set:
        for src_id, col_id in (
            session.query(CollectionItem.source_id, CollectionItem.collection_id)
            .filter(CollectionItem.source_id.in_(included_url_set))
            .all()
        ):
            if src_id and col_id in collections_by_id:
                url_to_collection.setdefault(src_id, collections_by_id[col_id])

    # 3. Load PageVersion counts per URL
    version_counts: Dict[str, int] = {}
    if included_url_set:
        for (pv_url,) in (
            session.query(PageVersion.url)
            .filter(PageVersion.url.in_(included_url_set))
            .all()
        ):
            version_counts[pv_url] = version_counts.get(pv_url, 0) + 1

    # 4. Load latest WikiVersion per URL
    latest_wiki: Dict[str, WikiVersion] = {}
    if included_url_set:
        for wv in (
            session.query(WikiVersion)
            .filter(WikiVersion.url.in_(included_url_set))
            .order_by(WikiVersion.id.asc())
            .all()
        ):
            latest_wiki[wv.url] = wv

    # 5. Load normalized embeddings for nearest-neighbor backlinks (excluding notes)
    embeddings: Dict[str, List[float]] = {}
    if k > 0 and included_url_set:
        for ae_url, ae_vec in (
            session.query(ArticleEmbedding.url, ArticleEmbedding.embedding)
            .filter(ArticleEmbedding.url.in_(included_url_set))
            .all()
        ):
            vec = _parse_vector(ae_vec)
            unit = _normalize_vector(vec) if vec else None
            if unit:
                embeddings[ae_url] = unit

        # Fallback to averaged ChunkEmbeddings for URLs without ArticleEmbedding
        missing_urls = [u for u in included_url_set if u not in embeddings]
        if missing_urls:
            chunk_accum: Dict[str, List[List[float]]] = {}
            for src_url, raw_vec in (
                session.query(ChunkEmbedding.source_id, ChunkEmbedding.chunk_vector)
                .filter(ChunkEmbedding.source_id.in_(missing_urls))
                .all()
            ):
                vec = _parse_vector(raw_vec)
                if vec:
                    chunk_accum.setdefault(src_url, []).append(vec)
            for url, vecs in chunk_accum.items():
                if vecs:
                    dim = len(vecs[0])
                    avg = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
                    unit = _normalize_vector(avg)
                    if unit:
                        embeddings[url] = unit

    default_model = getattr(config, "ollama_model", "unknown") if config else "unknown"
    sources_subpath = (
        (getattr(config, "obsidian_sources_subpath", "_sources") or "_sources").strip("/")
        if config
        else "_sources"
    )
    articles_subpath = (
        (
            getattr(config, "obsidian_articles_subpath", "reference/articles")
            or "reference/articles"
        ).strip("/")
        if config
        else "reference/articles"
    )

    # Precompute target paths for every included page so backlinks resolve accurately
    page_records: List[Dict[str, Any]] = []
    used_titles_per_dir: Dict[Tuple[str, str], Set[str]] = {}
    used_source_paths: Set[str] = set()

    for page in pages:
        parsed = urlparse(page.url)
        site = _sanitize_fs_segment(
            parsed.netloc or "unknown-site", fallback="unknown-site"
        )
        col_name = (
            collections_by_id.get(page.collection_id)
            or url_to_collection.get(page.url)
            or "Uncategorized"
        )

        # Source path under _sources/<site>/<dot.joined.path>.md
        src_filename = format_source_filename(page.url)
        src_rel_path = f"_sources/{site}/{src_filename}"
        if src_rel_path.lower() in used_source_paths:
            short_h = hashlib.sha256(page.url.encode("utf-8")).hexdigest()[:6]
            stem = src_filename[:-3]
            src_filename = f"{stem}.{short_h}.md"
            src_rel_path = f"_sources/{site}/{src_filename}"
        used_source_paths.add(src_rel_path.lower())

        # Wiki content & model metadata
        wv = latest_wiki.get(page.url)
        wiki_md = (
            (wv.wiki_content if wv and wv.wiki_content else None)
            or page.description
            or ""
        )
        model_used = (
            (wv.model_name if wv and wv.model_name else None)
            or page.wiki_model
            or default_model
        )
        raw_title = (wv.title if wv and wv.title else None) or page.title or site
        clean_title = _sanitize_fs_segment(raw_title, fallback="Untitled Article")

        dir_key = (col_name.lower(), site.lower())
        used_in_dir = used_titles_per_dir.setdefault(dir_key, set())
        if clean_title.lower() in used_in_dir:
            clean_title = resolve_title_conflict(
                clean_title,
                wiki_md,
                page.url,
                used_in_dir,
                config=config,
                ollama_client=ollama_client,
            )
        used_in_dir.add(clean_title.lower())

        article_rel_path = f"articles/{col_name}/{site}/{clean_title}.md"
        obsidian_article_path = f"/{articles_subpath}/{col_name}/{site}/{clean_title}.md"
        obsidian_source_path = f"/{sources_subpath}/{site}/{src_filename}"

        page_records.append(
            {
                "page": page,
                "site": site,
                "collection": col_name,
                "title": clean_title,
                "src_rel_path": src_rel_path,
                "article_rel_path": article_rel_path,
                "obsidian_source_path": obsidian_source_path,
                "obsidian_article_path": obsidian_article_path,
                "wiki_md": wiki_md,
                "model_used": model_used,
                "version": version_counts.get(page.url, 0) + 1,
                "tags": _parse_tags_list(page.tags),
                "date_scraped": page.fetched_at or "",
            }
        )

    records_by_url: Dict[str, Dict[str, Any]] = {
        rec["page"].url: rec for rec in page_records
    }

    # Precompute top-K nearest neighbors for each URL with an embedding (grouped by dim)
    neighbors_by_url: Dict[str, List[Tuple[Dict[str, Any], float]]] = {}
    if k > 0 and embeddings:
        by_dim: Dict[int, List[str]] = {}
        for u, vec in embeddings.items():
            if u in records_by_url:
                by_dim.setdefault(len(vec), []).append(u)

        for dim, dim_urls in by_dim.items():
            for u in dim_urls:
                v_u = embeddings[u]
                scored: List[Tuple[Dict[str, Any], float]] = []
                for other_u in dim_urls:
                    if other_u == u:
                        continue
                    sim = sum(map(operator.mul, v_u, embeddings[other_u]))
                    if sim > 0.0:
                        scored.append((records_by_url[other_u], sim))
                scored.sort(key=lambda pair: pair[1], reverse=True)
                neighbors_by_url[u] = scored[:k]

    # Write ZIP archive
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rec in page_records:
            page = rec["page"]

            # 1. Write _sources/<site>/<dot.joined.path>.md
            source_frontmatter = (
                "---\n"
                f"url: {_yaml_escape(page.url)}\n"
                f"site: {_yaml_escape(rec['site'])}\n"
                f"date_scraped: {_yaml_escape(rec['date_scraped'])}\n"
                f"version: {rec['version']}\n"
                "---\n\n"
            )
            source_body = page.md_content or ""
            zf.writestr(rec["src_rel_path"], source_frontmatter + source_body)

            # 2. Write articles/<collection>/<site>/<title>.md
            tags_yaml = ""
            if rec["tags"]:
                tags_yaml = "tags:\n" + "".join(
                    f"  - {_yaml_escape(t)}\n" for t in rec["tags"]
                )
            else:
                tags_yaml = "tags: []\n"

            wiki_frontmatter = (
                "---\n"
                f"title: {_yaml_escape(rec['title'])}\n"
                f"url: {_yaml_escape(page.url)}\n"
                f"site: {_yaml_escape(rec['site'])}\n"
                f"collection: {_yaml_escape(rec['collection'])}\n"
                f"date_scraped: {_yaml_escape(rec['date_scraped'])}\n"
                f"model_used: {_yaml_escape(rec['model_used'])}\n"
                f"{tags_yaml}"
                "---\n\n"
            )

            inline_tags = " ".join(
                t for t in (format_obsidian_inline_tag(tag) for tag in rec["tags"]) if t
            )
            header_block = f"# {rec['title']}\n"
            if inline_tags:
                header_block += f"{inline_tags}\n"
            header_block += f"\n*Source: [{rec['src_rel_path']}]({_encode_vault_link(rec['obsidian_source_path'])})*\n\n"

            wiki_body = rec["wiki_md"].strip()
            # Avoid duplicating top-level H1 if wiki already starts with `# Title`
            if wiki_body.startswith("# "):
                first_nl = wiki_body.find("\n")
                if first_nl != -1:
                    wiki_body = wiki_body[first_nl + 1 :].lstrip()

            backlinks_block = ""
            neighbors = neighbors_by_url.get(page.url, [])
            if neighbors:
                lines = ["\n\n---\n\n## Related Articles\n"]
                for nb_rec, sim in neighbors:
                    link_target = _encode_vault_link(nb_rec["obsidian_article_path"])
                    lines.append(
                        f"- [{nb_rec['title']}]({link_target}) *(similarity: {sim:.3f})*"
                    )
                backlinks_block = "\n".join(lines) + "\n"

            full_article = wiki_frontmatter + header_block + wiki_body + backlinks_block
            zf.writestr(rec["article_rel_path"], full_article)

    return buf.getvalue()
