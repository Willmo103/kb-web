# Implementation Plan — Fix YouTube Downloads Without Audio (Issue #112)

## Problem Statement
When downloading YouTube videos via the web UI ("Download Video Offline" button in `/view/page`), downloaded `.mp4` video files are saved without audio.
The current configuration uses `"format": "mp4/best"`, which fails to fetch audio streams when YouTube serves separate adaptive video and audio streams (DASH/HLS).

## Solution Overview
1. **yt-dlp Format & Remuxing Configuration** (`src/kb_web/utils.py`):
   - Update `download_youtube_video()` to read `youtube_download_format` from `config` (falling back to a robust default: `bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b`).
   - Add `"merge_output_format": "mp4"` to `ydl_opts` so yt-dlp automatically invokes ffmpeg to mux video and audio tracks into a standard MP4 file.
   - Use yt-dlp's downloaded files metadata callback or `ydl.prepare_filename(info)` for deterministic path resolution.

2. **Rule 7 Configuration Exposure** (`src/kb_web/config.py`, `src/kb_web/routers/admin.py`, `src/kb_web/templates/admin.j2.html`):
   - Add `youtube_download_format` property on `Config` backed by `settings_external` table and persistent in `kb-web.json`.
   - Default: `bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b`.
   - Expose `youtube_download_format` in the Admin Portal under **Media & YouTube** / **Server Configurations**.
   - Add support in `POST /admin/config` in `routers/admin.py`.

3. **Regression Tests** (`tests/test_server.py`):
   - Enhance `test_download_youtube_video_naming_and_resolution` to verify `format` and `merge_output_format` passed to `yt_dlp.YoutubeDL`.
   - Add test verifying `config.youtube_download_format` property persistence and admin updating.

4. **Self-Documentation**:
   - Update `CHANGELOG.md` under `[0.5.9]` (or next version header).
   - Generate walkthrough artifact in `.artifacts/fix-youtube-download-audio-112/walkthrough.md`.
