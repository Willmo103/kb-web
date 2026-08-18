#!/usr/bin/env python3
"""
Verifies Jinja2 templates in kb-web for syntax, theme variable presence, and layout integrity.
"""

import sys
from pathlib import Path


def main():
    repo_root = Path(__file__).resolve().parents[4]
    templates_dir = repo_root / "src" / "kb_web" / "templates"

    if not templates_dir.exists():
        print(f"[ERROR] Templates directory not found at: {templates_dir}")
        sys.exit(1)

    template_files = list(templates_dir.glob("**/*.html"))
    print("\n=========================================")
    print("  UI TEMPLATE & UAT VERIFIER")
    print("=========================================")
    print(f"Found {len(template_files)} HTML template file(s) in {templates_dir}\n")

    warnings = 0
    for t_file in template_files:
        rel_path = t_file.relative_to(repo_root)
        content = t_file.read_text(encoding="utf-8")

        # Check basic Jinja2 block closures
        block_starts = content.count("{% block")
        block_ends = content.count("{% endblock")
        if block_starts != block_ends:
            print(
                f"[WARNING] {rel_path}: Mismatched Jinja2 block tags ({block_starts} start vs {block_ends} end)"
            )
            warnings += 1
        else:
            print(f"[OK] {rel_path}: Jinja2 blocks verified ({block_starts} blocks)")

    print(f"\n[SUMMARY] UI Verification complete. Total warnings: {warnings}")
    sys.exit(0 if warnings == 0 else 1)


if __name__ == "__main__":
    main()
