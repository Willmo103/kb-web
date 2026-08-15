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

        if stripped.startswith(("*", "-", "+")) and not stripped.startswith(
            ("**", "***")
        ):
            if (
                stripped.startswith("* ")
                or stripped.startswith("- ")
                or stripped.startswith("+ ")
            ):
                is_list_item = True
        elif re.match(r"^\d+\.\s", stripped):
            is_list_item = True

        if is_list_item and i > 0:
            prev_line = final_lines[-1]
            prev_stripped = prev_line.strip()

            prev_is_list_item = False
            if prev_stripped.startswith(
                ("*", "-", "+")
            ) and not prev_stripped.startswith(("**", "***")):
                if (
                    prev_stripped.startswith("* ")
                    or prev_stripped.startswith("- ")
                    or prev_stripped.startswith("+ ")
                ):
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


def chunk_text_with_overlap(
    text: str, max_chunk_size: int = 1500, overlap: int = 150
) -> list[str]:
    """Splits text into chunks of at most max_chunk_size characters with overlap.

    Tries to split along paragraph/line boundaries if possible.
    """
    if not text:
        return []

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + max_chunk_size
        if end >= text_len:
            chunks.append(text[start:])
            break

        # Try to find a line break within the overlap window to split cleanly
        split_pos = end
        search_start = max(start, end - overlap)
        last_newline = text.rfind("\n", search_start, end)
        if last_newline != -1:
            split_pos = last_newline + 1
        else:
            last_space = text.rfind(" ", search_start, end)
            if last_space != -1:
                split_pos = last_space + 1

        chunk = text[start:split_pos]
        chunks.append(chunk)

        # Next chunk starts at split_pos minus overlap (or start + max_chunk_size - overlap)
        actual_chunk_len = len(chunk)
        start = start + actual_chunk_len - overlap
        if start >= text_len or actual_chunk_len <= overlap:
            break

    return [c.strip() for c in chunks if c.strip()]


def fetch_youtube_video_page(url: str, video_id: str) -> HTMLPage:
    """Retrieves YouTube video metadata and pulls subtitle transcripts to construct custom HTML/markdown documents."""
    title = f"YouTube Video {video_id}"
    description = ""
    creator = "Unknown Creator"

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


def extract_wiki_content(
    html_page: HTMLPage, config=None, client: Optional[ollama.Client] = None
) -> str:
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
            chat_kwargs = {
                "model": config.ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"URL: {html_page.url}\n\nRAW CONTENT:\n{raw_content}",
                    },
                ],
            }
            if getattr(config, "ollama_think", False):
                chat_kwargs["think"] = True
            response = client.chat(**chat_kwargs)
            return response.message.content
        else:
            chunks = chunk_text(raw_content, max_len)
            chunk_summaries = []
            for idx, chunk in enumerate(chunks):
                if is_video:
                    system_message = (
                        f"You are an AI assistant helping to process segment {idx + 1} of {len(chunks)} of a long YouTube video transcript. "
                        "Summarize this segment chronologically. Extract all key insights, arguments, and quotes. "
                        "CRITICAL: You MUST preserve timestamps (e.g., [MM:SS] or [HH:MM:SS]) and exact quotes with their timestamps. "
                        "Do not omit timing information."
                    )
                else:
                    system_message = (
                        f"You are an AI assistant helping to process segment {idx + 1} of {len(chunks)} of a long article. "
                        "Summarize this segment, extracting all key information, main topics, and technical details. "
                        "Do not omit important details."
                    )

                chat_kwargs = {
                    "model": config.ollama_model,
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": chunk},
                    ],
                }
                if getattr(config, "ollama_think", False):
                    chat_kwargs["think"] = True
                chunk_resp = client.chat(**chat_kwargs)
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

            chat_kwargs = {
                "model": config.ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_content,
                    },
                ],
            }
            if getattr(config, "ollama_think", False):
                chat_kwargs["think"] = True
            response = client.chat(**chat_kwargs)
            return response.message.content
    except Exception as e:
        print(f"Ollama extraction failed: {e}")
        raise


