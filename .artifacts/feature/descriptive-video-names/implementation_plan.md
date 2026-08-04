# Implementation Plan - Descriptive Video Names

This plan details the changes to download YouTube videos with descriptive filenames (`[Creator] - Title [VideoId].mp4`) and to resolve these files dynamically on the video details/player pages.

## User Review Required

> [!IMPORTANT]
> 1. **Filename Format**: Videos will be downloaded as `[Uploader] - Video Title [VideoId].mp4` (sanitized for safe filesystem names).
> 2. **Dynamic Matching**: The server will dynamically scan the media directory for any file containing the `VideoId` to detect if the video has been saved offline, allowing cross-system portability (even if database paths mismatch).

## Open Questions

There are no open questions.

## Proposed Changes

---

### Ingestion & Downloader

#### [MODIFY] [utils.py](file:///c:/src/kb-web/src/kb_web/utils.py)
- Update `download_youtube_video` to construct descriptive filenames:
  - First, attempt to load the video uploader (creator) and title from the database (`youtube_videos` and `fetched_pages` tables).
  - If not found, use `yt-dlp` info dictionary extraction to parse `uploader` and `title` before downloading.
  - Sanitize the title and creator strings to make them safe for cross-platform filesystems.
  - Run the download with template `[Creator] - Title [VideoId].%(ext)s` and ensure final output is renamed to `.mp4`.

---

### Pages Router & Player

#### [MODIFY] [pages.py](file:///c:/src/kb-web/src/kb_web/routers/pages.py)
- In the `/view/page` endpoint, update offline video detection:
  - First, check if `local_path` from the database exists on disk.
  - Second, check if the legacy path `{video_id}.mp4` exists.
  - Third, scan `media/videos/` for any file matching `*{video_id}*` using glob pattern.
  - Resolve the correct `local_video_url` using the matched file's actual basename (e.g. `/media/videos/[Creator] - Title [VideoId].mp4`) rather than hardcoding `/media/videos/{video_id}.mp4`.

## Verification Plan

### Automated Tests
- Add a new unit test `test_descriptive_video_download_and_resolution` in `tests/test_server.py` verifying:
  - Descriptive filename generation.
  - Resolution of descriptive names in the page view page.
- Run `uv run pytest` to ensure all 40+ tests pass.

### Manual Verification
- Trigger video download from UI and verify that the file downloaded in `media/videos/` is named descriptively.
- Refresh page and verify `Saved Offline` badge displays and player loads the custom local MP4 path correctly.
