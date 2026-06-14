"""
Helper utilities for the Knowledge Base Web Importer application.
"""

import hashlib
import json
import math
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
import ollama
from bs4 import BeautifulSoup  # type: ignore
from html2text import HTML2Text

from .models import HTMLPage, extract_youtube_video_id
from .base import config as default_config, _get_ollama_client

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

DEFAULT_TAGS_PROMPT = (
    "You are a professional categorization assistant. Analyze the following web page content "
    "and generate a list of 5 to 10 relevant tags, keywords, or labels for cataloging it. "
    "Respond ONLY with a comma-separated list of tags (e.g., 'python, web-development, tutorial'). "
    "Do not reply with any filler headers, introductory remarks, or formatting."
)


def extract_first_url(text: str) -> str:
    """Extracts the first web URL from a block of text, supporting common copy-paste errors."""
    text = text.strip()
    match = re.search(r"https?:/*\S+", text)
    if match:
        url = match.group(0)
        if url.startswith("http:") and not url.startswith("http://"):
            url = "http://" + url[5:]
        elif url.startswith("https:") and not url.startswith("https://"):
            url = "https://" + url[6:]
        url = url.rstrip(".,;()[]{}\"\"''")
        return url

    match_domain = re.search(r"[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/\S*)?", text)
    if match_domain:
        url = match_domain.group(0)
        url = url.rstrip(".,;()[]{}\"\"''")
        return "https://" + url

    return text


def get_url_basename(url: str) -> str:
    """Helper to extract the domain/hostname as site basename from a URL, stripping www."""
    parsed = urlparse(url)
    hostname = parsed.netloc or parsed.path
    if not hostname:
        return "unknown"
    hostname = hostname.lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def preprocess_markdown(text: str) -> str:
    """Preprocesses markdown to normalize bullet lists starting with a single asterisk

    and ensures they are preceded by a blank line for standard markdown parsers.
    """
    if not text:
        return ""

    lines = text.split("\n")
    processed_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("*") and not stripped.startswith("**"):
            indent = len(line) - len(line.lstrip())
            content = line.lstrip()
            remainder = content[1:]
            if remainder and not remainder.startswith(" "):
                line = " " * indent + "* " + remainder
        processed_lines.append(line)

    final_lines = []
    for i, line in enumerate(processed_lines):
        stripped = line.strip()
        is_list_item = False

        if stripped.startswith(("*", "-", "+")) and not stripped.startswith(("**", "***")):
            if stripped.startswith("* ") or stripped.startswith("- ") or stripped.startswith("+ "):
                is_list_item = True
        elif re.match(r"^\d+\.\s", stripped):
            is_list_item = True

        if is_list_item and i > 0:
            prev_line = final_lines[-1]
            prev_stripped = prev_line.strip()

            prev_is_list_item = False
            if prev_stripped.startswith(("*", "-", "+")) and not prev_stripped.startswith(("**", "***")):
                if prev_stripped.startswith("* ") or prev_stripped.startswith("- ") or prev_stripped.startswith("+ "):
                    prev_is_list_item = True
            elif re.match(r"^\d+\.\s", prev_stripped):
                prev_is_list_item = True

            if prev_stripped and not prev_is_list_item:
                final_lines.append("")

        final_lines.append(line)

    return "\n".join(final_lines)


def chunk_text(text: str, max_chunk_size: int) -> list[str]:
    """Splits a long text into logical chunks of at most max_chunk_size characters,

    splitting safely along line boundaries if possible.
    """
    if not text:
        return []
    
    lines = text.splitlines()
    chunks = []
    current_chunk = []
    current_len = 0
    
    for line in lines:
        if len(line) > max_chunk_size:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_len = 0
            for i in range(0, len(line), max_chunk_size):
                chunks.append(line[i : i + max_chunk_size])
            continue
            
        if current_len + len(line) + 1 > max_chunk_size and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
            current_len = 0
            
        current_chunk.append(line)
        current_len += len(line) + 1
        
    if current_chunk:
        chunks.append("\n".join(current_chunk))
        
    return chunks


