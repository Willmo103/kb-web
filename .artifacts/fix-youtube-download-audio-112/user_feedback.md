# User Feedback — fix/youtube-download-audio-112 (2026-10-17)

## User Request
- Fix YouTube video download issue: "The youtube video downloads, *seemingly*, arn't being downloaded with sound. The former videos that have been stored to the server via the download feature have sound when played back from the UI."
- Fix priority: "I have created all of the issues from the audit on the repo. I need the current youtube video fixed first."

## Root Cause
- In `src/kb_web/utils.py:1325`, `download_youtube_video()` configured yt-dlp with `"format": "mp4/best"`.
- Modern YouTube videos typically do not provide a 720p/1080p pre-muxed combined MP4 stream (only 360p format 18 legacy streams). When pre-muxed mp4 is absent, yt-dlp falls back to the best single stream matching `best`, which often selects video-only streams without audio.
- yt-dlp was not configured to download best video + best audio and merge them with ffmpeg (`merge_output_format: "mp4"`).
- Furthermore, under Rule 7 (Strict Configuration Transparency & Admin Exposure), the format selector should be user-configurable in the admin portal rather than hardcoded.
