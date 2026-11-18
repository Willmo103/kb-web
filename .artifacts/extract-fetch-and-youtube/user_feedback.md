# User Feedback: Standalone Webpage Fetcher & YouTube Downloader Scripts

## Request Context 1
- **Date**: 2026-11-11
- **Prompt**:
  > extract the logic for fetching a webpage as a script, do the same for downloading a youtube video. include the classes in the scripts. write these scripts directly in the .artifacts folder created for this task and do not commit anything to the git history.

## Request Context 2
- **Date**: 2026-11-11
- **Prompt**:
  > can you make these typer cli apps please

## Directives
1. **Typer CLI Migration**:
   - Refactor CLI entrypoints in `fetch_webpage.py` and `download_youtube.py` to use `typer.Typer(no_args_is_help=True)` with rich help formatting, type hints, `typer.Argument`, and `typer.Option`.
2. **Subcommands & Features**:
   - `fetch_webpage.py`:
     - Default command: fetch webpage, clean HTML, extract links, and convert to Markdown.
     - Options: `--output / -o`, `--markdown-only`, `--json`, `--allow-internal`, `--timeout`.
   - `download_youtube.py`:
     - Commands / Options:
       - `download` (or default): download video + audio merged to MP4.
       - `info` / `--metadata-only`: inspect metadata, creator, duration, views.
       - `transcript` / `--transcript-only`: print timestamped transcript.
       - Options: `--audio-only`, `--output-dir / -o`, `--format`, `--overwrite`, `--json`.
3. **VCS Constraint**:
   - Keep scripts in `.artifacts/extract-fetch-and-youtube/`.
   - **DO NOT** commit anything to git.