def fetch_youtube_video_page(url: str, video_id: str) -> HTMLPage:
    """Retrieves YouTube video metadata and pulls subtitle transcripts to construct custom HTML/markdown documents."""
    title = f"YouTube Video {video_id}"
    description = ""
    creator = "Unknown Creator"

    try:
        import yt_dlp

        class QuietLogger:
            def debug(self, msg): pass
            def warning(self, msg): pass
            def error(self, msg): pass

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
            creator = info.get("uploader") or info.get("channel") or "Unknown Creator"
    except Exception as e:
        print(f"yt-dlp metadata extraction failed: {e}")
        try:
            res = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=10)
            soup = BeautifulSoup(res.text, "html5lib")
            if soup.title:
                title = soup.title.string.replace(" - YouTube", "")
        except Exception:
            pass

    transcript = None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        else:
            transcript_list = YouTubeTranscriptApi().fetch(video_id)

        transcript_lines = []
        for entry in transcript_list:
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
        creator=creator,
    )


def fetch_url(url: str) -> HTMLPage:
    """Downloads content from a specified URL and extracts its markdown representation,

    hyperlinks, and cryptographic hashes.
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
                    existing_models.append(str(m))
        else:
            existing_models = [str(m) for m in models_response]

        if (
            model_name not in existing_models
            and f"{model_name}:latest" not in existing_models
        ):
            print(f"Ollama model '{model_name}' not found locally. Initiating pull...")
            client.pull(model_name)
            print(f"Successfully pulled Ollama model '{model_name}'")
    except Exception as e:
        print(f"Failed to automatically pull Ollama model '{model_name}': {e}")


def extract_wiki_content(html_page: HTMLPage, config=None, client: Optional[ollama.Client] = None) -> str:
    """Queries Ollama to clean, restructure, and digest raw markdown into wiki formats."""
    if config is None:
        config = default_config
    if client is None:
        client = _get_ollama_client()
    try:
        video_id = extract_youtube_video_id(html_page.url)
        is_video = bool(video_id)
        
        if is_video:
            system_prompt = getattr(config, "youtube_wiki_prompt", config.wiki_prompt)
        else:
            system_prompt = config.wiki_prompt

        raw_content = html_page.md_content or ""
        max_len = getattr(config, "max_input_length", 20000)
        
        if len(raw_content) <= max_len:
            response = client.chat(
                model=config.ollama_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"URL: {html_page.url}\n\nRAW CONTENT:\n{raw_content}",
                    },
                ],
            )
            return response.message.content
        else:
            chunks = chunk_text(raw_content, max_len)
            chunk_summaries = []
            for idx, chunk in enumerate(chunks):
                if is_video:
                    system_message = (
                        f"You are an AI assistant helping to process segment {idx+1} of {len(chunks)} of a long YouTube video transcript. "
                        "Summarize this segment chronologically. Extract all key insights, arguments, and quotes. "
                        "CRITICAL: You MUST preserve timestamps (e.g., [MM:SS] or [HH:MM:SS]) and exact quotes with their timestamps. "
                        "Do not omit timing information."
                    )
                else:
                    system_message = (
                        f"You are an AI assistant helping to process segment {idx+1} of {len(chunks)} of a long article. "
                        "Summarize this segment, extracting all key information, main topics, and technical details. "
                        "Do not omit important details."
                    )
                
                chunk_resp = client.chat(
                    model=config.ollama_model,
                    messages=[
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": chunk},
                    ]
                )
                chunk_summaries.append(chunk_resp.message.content)
            
            compiled_summaries = "\n\n---\n\n".join(chunk_summaries)
            
            if is_video:
                user_content = (
                    f"URL: {html_page.url}\n\n"
                    "This is a compiled summary of the video transcript because the transcript was too long to process at once. "
                    "Use these section summaries to construct the final wiki article following the instructions.\n\n"
                    f"COMPILED SECTION SUMMARIES:\n{compiled_summaries}"
                )
            else:
                user_content = (
                    f"URL: {html_page.url}\n\n"
                    "This is a compiled summary of the article because the article was too long to process at once. "
                    "Use these section summaries to construct the final wiki article following the instructions.\n\n"
                    f"COMPILED SECTION SUMMARIES:\n{compiled_summaries}"
                )
                
            response = client.chat(
                model=config.ollama_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_content,
                    },
                ],
            )
            return response.message.content
    except Exception as e:
        print(f"Ollama extraction failed: {e}")
        return f"# Ingestion Backup \n\nAI Processing skipped or failed. Raw layout captured below.\n\n {html_page.md_content[:2000]}"


def extract_tags_content(html_page: HTMLPage, config=None, client: Optional[ollama.Client] = None) -> list[str]:
    """Queries Ollama to extract descriptive tags from markdown content."""
    if config is None:
        config = default_config
    if client is None:
        client = _get_ollama_client()
    try:
        raw_content = html_page.md_content or ""
        max_len = getattr(config, "max_input_length", 20000)
        
        if len(raw_content) > max_len and html_page.description:
            content_to_analyze = f"TITLE: {html_page.title}\n\nWIKI SUMMARY:\n{html_page.description}"
        else:
            content_to_analyze = raw_content[:max_len]
            
        response = client.chat(
            model=config.ollama_model,
            messages=[
                {"role": "system", "content": DEFAULT_TAGS_PROMPT},
                {
                    "role": "user",
                    "content": f"URL: {html_page.url}\n\nRAW CONTENT:\n{content_to_analyze}",
                },
            ],
        )
        tags_str = response.message.content
        tags = [t.strip().lower() for t in tags_str.split(",") if t.strip()]
        return [t for t in tags if t]
    except Exception as e:
        print(f"Ollama tagging failed: {e}")
        return []


def save_youtube_metadata_helper(db, url: str, creator: Optional[str] = None, force_fetch: bool = False) -> None:
    """Saves YouTube metadata to the youtube_videos table."""
    video_id = extract_youtube_video_id(url)
    if not video_id:
        return

    channel_id = None
    duration = None
    view_count = None
    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"

    if "youtube_videos" in db.table_names() and not force_fetch:
        try:
            existing = db["youtube_videos"].get(url)
            if existing and existing.get("creator") != "Unknown Creator":
                return
        except Exception:
            pass

    try:
        import yt_dlp
        class QuietLogger:
            def debug(self, msg): pass
            def warning(self, msg): pass
            def error(self, msg): pass

        ydl_opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "logger": QuietLogger(),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            creator = info.get("uploader") or info.get("channel") or creator or "Unknown Creator"
            channel_id = info.get("channel_id")
            duration = info.get("duration")
            view_count = info.get("view_count")
            thumbnail_url = info.get("thumbnail") or thumbnail_url
    except Exception as e:
        print(f"Failed to fetch YouTube metadata in helper for {url}: {e}")
        creator = creator or "Unknown Creator"

    try:
        db["youtube_videos"].upsert({
            "url": url,
            "video_id": video_id,
            "creator": creator,
            "channel_id": channel_id,
            "duration": duration,
            "view_count": view_count,
            "thumbnail_url": thumbnail_url,
            "updated_at": datetime.now().isoformat()
        }, pk="url")
        print(f"Successfully saved YouTube video metadata for: {url}")
    except Exception as e:
        print(f"Failed to save YouTube metadata to database: {e}")


def update_article_embedding(db, url: str, config=None, client: Optional[ollama.Client] = None) -> None:
    """Generates embedding for the article and saves/updates it in the database."""
    if config is None:
        config = default_config
    if client is None:
        client = _get_ollama_client()
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


def get_similar_articles(db, current_url: str, config=None, limit: int = 5) -> list[dict]:
    """Calculates cosine similarity between current_url and all other articles."""
    if config is None:
        config = default_config
    try:
        if "article_embeddings" not in db.table_names():
            return []

        try:
            current_row = db["article_embeddings"].get(current_url)
            current_emb = json.loads(current_row["embedding"])
        except Exception:
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

                if similarity >= getattr(config, "similarity_threshold", 0.8):
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


def serialize_page_for_db(page_data: HTMLPage) -> tuple[dict, Optional[str]]:
    """Helper to convert HTMLPage object to a dict ready for fetched_pages insertion,

    stripping out YouTube metadata attributes from the fetched_pages model to preserve decoupling.
    """
    serialized = page_data.model_dump()
    creator = serialized.pop("creator", None)
    serialized.pop("video_id", None)
    serialized.pop("duration", None)
    serialized.pop("view_count", None)
    serialized.pop("thumbnail_url", None)
    serialized.pop("collection_title", None)
    serialized["links"] = json.dumps(serialized["links"])
    serialized["keywords"] = json.dumps(serialized["keywords"])
    serialized["tags"] = json.dumps(serialized["tags"])
    return serialized, creator

