# User Feedback

The user requested:
1. Create a CLI (using Typer, extending `cli.py` with a client subcommand group) and accompanying API router (`cli_api.py`) exposing admin tasks to the CLI.
2. Authenticate requests with an `X-API-KEY` header generated from the admin portal to register clients with their computer names.
3. Add CLI commands for:
   - Installing the CLI (registering client + saving credentials locally).
   - Listing available commands & help.
   - Posting URLs to the server for processing.
   - Listing `n` most recent articles/videos.
   - Triggering privileged operations (regenerate-wiki, download-video, regenerate-tags) for a specific article or video.
   - Listing collections and managing collection items.
   - Listing tags and managing tag associations.
   - Querying a RAG agent with context retrieval.
4. Implement this on a new branch `feature/server-admin-cli` off `production`.
