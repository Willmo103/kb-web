# Standalone Webpage Fetcher & YouTube Downloader (Typer CLI)

This folder contains self-contained Typer CLI Python applications extracted from the `kb-web` codebase. Each script encapsulates all necessary domain models, validation, business logic, and rich terminal interfaces with command completion, automatic help screens, and JSON outputs.

---

## 1. Scripts Overview

| Script | Source Modules | Key Classes | Primary Functions |
|---|---|---|---|
| [`fetch_webpage.py`](fetch_webpage.py) | `pipeline.py`, `html_cleaner.py`, `utils.py`, `models.py` | `WebpageFetcher`, `HTMLPage`, `ParsedUrl` | SSRF URL validation, HTTP fetching with custom headers, boilerplate/script stripping, link extraction, Markdown conversion |
| [`download_youtube.py`](download_youtube.py) | `video_manager.py`, `utils.py`, `models.py` | `YouTubeDownloader`, `YouTubeVideoMetadata`, `VideoDownloadResult` | 11-char ID extraction, yt-dlp metadata extraction, timestamped transcript retrieval, combined stream muxing (`mp4`), filename sanitization |

---

## 2. Webpage Fetcher CLI (`fetch_webpage.py`)

### Commands
- **`fetch`** (default): Downloads webpage content, removes navigation/boilerplate noise, and produces clean Markdown.
- **`links`**: Extracts and lists all resolved hyperlinks from raw HTML without boilerplate filtering.
- **`clean`**: Converts a local HTML file or saved scrape into clean Markdown.

### Usage Examples
```bash
# Direct fetch (defaults to 'fetch' subcommand)
uv run python .artifacts/extract-fetch-and-youtube/fetch_webpage.py https://example.com

# Fetch and save clean Markdown only
uv run python .artifacts/extract-fetch-and-youtube/fetch_webpage.py https://docs.python.org/3/ --markdown-only -o python_docs.md

# Extract all links as a JSON array
uv run python .artifacts/extract-fetch-and-youtube/fetch_webpage.py links https://en.wikipedia.org/wiki/Python_(programming_language) --json

# Clean a local HTML file to Markdown
uv run python .artifacts/extract-fetch-and-youtube/fetch_webpage.py clean ./page.html -o ./cleaned.md
```

---

## 3. YouTube Downloader CLI (`download_youtube.py`)

### Commands
- **`download`** (default): Downloads video and merges adaptive video and audio streams into an MP4 file.
- **`info`**: Inspects metadata (creator, duration, views, tags) without downloading video files.
- **`transcript`**: Extracts timestamped subtitle transcripts (`[MM:SS] Text`).

### Usage Examples
```bash
# Direct download (defaults to 'download' subcommand)
uv run python .artifacts/extract-fetch-and-youtube/download_youtube.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" -o ./videos

# Download high-quality audio stream only (.m4a)
uv run python .artifacts/extract-fetch-and-youtube/download_youtube.py dQw4w9WgXcQ --audio-only -o ./audio

# Inspect metadata without downloading media
uv run python .artifacts/extract-fetch-and-youtube/download_youtube.py info dQw4w9WgXcQ

# Extract timestamped transcript
uv run python .artifacts/extract-fetch-and-youtube/download_youtube.py transcript dQw4w9WgXcQ -o transcript.txt
```

---

## 4. Git Invariant Compliance
Per instructions, these artifacts are placed directly in `.artifacts/extract-fetch-and-youtube/` and have **not** been added or committed to git history.
