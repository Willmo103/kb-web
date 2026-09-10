---
name: ui-component-uat-check
description: Automated pre-commit verification tool for checking Jinja2 UI templates, CSS themes, and route safety in kb-web.
---
# UI Component UAT Check Skill

Use this skill to run automated structural and aesthetic checks on UI templates in `src/kb_web/templates/` before conducting manual UAT or committing code.

## Workflow

1. Execute the verification script:
   ```bash
   uv run python .agent/skills/ui-component-uat-check/scripts/verify_ui_templates.py
   ```
2. The script checks:
   - Jinja2 syntax and structural completeness.
   - Presence of Solarized Light (`#fdf6e3`) and Retro Dark theme variables.
   - Route URL bindings across templates.
3. Review console output and resolve any template warnings before proceeding.
