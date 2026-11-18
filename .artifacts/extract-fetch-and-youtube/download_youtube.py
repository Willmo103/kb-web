#!/usr/bin/env python3
"""
Standalone YouTube Downloader & Metadata/Transcript Extractor Script (Typer CLI).

Extracted from kb-web (video_manager.py, utils.py, models.py).
Provides video ID extraction from all URL variants, yt-dlp metadata extraction,
subtitle transcript retrieval with timestamps, combined stream muxing (video+audio),
and robust filesystem sanitization.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

from pydantic import BaseModel, Field
import typer


# ==============================================================================
# Domain Models & Classes
# ==============================================================================

class YouTubeVideoMetadata(BaseModel):
    """Structured YouTube video metadata."""
    video_id: str
    url: str
    title: str
    creator: str
    channel_id: Optional[str] = None
    duration: Optional[int] = None
    view_count: Optional[int] = None
    description: Optional[str] = None
    upload_date: Optional[str] = None
    thumbnail_url: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    has_transcript: bool = False
    transcript: Optional[str] = None


class VideoDownloadResult(BaseModel):
    """Result of a video download operation."""
    video_id: str
    url: str
    local_path: str
    filename: str
    file_size_bytes: int
    duration_seconds: Optional[int] = None
    already_existed: bool = False
    metadata: Optional[YouTubeVideoMetadata] = None


# ==============================================================================
# YouTube Helpers
# ==============================================================================

def extract_youtube_video_id(url_or_id: str) -> Optional[str]:
    """
    Extracts an 11-character YouTube video ID from various link structures
    or raw video ID / filename strings.
    """
    if not url_or_id:
        return None

    target = str(url_or_id).strip()

    # Exact 11-character ID (alphanumeric + '-' + '_')
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", target):
        return target

    # URL formats
    try:
        parsed = urlparse(target)
        if parsed.hostname in ("youtu.be", "www.youtu.be"):
            path_part = parsed.path.lstrip("/").split("/")[0]
            if len(path_part) == 11:
                return path_part
        if parsed.hostname in ("youtube.com", "www.youtube.com", "m.youtube.com"):
            if parsed.path == "/watch":
                v = parse_qs(parsed.query).get("v", [None])[0]
                if v and len(v) == 11:
                    return v
            if parsed.path.startswith(("/embed/", "/v/", "/shorts/")):
                parts = parsed.path.strip("/").split("/")
                if len(parts) >= 2 and len(parts[1]) == 11:
                    return parts[1]
    except Exception:
        pass

    # Filename formats: [creator] - Title [videoId].mp4 or videoId.mp4
    match = re.search(r"\[([a-zA-Z0-9_-]{11})\](?:\.[a-zA-Z0-9]+)?$", target)
    if match:
        return match.group(1)

    match = re.search(r"[_-]([a-zA-Z0-9_-]{11})\.[a-zA-Z0-9]+$", target)
    if match:
        return match.group(1)

    return None


def sanitize_filename(name: str) -> str:
    """Removes characters invalid in Windows & Unix filesystems: \\ / : * ? \" < > |"""
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    return cleaned.strip()


