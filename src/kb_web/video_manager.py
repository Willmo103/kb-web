"""
YouTube video media manager for kb-web.

Handles local video storage directory management, video indexing into the database,
and ZIP archive backups with an enforced maximum retention policy (max 2 backups).
"""

import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from .config import Config

default_config = Config()


def get_media_dir(config: Optional[Config] = None) -> Path:
    """Returns the local directory where YouTube videos are stored and ensures it exists."""
    cfg = config or default_config
    if hasattr(cfg, "data_root"):
        media_dir = cfg.data_root / "media" / "videos"
    elif hasattr(cfg, "configs_dir"):
        media_dir = cfg.configs_dir.parent / "media" / "videos"
    else:
        media_dir = Path.home() / ".kb" / "media" / "videos"
    media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir


def get_backups_dir(config: Optional[Config] = None) -> Path:
    """Returns the directory where backups are stored and ensures it exists."""
    cfg = config or default_config
    backups_dir = cfg.backups_dir
    backups_dir.mkdir(parents=True, exist_ok=True)
    return backups_dir


def extract_video_id_from_filename(filename: str) -> Optional[str]:
    """Extracts an 11-character YouTube video ID from a filename."""
    # Pattern 1: [creator] - Title [videoId].mp4
    match = re.search(r"\[([a-zA-Z0-9_-]{11})\](?:\.[a-zA-Z0-9]+)?$", filename)
    if match:
        return match.group(1)

    # Pattern 2: videoId.mp4 (exact 11 chars)
    match = re.match(r"^([a-zA-Z0-9_-]{11})(?:\.[a-zA-Z0-9]+)?$", filename)
    if match:
        return match.group(1)

    # Pattern 3: Embedded anywhere after an underscore or hyphen: ..._videoId.ext
    match = re.search(r"[_-]([a-zA-Z0-9_-]{11})\.[a-zA-Z0-9]+$", filename)
    if match:
        return match.group(1)

    return None


def index_local_videos(
    config: Optional[Config] = None, target_db_url: Optional[str] = None
) -> Dict[str, Any]:
    """Scans media/videos for YouTube video files, parses video IDs, and updates local_path in youtube_videos table."""
    cfg = config or default_config
    media_dir = get_media_dir(cfg)
    video_extensions = {".mp4", ".webm", ".mkv", ".m4v"}

    video_files: List[Path] = [
        f
        for f in media_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in video_extensions
    ]

    indexed_count = 0
    updated_urls: List[str] = []

    from .base import db_session, get_engine
    from .models_orm import YouTubeVideo, FetchedPage
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import create_engine

    if target_db_url:
        engine = create_engine(target_db_url)
        Session = sessionmaker(bind=engine)
        session_cm = Session()
    else:
        session_cm = None

    def execute_indexing(session):
        nonlocal indexed_count
        all_yt_rows = session.query(YouTubeVideo).all()
        # Map video_id to row
        yt_map = {row.video_id: row for row in all_yt_rows if row.video_id}

        for file_path in video_files:
            video_id = extract_video_id_from_filename(file_path.name)
            target_row = None

            if video_id and video_id in yt_map:
                target_row = yt_map[video_id]
            else:
                # Try matching by filename substring in video_id or vice-versa
                for row_vid, row in yt_map.items():
                    if row_vid and row_vid in file_path.name:
                        target_row = row
                        break

            try:
                resolved_path = str(file_path.relative_to(media_dir))
            except ValueError:
                resolved_path = file_path.name

            if target_row:
                if target_row.local_path != resolved_path:
                    target_row.local_path = resolved_path
                    target_row.updated_at = datetime.now().isoformat()
                    indexed_count += 1
                    updated_urls.append(target_row.url)
            elif video_id:
                # Look for matching FetchedPage to create a YouTubeVideo entry
                url1 = f"https://www.youtube.com/watch?v={video_id}"
                url2 = f"https://youtube.com/watch?v={video_id}"
                page = (
                    session.query(FetchedPage)
                    .filter(FetchedPage.url.in_([url1, url2]))
                    .first()
                )
                if page:
                    new_yt = YouTubeVideo(
                        url=page.url,
                        video_id=video_id,
                        local_path=resolved_path,
                        created_at=datetime.now().isoformat(),
                    )
                    session.add(new_yt)
                    indexed_count += 1
                    updated_urls.append(page.url)

    if target_db_url and session_cm:
        with session_cm as session:
            execute_indexing(session)
            session.commit()
    else:
        with db_session() as session:
            execute_indexing(session)

    return {
        "total_files": len(video_files),
        "indexed_count": indexed_count,
        "updated_urls": updated_urls,
    }


