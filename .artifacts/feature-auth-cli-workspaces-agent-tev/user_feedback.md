# User Feedback - Authentication Hardening, CLI Restart, Workspace Versioning & Agent Tools with Tev1

## User Request Summary
- **Date**: 2026-10-02
- **Context & Feedback**:
  1. **Authentication & Server Recovery after Power Loss**:
     - A power loss state at the user's house caused the server to reboot.
     - Upon spinning back up, the authentication mechanism broke and the user was unable to log back in until returning home and running a restart script.
     - Requested: A remote restart command from the CLI (`kb-web-cli restart`) to cleanly reboot/reload the service.
     - Requested: Investigate and harden the authentication mechanism against sudden restarts/power loss so credentials and session states remain consistent even if the database is in recovery or slow to start.
  2. **CLI Authentication Failure (401 Unauthorized)**:
     - Following authentication hardening, `kb-web-cli` stopped working with `Error 401: {"detail":"Unauthorized: Authentication required."}` when submitting requests like `kb-web-cli import 'https://test.com/some-page'`.
     - Root cause: The global authentication middleware only checked the hardcoded server API key (`KB_API_KEY`) and session cookies, failing to validate registered client CLI API keys stored in the database (`CliApiKey` / `cli_api_keys`).
  3. **Coding REPL / Workspace Additions**:
     - Workspaces are morphing into live-editable repositories for scripts (e.g. `pythonrc.py`, PowerShell Profiles, multi-device scratch pads).
     - Sub-class / feature for workspace version control: track file versions and create tagged, immutable snapshots of workspace files at a given state.
     - Frozen workspace versions should be viewable as Knowledge Base articles.
  4. **Workspace Coding Agent Tools**:
     - Enhance the workspace coding agent with legitimate tools:
       - Create files by choice with names and optional annotations.
       - Read sections of files instead of piping entire workspace content into the system prompt.
       - Edit files via target/replacement tools.
     - Implement a terminal harness for interactive coding agent pairing directly from the CLI.
  5. **Incorporate `tev1` Decision Agent**:
     - Incorporate the `tev1` decision model (`tev1:latest` / `tev1:4b`).
     - Use `ollama.systemone(...)` directly through the project's `ollama` dependency (updated to `>=0.6.3`) without requiring external SDK packages.
     - Use `tev1` in the agent harness for fast, structured decision making, classification, and gating.