def extract_tags_content(
    html_page: HTMLPage, config=None, client: Optional[ollama.Client] = None
) -> list[str]:
    """Queries Ollama to extract descriptive tags from markdown content."""
    if config is None:
        config = default_config
    if client is None:
        client = _get_ollama_client()
    try:
        raw_content = html_page.md_content or ""
        max_len = getattr(config, "max_input_length", 20000)

        if len(raw_content) > max_len and html_page.description:
            content_to_analyze = (
                f"TITLE: {html_page.title}\n\nWIKI SUMMARY:\n{html_page.description}"
            )
        else:
            content_to_analyze = raw_content[:max_len]

        chat_kwargs = {
            "model": config.ollama_model,
            "messages": [
                {"role": "system", "content": DEFAULT_TAGS_PROMPT},
                {
                    "role": "user",
                    "content": f"URL: {html_page.url}\n\nRAW CONTENT:\n{content_to_analyze}",
                },
            ],
        }
        if getattr(config, "ollama_think", False):
            chat_kwargs["think"] = True
        response = client.chat(**chat_kwargs)
        tags_str = response.message.content
        tags = [t.strip().lower() for t in tags_str.split(",") if t.strip()]
        return [t for t in tags if t]
    except Exception as e:
        print(f"Ollama tagging failed: {e}")
        raise


def save_youtube_metadata_helper(
    db, url: str, creator: Optional[str] = None, force_fetch: bool = False
) -> None:
    """Saves YouTube metadata to the youtube_videos table."""
    video_id = extract_youtube_video_id(url)
    if not video_id:
        return

    channel_id = None
    duration = None
    view_count = None
    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"

    from .models_orm import YouTubeVideo
    from .base import db_session

    with db_session() as session:
        if not force_fetch:
            try:
                existing = session.query(YouTubeVideo).filter_by(url=url).first()
                if existing and existing.creator != "Unknown Creator":
                    return
            except Exception:
                pass

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
            creator = (
                info.get("uploader")
                or info.get("channel")
                or creator
                or "Unknown Creator"
            )
            channel_id = info.get("channel_id")
            duration = info.get("duration")
            view_count = info.get("view_count")
            thumbnail_url = info.get("thumbnail") or thumbnail_url
    except Exception as e:
        print(f"Failed to fetch YouTube metadata in helper for {url}: {e}")
        creator = creator or "Unknown Creator"

    try:
        with db_session() as session:
            video = session.query(YouTubeVideo).filter_by(url=url).first()
            if video:
                video.video_id = video_id
                video.creator = creator
                video.channel_id = channel_id
                video.duration = duration
                video.view_count = view_count
                video.thumbnail_url = thumbnail_url
                video.updated_at = datetime.now().isoformat()
            else:
                session.add(
                    YouTubeVideo(
                        url=url,
                        video_id=video_id,
                        creator=creator,
                        channel_id=channel_id,
                        duration=duration,
                        view_count=view_count,
                        thumbnail_url=thumbnail_url,
                        updated_at=datetime.now().isoformat(),
                    )
                )
        print(f"Successfully saved YouTube video metadata for: {url}")
    except Exception as e:
        print(f"Failed to save YouTube metadata to database: {e}")


