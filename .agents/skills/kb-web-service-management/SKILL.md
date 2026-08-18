---
name: kb-web-service-management
description: Instructions for managing systemd services (kb-web.service and kb-web-mcp.service) and production server deployment.
---
# kb-web Service Management Skill

Use this skill when configuring or testing systemd service templates (`kb-web.service` and `kb-web-mcp.service`).

## Systemd Files
- `kb-web.service`: Main web app service running `gunicorn` / `uvicorn` FastAPI server.
- `kb-web-mcp.service`: Model Context Protocol server running `src/kb_web/mcp_server.py`.

## Verification Steps
1. Verify systemd unit files are located in package root.
2. Check environment variable bindings (`.env` file).
3. Test daemon launcher command via CLI:
   ```bash
   uv run kb-web serve --port 8050
   ```
4. Verify systemd service status:
   ```bash
   sudo systemctl status kb-web.service
   ```