class QuietLogger:
    """yt-dlp logger suppressing verbose debug output."""
    def debug(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        pass


# ==============================================================================
# YouTubeDownloader Engine Class
# ==============================================================================

class YouTubeDownloader:
    """
    Production-grade YouTube video downloader with combined DASH stream selection,
    transcript extraction, and filesystem persistence.
    """

    # Combined stream selector preventing silent video-only downloads (package_caveats.md)
    DEFAULT_FORMAT = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
    AUDIO_FORMAT = "ba[ext=m4a]/ba/b"

    def __init__(self, output_dir: Optional[Path | str] = None, quiet: bool = True):
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = Path.home() / ".kb" / "media" / "videos"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.quiet = quiet

    def get_metadata(self, video_id_or_url: str, fetch_transcript: bool = True) -> YouTubeVideoMetadata:
        """
        Extracts rich metadata for a YouTube video using yt-dlp without downloading media.
        Optionally pulls subtitle transcripts.
        """
        if yt_dlp is None:
            raise RuntimeError("yt-dlp is required. Install with: pip install yt-dlp")

        video_id = extract_youtube_video_id(video_id_or_url)
        if not video_id:
            raise ValueError(f"Could not extract valid 11-char YouTube video ID from: {video_id_or_url}")

        video_url = f"https://www.youtube.com/watch?v={video_id}"

        ydl_opts: Dict[str, Any] = {
            "skip_download": True,
            "quiet": self.quiet,
            "no_warnings": True,
        }
        if self.quiet:
            ydl_opts["logger"] = QuietLogger()

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            if not info:
                raise RuntimeError(f"yt-dlp failed to retrieve info for {video_url}")

            title = info.get("title") or f"YouTube Video {video_id}"
            creator = info.get("uploader") or info.get("channel") or "Unknown Creator"
            channel_id = info.get("channel_id")
            duration = info.get("duration")
            view_count = info.get("view_count")
            description = info.get("description") or ""
            upload_date = info.get("upload_date")
            thumbnail = info.get("thumbnail")
            tags = info.get("tags") or []

        # Pull transcript if requested
        transcript_text = None
        if fetch_transcript:
            transcript_text = self.get_transcript(video_id)

        return YouTubeVideoMetadata(
            video_id=video_id,
            url=video_url,
            title=title,
            creator=creator,
            channel_id=channel_id,
            duration=duration,
            view_count=view_count,
            description=description,
            upload_date=upload_date,
            thumbnail_url=thumbnail,
            tags=tags,
            has_transcript=bool(transcript_text),
            transcript=transcript_text,
        )

    def get_transcript(self, video_id: str) -> Optional[str]:
        """
        Retrieves video subtitle transcript using youtube-transcript-api,
        formatting each entry with timestamps: [MM:SS] Text.
        """
        if YouTubeTranscriptApi is None:
            return None

        try:
            if hasattr(YouTubeTranscriptApi, "get_transcript"):
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            else:
                transcript_list = YouTubeTranscriptApi().fetch(video_id)

            lines = []
            for entry in transcript_list:
                start_sec = int(entry.start if hasattr(entry, "start") else entry.get("start", 0))
                text_content = entry.text if hasattr(entry, "text") else entry.get("text", "")
                minutes = start_sec // 60
                seconds = start_sec % 60
                lines.append(f"[{minutes:02d}:{seconds:02d}] {text_content.strip()}")

            return "\n".join(lines)
        except Exception:
            return None

    def download(
        self,
        video_id_or_url: str,
        format_selector: Optional[str] = None,
        audio_only: bool = False,
        overwrite: bool = False,
    ) -> VideoDownloadResult:
        """
        Downloads a YouTube video using combined audio/video streams,
        merging output cleanly to MP4/M4A.
        """
        if yt_dlp is None:
            raise RuntimeError("yt-dlp is required. Install with: pip install yt-dlp")

        video_id = extract_youtube_video_id(video_id_or_url)
        if not video_id:
            raise ValueError(f"Could not extract valid 11-char YouTube video ID from: {video_id_or_url}")

        # Check if file matching video_id already exists in output directory
        if not overwrite:
            existing_files = list(self.output_dir.glob(f"*{video_id}*"))
            video_candidates = [f for f in existing_files if f.is_file() and f.suffix.lower() in (".mp4", ".mkv", ".webm", ".m4a")]
            if video_candidates:
                target_file = video_candidates[0]
                return VideoDownloadResult(
                    video_id=video_id,
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    local_path=str(target_file.resolve()),
                    filename=target_file.name,
                    file_size_bytes=target_file.stat().st_size,
                    already_existed=True,
                )

        # Retrieve metadata for clean naming
        meta = self.get_metadata(video_id, fetch_transcript=False)

        creator_clean = sanitize_filename(meta.creator)
        title_clean = sanitize_filename(meta.title)

        if creator_clean and title_clean:
            filename_base = f"[{creator_clean}] - {title_clean} [{video_id}]"
        elif title_clean:
            filename_base = f"{title_clean} [{video_id}]"
        else:
            filename_base = f"{video_id}"

        # Choose stream format
        if format_selector:
            chosen_format = format_selector
        elif audio_only:
            chosen_format = self.AUDIO_FORMAT
        else:
            chosen_format = self.DEFAULT_FORMAT

        ext = "m4a" if audio_only else "mp4"
        out_tmpl = str(self.output_dir / f"{filename_base}.%(ext)s")

        ydl_opts: Dict[str, Any] = {
            "format": chosen_format,
            "outtmpl": out_tmpl,
            "quiet": self.quiet,
            "no_warnings": True,
        }
        if not audio_only:
            ydl_opts["merge_output_format"] = "mp4"
        if self.quiet:
            ydl_opts["logger"] = QuietLogger()

        video_url = f"https://www.youtube.com/watch?v={video_id}"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        # Locate downloaded file
        downloaded = [
            f for f in self.output_dir.iterdir()
            if f.is_file() and f.name.startswith(filename_base)
        ]

        if not downloaded:
            raise RuntimeError(f"Download completed but output file not found with base: {filename_base}")

        result_path = downloaded[0]
        # Normalize non-mp4 extensions when merging video
        if not audio_only and result_path.suffix.lower() != ".mp4":
            mp4_path = result_path.with_suffix(".mp4")
            result_path.rename(mp4_path)
            result_path = mp4_path

        return VideoDownloadResult(
            video_id=video_id,
            url=video_url,
            local_path=str(result_path.resolve()),
            filename=result_path.name,
            file_size_bytes=result_path.stat().st_size,
            duration_seconds=meta.duration,
            already_existed=False,
            metadata=meta,
        )


# ==============================================================================
# Typer CLI Application
# ==============================================================================

app = typer.Typer(
    help="CLI for downloading YouTube videos, muxing combined audio/video streams, and pulling transcripts.",
    no_args_is_help=True,
)


@app.command(name="download", help="Download a YouTube video merging adaptive video and audio streams to MP4.")
def download_cmd(
    url_or_id: str = typer.Argument(..., help="YouTube URL or 11-char video ID."),
    output_dir: Optional[Path] = typer.Option(
        None, "--output-dir", "-o", help="Target directory for downloaded video files."
    ),
    audio_only: bool = typer.Option(
        False, "--audio-only", "-a", help="Download high-quality audio stream only (.m4a)."
    ),
    stream_format: Optional[str] = typer.Option(
        None, "--format", "-f", help="Custom yt-dlp format selection string."
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Re-download and overwrite existing media file."
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="Output download result as JSON."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show verbose yt-dlp logger output."
    ),
) -> None:
    """Downloads YouTube video or audio with automatic filesystem sanitization."""
    downloader = YouTubeDownloader(output_dir=output_dir, quiet=not verbose)

    try:
        result = downloader.download(
            url_or_id,
            format_selector=stream_format,
            audio_only=audio_only,
            overwrite=overwrite,
        )
    except Exception as e:
        typer.secho(f"Error downloading {url_or_id}: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(json.dumps(result.model_dump(), indent=2))
    else:
        status_label = "Already exists" if result.already_existed else "Downloaded successfully"
        typer.secho(f"[{status_label}]", fg=typer.colors.GREEN if not result.already_existed else typer.colors.YELLOW, bold=True)
        typer.echo(f"  Filename: {result.filename}")
        typer.echo(f"  Path:     {result.local_path}")
        typer.echo(f"  Size:     {round(result.file_size_bytes / (1024 * 1024), 2)} MB")


@app.command(name="info", help="Fetch and inspect metadata for a video without downloading media files.")
def info_cmd(
    url_or_id: str = typer.Argument(..., help="YouTube URL or 11-char video ID."),
    with_transcript: bool = typer.Option(
        False, "--transcript", "-t", help="Include subtitle transcript in metadata lookup."
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="Output metadata as JSON."
    ),
) -> None:
    """Queries metadata via yt-dlp extraction."""
    downloader = YouTubeDownloader(quiet=True)

    try:
        meta = downloader.get_metadata(url_or_id, fetch_transcript=with_transcript)
    except Exception as e:
        typer.secho(f"Error inspecting {url_or_id}: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(json.dumps(meta.model_dump(), indent=2))
    else:
        typer.secho(f"{meta.title}", fg=typer.colors.CYAN, bold=True)
        typer.echo(f"  Video ID:            {meta.video_id}")
        typer.echo(f"  Creator/Channel:     {meta.creator}")
        typer.echo(f"  Duration:            {meta.duration}s")
        typer.echo(f"  Views:               {meta.view_count}")
        typer.echo(f"  Uploaded:            {meta.upload_date}")
        typer.echo(f"  Transcript Status:   {'Available' if meta.has_transcript else 'Not available'}")
        if meta.tags:
            typer.echo(f"  Tags:                {', '.join(meta.tags[:8])}")


@app.command(name="transcript", help="Fetch and print timestamped subtitle transcript for a YouTube video.")
def transcript_cmd(
    url_or_id: str = typer.Argument(..., help="YouTube URL or 11-char video ID."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="File path to save the transcript (default: stdout)."
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="Output transcript as JSON object."
    ),
) -> None:
    """Extracts timestamped subtitle transcript ([MM:SS] Text)."""
    downloader = YouTubeDownloader(quiet=True)

    try:
        meta = downloader.get_metadata(url_or_id, fetch_transcript=True)
    except Exception as e:
        typer.secho(f"Error retrieving transcript for {url_or_id}: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if not meta.transcript:
        typer.secho("No transcript available for this video.", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1)

    if json_output:
        content = json.dumps({"video_id": meta.video_id, "transcript": meta.transcript}, indent=2)
    else:
        content = meta.transcript

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        typer.secho(f"Transcript saved to {output}", fg=typer.colors.GREEN)
    else:
        typer.echo(content)


def main():
    # If the user passes a URL/video_id directly without a subcommand, default to 'download'
    known_commands = {"download", "info", "transcript", "--help", "-h"}
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-") and sys.argv[1] not in known_commands:
        sys.argv.insert(1, "download")
    app()


if __name__ == "__main__":
    main()