def update_article_embedding(
    db, url: str, config=None, client: Optional[ollama.Client] = None
) -> None:
    """Generates embedding for the article and saves/updates it in the database."""
    if config is None:
        config = default_config
    if client is None:
        client = _get_ollama_client()
    try:
        from .models_orm import FetchedPage, ArticleEmbedding, TitleEmbedding
        from .base import db_session

        with db_session() as session:
            page = session.query(FetchedPage).filter_by(url=url).first()
            if not page:
                print(f"Page {url} not found for embedding generation.")
                return

            tags_json = page.tags or "[]"
            title = page.title or ""
            description = page.description or ""

        try:
            tags = json.loads(tags_json)
        except Exception:
            tags = []

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

        now_str = datetime.now().isoformat()
        with db_session() as session:
            art_emb = session.query(ArticleEmbedding).filter_by(url=url).first()
            if art_emb:
                art_emb.embedding = embedding
                art_emb.updated_at = now_str
            else:
                art_emb = ArticleEmbedding(
                    url=url, embedding=embedding, updated_at=now_str
                )
                session.add(art_emb)

            # Generate and store title embedding
            if title.strip():
                try:
                    try:
                        title_resp = client.embeddings(
                            model=emb_model, prompt=title[:4000]
                        )
                        title_embedding = title_resp["embedding"]
                    except Exception as e2:
                        print(
                            f"Ollama title embedding with model '{emb_model}' failed: {e2}. Trying main model '{config.ollama_model}'..."
                        )
                        ensure_model_available(client, config.ollama_model)
                        title_resp = client.embeddings(
                            model=config.ollama_model, prompt=title[:4000]
                        )
                        title_embedding = title_resp["embedding"]

                    title_emb = (
                        session.query(TitleEmbedding).filter_by(url=url).first()
                    )
                    if title_emb:
                        title_emb.embedding = title_embedding
                        title_emb.updated_at = now_str
                    else:
                        title_emb = TitleEmbedding(
                            url=url, embedding=title_embedding, updated_at=now_str
                        )
                        session.add(title_emb)
                    print(
                        f"Successfully generated and stored title embedding for: {url}"
                    )
                except Exception as te:
                    print(f"Failed to generate title embedding for {url}: {te}")
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


def get_similar_articles(
    db, current_url: str, config=None, limit: int = 5
) -> list[dict]:
    """Calculates cosine similarity between current_url and all other articles."""
    if config is None:
        config = default_config

    from .models_orm import ArticleEmbedding, FetchedPage
    from .base import db_session

    try:
        with db_session() as session:
            dialect_name = session.bind.dialect.name
            curr = session.query(ArticleEmbedding).filter_by(url=current_url).first()
            if not curr or not curr.embedding:
                return []

            if dialect_name == "postgresql":
                distance_col = ArticleEmbedding.embedding.cosine_distance(curr.embedding)
                results = (
                    session.query(ArticleEmbedding, FetchedPage, distance_col)
                    .join(FetchedPage, ArticleEmbedding.url == FetchedPage.url)
                    .filter(ArticleEmbedding.url != current_url)
                    .order_by(distance_col)
                    .limit(limit)
                    .all()
                )

                similarities = []
                for emb, page, distance in results:
                    if distance is None:
                        continue
                    similarity = 1.0 - float(distance)
                    if similarity >= getattr(config, "similarity_threshold", 0.8):
                        tags_json = page.tags or "[]"
                        try:
                            tags = json.loads(tags_json)
                        except Exception:
                            tags = []

                        similarities.append(
                            {
                                "url": page.url,
                                "title": page.title or page.url,
                                "tags": tags,
                                "similarity": round(similarity * 100, 1),
                            }
                        )
                return similarities
            else:
                # SQLite fallback utilizing python cosine_similarity
                all_embs = (
                    session.query(ArticleEmbedding, FetchedPage)
                    .join(FetchedPage, ArticleEmbedding.url == FetchedPage.url)
                    .filter(ArticleEmbedding.url != current_url)
                    .all()
                )

                similarities = []
                current_emb = curr.embedding
                if isinstance(current_emb, str):
                    try:
                        current_emb = json.loads(current_emb)
                    except Exception:
                        pass

                for emb, page in all_embs:
                    if not emb.embedding:
                        continue
                    val_emb = emb.embedding
                    if isinstance(val_emb, str):
                        try:
                            val_emb = json.loads(val_emb)
                        except Exception:
                            continue
                    similarity = cosine_similarity(current_emb, val_emb)
                    if similarity >= getattr(config, "similarity_threshold", 0.8):
                        tags_json = page.tags or "[]"
                        try:
                            tags = json.loads(tags_json)
                        except Exception:
                            tags = []
                        similarities.append(
                            {
                                "url": page.url,
                                "title": page.title or page.url,
                                "tags": tags,
                                "similarity": round(similarity * 100, 1),
                            }
                        )
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


