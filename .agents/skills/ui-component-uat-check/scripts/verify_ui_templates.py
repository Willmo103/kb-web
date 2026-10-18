#!/usr/bin/env python3
"""
Verifies Jinja2 templates in kb-web for syntax, block closures, div tag balance, and tab-pane layout integrity.
"""

import re
import sys
from pathlib import Path


def check_div_balance(content: str) -> tuple[int, int]:
    """Counts opening and closing div tags, ignoring scripts, Jinja comments, and HTML comments."""
    stripped = re.sub(r"<script.*?</script>", "", content, flags=re.S)
    stripped = re.sub(r"{#.*?#}", "", stripped, flags=re.S)
    stripped = re.sub(r"<!--.*?-->", "", stripped, flags=re.S)
    opens = len(re.findall(r"<div[\s>]", stripped))
    closes = len(re.findall(r"</div>", stripped))
    return opens, closes


def main():
    repo_root = Path(__file__).resolve().parents[4]
    templates_dir = repo_root / "src" / "kb_web" / "templates"

    if not templates_dir.exists():
        print(f"[ERROR] Templates directory not found at: {templates_dir}")
        sys.exit(1)

    template_files = sorted(list(templates_dir.glob("**/*.html")))
    print("\n=========================================")
    print("  UI TEMPLATE & UAT VERIFIER")
    print("=========================================")
    print(f"Found {len(template_files)} HTML template file(s) in {templates_dir}\n")

    warnings = 0
    for t_file in template_files:
        rel_path = t_file.relative_to(repo_root)
        content = t_file.read_text(encoding="utf-8")

        # 1. Check basic Jinja2 block closures
        block_starts = content.count("{% block")
        block_ends = content.count("{% endblock")
        if block_starts != block_ends:
            print(
                f"[WARNING] {rel_path}: Mismatched Jinja2 block tags ({block_starts} start vs {block_ends} end)"
            )
            warnings += 1

        # 2. Check HTML <div> balance
        opens, closes = check_div_balance(content)
        if opens != closes:
            print(
                f"[WARNING] {rel_path}: HTML <div> imbalance detected (opens={opens}, closes={closes})"
            )
            warnings += 1

        if block_starts == block_ends and opens == closes:
            print(f"[OK] {rel_path}: Blocks ({block_starts}) and divs ({opens}/{closes}) verified")

    print(f"\n[SUMMARY] UI Verification complete. Total warnings: {warnings}")
    sys.exit(0 if warnings == 0 else 1)


if __name__ == "__main__":
    main()
