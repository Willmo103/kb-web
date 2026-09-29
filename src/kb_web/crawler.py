"""
Webpage link crawler, candidate discovery, and AI curation engine for kb-web.
"""

import json
import logging
import re
import time
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from .base import _get_ollama_client, config, db_session
from .models_orm import Collection, CollectionItem, FetchedPage
from .utils import (
    HEADERS,
    extract_first_url,
    get_url_basename,
    ingest_url_sync,
)

logger = logging.getLogger("kb_web")

# Common noise patterns to strip or filter out
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "ref_src",
    "fbclid",
    "gclid",
    "_hsenc",
    "_hsmi",
    "mc_cid",
    "mc_eid",
}

# Regex to detect foreign language path prefixes (e.g. /zh/, /zh-cn/, /es/, /ja/, /fr/, /de/, /pt-br/)
FOREIGN_LANG_REGEX = re.compile(
    r"^/(?:zh|zh-cn|zh-tw|ja|jp|es|es-es|fr|fr-fr|de|de-de|pt|pt-br|ru|ko|it|nl|pl|ar|tr|vi|id)/",
    re.IGNORECASE,
)


def normalize_url(base_url: str, href: str) -> Optional[str]:
    """Resolves relative links, strips fragment anchors and tracking parameters,

    and validates HTTP/HTTPS protocol schemes.
    """
    if not href:
        return None

    href = href.strip()
    if href.startswith(("javascript:", "mailto:", "tel:", "data:", "sms:", "#")):
        return None

    try:
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)

        if parsed.scheme.lower() not in ("http", "https"):
            return None

        # Filter tracking query parameters
        clean_query = ""
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=False)
            filtered_params = {
                k: v for k, v in params.items() if k.lower() not in TRACKING_PARAMS
            }
            if filtered_params:
                clean_query = urlencode(filtered_params, doseq=True)

        # Normalize path: strip redundant trailing slashes for non-root paths
        path = parsed.path
        if path.endswith("/") and len(path) > 1:
            path = path[:-1]

        # Reconstruct clean URL without fragment
        clean_url = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path or "/",
            "",
            clean_query,
            "",
        ))
        return clean_url
    except Exception:
        return None