def generate_gemma_embeddings_for_page(
    db, url: str, config=None, client: Optional[ollama.Client] = None
) -> None:
    """Generates embeddinggemma chunk embeddings and description embedding for a page/video."""
    if config is None:
        config = default_config
    if client is None:
        client = _get_ollama_client()

    from .models_orm import FetchedPage, YouTubeVideo, ChunkEmbedding, ArticleEmbedding, VideoEmbedding
    from .base import db_session

    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=url).first()
        if not page:
            print(f"Page {url} not found for gemma embedding generation.")
            return

        title = page.title or url
        md_content = page.md_content or ""
        description = page.description or ""

        # Determine source type (articles or videos)
        is_video = session.query(YouTubeVideo).filter_by(url=url).first() is not None

    source_type = "videos" if is_video else "articles"

    # Check model availability for embeddinggemma
    emb_model = "embeddinggemma"
    try:
        ensure_model_available(client, emb_model)
    except Exception as e:
        print(
            f"Warning: failed to verify/pull '{emb_model}': {e}. Using configured model."
        )
        emb_model = getattr(config, "ollama_embedding_model", "nomic-embed-text")

    # 1. Chunk and embed md_content
    chunks = chunk_text_with_overlap(md_content, 1500, 150)

    with db_session() as session:
        # Delete existing chunks for this url to avoid stale ones
        session.query(ChunkEmbedding).filter_by(
            source_type=source_type, source_id=url
        ).delete()

        for idx, chunk in enumerate(chunks):
            prompt = f"search_document: {chunk}"
            try:
                resp = client.embeddings(model=emb_model, prompt=prompt)
                vector = resp["embedding"]
                new_chunk = ChunkEmbedding(
                    source_type=source_type,
                    source_id=url,
                    source_title=title,
                    chunk_number=idx,
                    chunk_content=chunk,
                    chunk_vector=vector,
                    created_at=datetime.now().isoformat(),
                )
                session.add(new_chunk)
            except Exception as e:
                print(
                    f"Failed to generate chunk embedding for {url} chunk {idx}: {e}"
                )

        # 2. Embed description and save to article_embeddings or video_embeddings
        if description.strip():
            prompt_desc = f"search_document: {description}"
            try:
                resp = client.embeddings(model=emb_model, prompt=prompt_desc)
                vector_desc = resp["embedding"]
                now_str = datetime.now().isoformat()

                if is_video:
                    vid_emb = (
                        session.query(VideoEmbedding).filter_by(url=url).first()
                    )
                    if vid_emb:
                        vid_emb.embedding = vector_desc
                        vid_emb.updated_at = now_str
                    else:
                        vid_emb = VideoEmbedding(
                            url=url, embedding=vector_desc, updated_at=now_str
                        )
                        session.add(vid_emb)
                else:
                    art_emb = (
                        session.query(ArticleEmbedding).filter_by(url=url).first()
                    )
                    if art_emb:
                        art_emb.embedding = vector_desc
                        art_emb.updated_at = now_str
                    else:
                        art_emb = ArticleEmbedding(
                            url=url, embedding=vector_desc, updated_at=now_str
                        )
                        session.add(art_emb)
                print(
                    f"Successfully stored gemma embedding of description for {url}"
                )
            except Exception as e:
                print(f"Failed to generate description embedding for {url}: {e}")


