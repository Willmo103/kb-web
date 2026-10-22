# Walkthrough — Fix YouTube Downloads Without Sound (Issue #112)

## Overview
Resolved the issue where YouTube video downloads via `/view/page` ("Download Video Offline") lacked sound.

---

## Changes Implemented

### 1. yt-dlp Video & Audio Format Selection (`src/kb_web/utils.py`)
- Updated `download_youtube_video(video_id, config_obj)`:
  - Dynamically reads `youtube_download_format` from `config_obj` (with fallback to `DEFAULT_YOUTUBE_DOWNLOAD_FORMAT`).
  - Sets `"merge_output_format": "mp4"` in `ydl_opts` to ensure yt-dlp uses `ffmpeg` to merge high-resolution adaptive video streams and dedicated audio streams into an MP4 container.

### 2. Rule 7 Configuration & Admin Exposure (`src/kb_web/config.py`, `src/kb_web/routers/admin.py`, `src/kb_web/templates/admin.j2.html`)
- Added `DEFAULT_YOUTUBE_DOWNLOAD_FORMAT = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"`.
- Added `youtube_download_format` property on `Config` (backed by PostgreSQL `settings_external` table and persisted to `~/.kb/configs/kb-web.json` on `config.save()`).
- Added editable setting in the Admin Portal under **Server Configurations** / **Operational Limits**.
- Added `youtube_download_format` field in `POST /admin/config` in `routers/admin.py`.

### 3. Tests & Verification (`tests/test_server.py`)
- Added `test_youtube_download_format_config_and_admin_update`:
  - Validates default setting value.
  - Validates property setter.
  - Validates updating via `POST /admin/config` with redirect 303.
- Enhanced `test_descriptive_video_download_and_resolution`:
  - Asserts `merge_output_format == "mp4"`.
  - Asserts audio format tag `ba` is requested.
- Ran template verification script: 25 templates checked, 0 warnings.