def extract_candidate_links(
    seed_url: str,
    same_domain: bool = True,
    max_links: int = 250,
) -> dict:
    """Fetches a webpage, extracts all hyperlinks, normalizes and deduplicates them,

    and checks the database for existing ingested pages.
    """
    cleaned_seed = extract_first_url(seed_url)
    if not cleaned_seed:
        raise ValueError("Invalid seed URL provided.")

    try:
        response = httpx.get(
            cleaned_seed,
            headers=HEADERS,
            follow_redirects=True,
            timeout=15.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Server responded with status {e.response.status_code}")
    except Exception as e:
        raise RuntimeError(f"Failed connecting to target server: {e}")

    content_type = response.headers.get("content-type", "").lower()
    if "text" not in content_type and "html" not in content_type:
        raise RuntimeError(f"Target URL returned non-HTML content ({content_type})")

    html = response.text
    soup = BeautifulSoup(html, "html5lib")

    # Extract page title
    page_title = ""
    if soup.title and soup.title.string:
        page_title = soup.title.string.strip()
    if not page_title:
        h1 = soup.find("h1")
        if h1:
            page_title = h1.get_text(strip=True)
    if not page_title:
        page_title = cleaned_seed

    seed_domain = get_url_basename(cleaned_seed)
    seed_normalized = normalize_url(cleaned_seed, cleaned_seed)

    raw_candidates = []
    seen_urls = set()
    if seed_normalized:
        seen_urls.add(seed_normalized)

    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href")
        clean_url = normalize_url(cleaned_seed, href)
        if not clean_url:
            continue

        if clean_url in seen_urls:
            continue

        target_domain = get_url_basename(clean_url)
        if same_domain and target_domain != seed_domain:
            continue

        anchor_text = a_tag.get_text(separator=" ", strip=True)
        # Fallback anchor text to title attribute or URL path
        if not anchor_text:
            anchor_text = a_tag.get("title", "").strip()
        if not anchor_text:
            parsed_path = urlparse(clean_url).path.strip("/")
            anchor_text = parsed_path.split("/")[-1] if parsed_path else clean_url

        # Truncate overly long anchor text
        if len(anchor_text) > 120:
            anchor_text = anchor_text[:117] + "..."

        seen_urls.add(clean_url)
        raw_candidates.append({
            "url": clean_url,
            "title": anchor_text,
            "domain": target_domain,
            "path": urlparse(clean_url).path,
        })

        if len(raw_candidates) >= max_links:
            break

    # Check database to see which candidate URLs are already ingested
    candidate_urls = [c["url"] for c in raw_candidates]
    existing_urls = set()
    if candidate_urls:
        with db_session() as session:
            rows = (
                session.query(FetchedPage.url)
                .filter(FetchedPage.url.in_(candidate_urls))
                .all()
            )
            existing_urls = {r[0] for r in rows}

    candidates = []
    for c in raw_candidates:
        candidates.append({
            "url": c["url"],
            "title": c["title"],
            "domain": c["domain"],
            "already_ingested": c["url"] in existing_urls,
        })

    return {
        "seed_url": cleaned_seed,
        "page_title": page_title,
        "domain": seed_domain,
        "total_found": len(candidates),
        "links": candidates,
    }


def ai_curate_candidate_links(
    seed_url: str,
    page_title: str,
    links: List[dict],
    custom_instructions: Optional[str] = None,
    client=None,
) -> dict:
    """Uses Ollama LLM with structured JSON output to filter and pre-select substantive content links,

    prioritizing documentation and guides while discarding language variants, sitemaps, and boilerplate.
    """
    if not links:
        return {
            "selected_urls": [],
            "explanation": "No candidate links provided to evaluate.",
        }

    if client is None:
        client = _get_ollama_client()

    system_prompt = (
        "You are an expert web crawler curator for a technical knowledge base. "
        "Your task is to analyze discovered candidate links extracted from a seed webpage "
        "and select only substantive, high-value informational links (such as documentation chapters, "
        "tutorials, API guides, reference manuals, and technical blog posts).\n\n"
        "STRICT FILTERING RULES:\n"
        "1. PRIORITIZE core documentation, tutorials, user guides, and informational content.\n"
        "2. EXCLUDE links in other languages (e.g. localized paths like /zh/, /ja/, /es/, /de/, /fr/, /pt/ or language switchers).\n"
        "3. EXCLUDE sitemaps, RSS/Atom feeds, XML files, robots.txt.\n"
        "4. EXCLUDE boilerplate and utility pages: login, register/signup, account, privacy policy, terms of service, legal, cookie policy.\n"
        "5. EXCLUDE social media profiles or share widgets (Twitter, LinkedIn, Facebook, Instagram).\n"
        "6. EXCLUDE pagination lists, tag archives, search query URLs, and category index hubs that contain no standalone content.\n\n"
        "Output MUST be a valid JSON object matching this schema:\n"
        "{\n"
        '  "selected_urls": ["<url1>", "<url2>", ...],\n'
        '  "explanation": "<concise explanation of why these links were selected and what was filtered out>"\n'
        "}\n"
        "Do NOT include markdown formatting or conversational filler outside the JSON."
    )

    if custom_instructions and custom_instructions.strip():
        system_prompt += f"\n\nUSER CUSTOM INSTRUCTIONS:\n{custom_instructions.strip()}"

    # Build concise representation for LLM input
    links_payload = []
    for idx, item in enumerate(links[:150]):  # Cap at 150 items to fit LLM context cleanly
        links_payload.append({
            "id": idx + 1,
            "title": item.get("title", ""),
            "url": item.get("url", ""),
        })

    user_content = (
        f"Seed URL: {seed_url}\n"
        f"Seed Page Title: {page_title}\n"
        f"Candidate Links ({len(links_payload)} items):\n"
        f"{json.dumps(links_payload, indent=2)}"
    )

    try:
        response = client.chat(
            model=config.ollama_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            format="json",
            think=getattr(config, "ollama_think", False),
        )

        raw_text = response.message.content.strip()
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_text = "\n".join(lines).strip()

        data = json.loads(raw_text)
        selected_urls = data.get("selected_urls", [])
        explanation = data.get(
            "explanation",
            f"AI evaluated {len(links)} links and selected {len(selected_urls)} content pages.",
        )

        # Ensure returned URLs actually exist in the candidate list
        valid_urls = {item.get("url") for item in links if item.get("url")}
        filtered_selected = [u for u in selected_urls if u in valid_urls]

        # Heuristic fallback: filter out obvious foreign language paths if LLM missed any
        clean_selected = []
        for u in filtered_selected:
            path = urlparse(u).path
            if FOREIGN_LANG_REGEX.match(path):
                continue
            clean_selected.append(u)

        return {
            "selected_urls": clean_selected,
            "explanation": explanation,
        }
    except Exception as e:
        logger.error(f"AI candidate curation failed: {e}", exc_info=True)
        # Fallback heuristic selection: keep same-domain links that aren't language/TOS
        fallback = []
        for item in links:
            u = item.get("url", "")
            path = urlparse(u).path.lower()
            if FOREIGN_LANG_REGEX.match(path):
                continue
            if any(
                w in path
                for w in (
                    "login",
                    "signup",
                    "privacy",
                    "terms",
                    "tos",
                    "cookie",
                    "sitemap",
                    "feed",
                )
            ):
                continue
            fallback.append(u)

        return {
            "selected_urls": fallback,
            "explanation": f"Automated rule-based filter applied (AI service unavailable: {e}). Filtered out language variants, sitemaps, and utility links.",
        }


def run_batch_crawl_ingestion(
    urls: List[str],
    collection_id: Optional[int] = None,
    new_collection_title: Optional[str] = None,
    config_obj=None,
) -> None:
    """Background worker routine that processes enqueued URLs sequentially, associates them

    with the specified collection, and dispatches Gotify alerts upon completion.
    """
    if config_obj is None:
        config_obj = config

    from .base import _jinja_env
    from .gotify import post_error_to_gotify, post_to_gotify
    from .models_orm import Collection, CollectionItem, FetchedPage

    client = _get_ollama_client()
    resolved_col_id = collection_id

    # Create new collection if title provided
    if new_collection_title and new_collection_title.strip():
        with db_session() as session:
            new_col = Collection(
                title=new_collection_title.strip(),
                visibility="public",
                created_at=datetime.now().isoformat(),
            )
            session.add(new_col)
            session.flush()
            resolved_col_id = new_col.id

    logger.info(
        f"[CRAWLER BATCH] Commencing batch scraping for {len(urls)} URLs into collection ID: {resolved_col_id}"
    )

    success_count = 0
    skipped_count = 0
    failed_count = 0

    for idx, raw_url in enumerate(urls):
        url = extract_first_url(raw_url)
        if not url:
            continue

        try:
            logger.info(
                f"[CRAWLER BATCH] ({idx + 1}/{len(urls)}) Ingesting target: {url}"
            )
            result = ingest_url_sync(None, url, config_obj, client)

            if "Skipping ingestion" in result.get("message", ""):
                skipped_count += 1
            else:
                success_count += 1

            # Associate with collection if specified
            if resolved_col_id:
                with db_session() as session:
                    existing_item = (
                        session.query(CollectionItem)
                        .filter_by(collection_id=resolved_col_id, source_id=url)
                        .first()
                    )
                    if not existing_item:
                        from sqlalchemy import func

                        max_order = (
                            session.query(func.max(CollectionItem.item_order))
                            .filter_by(collection_id=resolved_col_id)
                            .scalar()
                            or 0
                        )
                        session.add(
                            CollectionItem(
                                collection_id=resolved_col_id,
                                source_type="articles",
                                source_id=url,
                                item_note="Ingested via Web Crawler Selection",
                                taxonomy_path="",
                                item_order=max_order + 1,
                                added_at=datetime.now().isoformat(),
                            )
                        )

            # Brief pause between scrapes to avoid rate-limiting
            time.sleep(1.0)
        except Exception as e:
            failed_count += 1
            logger.error(
                f"[CRAWLER BATCH] Failed scraping {url}: {e}", exc_info=True
            )

    logger.info(
        f"[CRAWLER BATCH] Batch completed. Ingested: {success_count}, Skipped: {skipped_count}, Failed: {failed_count}"
    )

    # Dispatch Gotify summary alert
    try:
        from kb_core.notifier import Gotify

        gotify = Gotify(config_obj.gotify_url, config_obj.gotify_token)
        summary_msg = (
            f"🕷️ Crawl Batch Scraping Finished!\n"
            f"• Ingested: {success_count}\n"
            f"• Skipped (Unchanged): {skipped_count}\n"
            f"• Failed: {failed_count}\n"
            f"• Total Processed: {len(urls)}"
        )
        gotify.send(title="Crawl Batch Ingest Complete", message=summary_msg, priority=5)
    except Exception as e:
        logger.warning(f"[CRAWLER BATCH] Could not dispatch Gotify notification: {e}")