def ingest_url_sync(db, url: str, config=None, client=None) -> dict:
    """Ingests a URL, processes it with Ollama, saves to DB, and updates embeddings."""
    url = extract_first_url(url)
    page_data = fetch_url(url)

    from .models_orm import FetchedPage, PageVersion
    from .base import db_session

    try:
        with db_session() as session:
            existing = session.query(FetchedPage).filter_by(url=url).first()
            if existing:
                if existing.md_content_hash == page_data.md_content_hash:
                    return {
                        "status": "success",
                        "message": "Content unchanged. Skipping ingestion.",
                        "url": url,
                    }
                else:
                    session.add(
                        PageVersion(
                            url=existing.url,
                            title=existing.title,
                            html_content=existing.html_content,
                            md_content=existing.md_content,
                            links=existing.links,
                            html_content_hash=existing.html_content_hash,
                            md_content_hash=existing.md_content_hash,
                            fetched_at=existing.fetched_at,
                            description=existing.description,
                            keywords=existing.keywords,
                            tags=existing.tags,
                        )
                    )
    except Exception:
        pass

    wiki_entry = extract_wiki_content(page_data, config, client)
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
    tags = extract_tags_content(page_data, config, client)
    page_data.tags = tags

    serialized, creator = serialize_page_for_db(page_data)
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=url).first()
        if page:
            for k, v in serialized.items():
                setattr(page, k, v)
        else:
            session.add(FetchedPage(**serialized))

    save_youtube_metadata_helper(db, page_data.url, creator)
    update_article_embedding(db, page_data.url, config, client)
    return {"status": "success", "url": url}


def download_youtube_video(video_id: str, config_obj=None) -> str:
    """Downloads a YouTube video to ~/.kb/media/videos/<video_id>.mp4 using yt-dlp.

    Returns the absolute local path to the downloaded video.
    """
    import yt_dlp
    import re

    if config_obj is None:
        config_obj = default_config

    media_dir = config_obj.configs_dir.parent / "media" / "videos"
    media_dir.mkdir(parents=True, exist_ok=True)

    # Check if a file containing the video_id already exists in the media directory
    existing_files = list(media_dir.glob(f"*{video_id}*"))
    if existing_files:
        return str(existing_files[0])

    def sanitize_filename(name: str) -> str:
        # Remove characters invalid in Windows & Unix filesystems: \ / : * ? " < > |
        cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
        return cleaned.strip()

    creator = None
    title = None

    # Try looking up in the database first
    url1 = f"https://www.youtube.com/watch?v={video_id}"
    url2 = f"https://youtube.com/watch?v={video_id}"
    try:
        from .base import db_session
        from .models_orm import YouTubeVideo, FetchedPage

        with db_session() as session:
            yt_rec = session.query(YouTubeVideo).filter(YouTubeVideo.url.in_([url1, url2])).first()
            if yt_rec:
                creator = yt_rec.creator
            page_rec = session.query(FetchedPage).filter(FetchedPage.url.in_([url1, url2])).first()
            if page_rec:
                title = page_rec.title
    except Exception:
        pass

    # Extract metadata using yt-dlp if database records do not exist
    if not creator or not title:
        try:
            ydl_opts_info = {
                "quiet": True,
                "no_warnings": True,
            }
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info = ydl.extract_info(video_url, download=False)
                if info:
                    if not creator:
                        creator = info.get("uploader")
                    if not title:
                        title = info.get("title")
        except Exception:
            pass

    creator_clean = sanitize_filename(creator) if creator else ""
    title_clean = sanitize_filename(title) if title else ""

    if creator_clean and title_clean:
        filename_base = f"[{creator_clean}] - {title_clean} [{video_id}]"
    elif title_clean:
        filename_base = f"{title_clean} [{video_id}]"
    else:
        filename_base = f"{video_id}"

    ydl_opts = {
        "format": "mp4/best",
        "outtmpl": str(media_dir / f"{filename_base}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])

    downloaded_files = []
    if media_dir.exists():
        for f in media_dir.iterdir():
            if f.is_file() and f.name.startswith(filename_base):
                downloaded_files.append(f)

    if downloaded_files:
        first_file = downloaded_files[0]
        if first_file.suffix != ".mp4":
            new_path = first_file.with_suffix(".mp4")
            first_file.rename(new_path)
            return str(new_path)
        return str(first_file)

    raise RuntimeError(f"Failed to download video {video_id} with yt-dlp.")