def prune_old_video_backups(backups_dir: Path, max_backups: int = 2) -> List[str]:
    """Ensures that no more than max_backups video archives are kept, deleting the oldest."""
    archives = list(backups_dir.glob("kb_videos_backup_*.zip"))
    if len(archives) <= max_backups:
        return []

    # Sort archives by modification time descending (newest first)
    archives.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    to_delete = archives[max_backups:]
    deleted = []
    for old_archive in to_delete:
        if old_archive.exists():
            try:
                old_archive.unlink()
                deleted.append(old_archive.name)
            except Exception as e:
                print(f"Warning: Failed to prune old video backup {old_archive.name}: {e}")
    return deleted


def create_video_backup_zip(
    config: Optional[Config] = None, max_backups: int = 2
) -> Optional[Path]:
    """Zips all video files from media/videos into a timestamped backup archive.

    Enforces the retention policy of retaining at most max_backups (default 2) video archives.
    """
    cfg = config or default_config
    media_dir = get_media_dir(cfg)
    backups_dir = get_backups_dir(cfg)

    video_extensions = {".mp4", ".webm", ".mkv", ".m4v"}
    video_files = [
        f for f in media_dir.rglob("*") if f.is_file() and f.suffix.lower() in video_extensions
    ]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"kb_videos_backup_{timestamp}.zip"
    zip_path = backups_dir / zip_filename

    # Create ZIP archive
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for video_file in video_files:
            try:
                arcname = str(video_file.relative_to(media_dir))
            except ValueError:
                arcname = video_file.name
            zipf.write(video_file, arcname=arcname)

    # Prune older archives so only max_backups remain
    prune_old_video_backups(backups_dir, max_backups=max_backups)

    return zip_path


def restore_video_backup_zip(
    zip_source: Path | str,
    config: Optional[Config] = None,
    target_db_url: Optional[str] = None,
) -> int:
    """Restores videos from a ZIP archive into media/videos and re-indexes them in the database."""
    cfg = config or default_config
    media_dir = get_media_dir(cfg)
    backups_dir = get_backups_dir(cfg)

    path = Path(zip_source)
    if not path.is_absolute() and not path.exists():
        path = backups_dir / zip_source

    if not path.exists():
        raise FileNotFoundError(f"Video backup archive not found: {path}")

    extracted_count = 0
    with zipfile.ZipFile(path, "r") as zipf:
        for member in zipf.infolist():
            if member.is_dir():
                continue
            clean_rel = Path(member.filename).as_posix().lstrip("/")
            target_dest = (media_dir / clean_rel).resolve()
            if not str(target_dest).startswith(str(media_dir.resolve())):
                continue
            target_dest.parent.mkdir(parents=True, exist_ok=True)
            with zipf.open(member) as source, open(target_dest, "wb") as target:
                target.write(source.read())
            extracted_count += 1

    # Re-index all videos after extraction
    index_local_videos(config=cfg, target_db_url=target_db_url)

    return extracted_count


def list_video_backups(config: Optional[Config] = None) -> List[Dict[str, Any]]:
    """Returns a list of available video backup ZIP files sorted newest first."""
    cfg = config or default_config
    backups_dir = get_backups_dir(cfg)

    archives = list(backups_dir.glob("kb_videos_backup_*.zip"))
    archives.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    result = []
    for archive in archives:
        stat = archive.stat()
        result.append(
            {
                "filename": archive.name,
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created_at": datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "path": str(archive),
            }
        )
    return result


def delete_video_backup_zip(
    filename: str, config: Optional[Config] = None
) -> bool:
    """Deletes a video backup archive from the backups directory."""
    cfg = config or default_config
    backups_dir = get_backups_dir(cfg)
    clean_name = os.path.basename(filename)
    target = backups_dir / clean_name
    if target.exists() and target.is_file() and target.name.startswith("kb_videos_backup_"):
        target.unlink()
        return True
    return False
