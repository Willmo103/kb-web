#!/usr/bin/env python3
"""
Engine to generate interactive, single-page HTML code audit and review reports
with ready-to-post GitHub issues, filtering, search, and selection tools.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "audit_report_template.html"


def generate_report(
    findings: List[Dict[str, Any]],
    repo: str,
    title: str = "Code Audit — Findings & Proposed Issues",
    eyebrow: Optional[str] = None,
    lede: Optional[str] = None,
    recommendations_html: Optional[str] = None,
    output_path: Optional[Path] = None,
    audit_name: Optional[str] = None,
) -> str:
    """Renders the standalone interactive HTML report from structured findings."""
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template not found at: {TEMPLATE_PATH}")

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    audit_name = audit_name or f"{repo.replace('/', '-')}-audit-{now_iso}"
    eyebrow = eyebrow or f"{repo} · Code Audit · {now_iso}"
    lede = lede or (
        f"A comprehensive review of {repo}. "
        "Each card contains the exact GitHub issue text ready to be posted. "
        "Select issues, add reviewer notes, and use the action dock to export or generate issues."
    )

    if not recommendations_html:
        recommendations_html = (
            "<ol>"
            "<li><b>High Priority / Security:</b> Address critical and high-severity items first.</li>"
            "<li><b>Bugs & Correctness:</b> Fix functional defects and broken error flows.</li>"
            "<li><b>Tooling & Guardrails:</b> Establish checks and tests to prevent regressions.</li>"
            "<li><b>Hygiene & Performance:</b> Optimize resource usage, clean logs, and synchronize configuration.</li>"
            "</ol>"
        )

    # Separate metadata from markdown bodies
    issues_meta = []
    bodies_tags = []

    for item in findings:
        item_id = item.get("id", "AUDIT-00")
        body_text = item.get("body", item.get("sum", "")).strip()

        meta = {
            "id": item_id,
            "sev": item.get("sev", "Medium"),
            "cat": item.get("cat", "General"),
            "labels": item.get("labels", ["enhancement"]),
            "loc": item.get("loc", ""),
            "title": item.get("title", f"Issue {item_id}"),
            "sum": item.get("sum", ""),
        }
        if "status" in item and item["status"]:
            meta["status"] = item["status"]

        issues_meta.append(meta)
        escaped_body = body_text.replace("</script>", "<\\/script>")
        bodies_tags.append(
            f'<script type="text/markdown" data-id="{item_id}">\n{escaped_body}\n</script>'
        )

    template_str = TEMPLATE_PATH.read_text(encoding="utf-8")

    # String replacement tokens
    rendered = template_str
    replacements = {
        "{{ title }}": title,
        "{{ description_meta }}": f"Code audit findings and proposed GitHub issues for {repo}",
        "{{ eyebrow }}": eyebrow,
        "{{ lede }}": lede,
        "{{ repo }}": repo,
        "{{ audit_name }}": audit_name,
        "{{ issues_json }}": json.dumps(issues_meta, indent=2),
        "{{ bodies_html }}": "\n\n".join(bodies_tags),
        "{{ recommendations_html }}": recommendations_html,
    }

    for k, v in replacements.items():
        rendered = rendered.replace(k, v)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
        print(f"[OK] Audit report generated at: {out.resolve()}")

    return rendered


def main():
    parser = argparse.ArgumentParser(description="Generate interactive HTML code audit report")
    parser.add_argument("--input", "-i", type=str, help="Path to JSON file containing findings array")
    parser.add_argument("--output", "-o", type=str, required=True, help="Destination HTML file path")
    parser.add_argument("--repo", "-r", type=str, default="Willmo103/kb-web", help="GitHub repo (org/name)")
    parser.add_argument("--title", "-t", type=str, default="Code Audit — Findings & Proposed Issues", help="Report header title")
    parser.add_argument("--eyebrow", "-e", type=str, help="Eyebrow text above title")
    parser.add_argument("--lede", "-l", type=str, help="Lead description paragraph")

    args = parser.parse_args()

    if args.input:
        in_path = Path(args.input)
        if not in_path.exists():
            print(f"[ERROR] Input JSON file not found: {in_path}", file=sys.stderr)
            sys.exit(1)
        raw_data = json.loads(in_path.read_text(encoding="utf-8"))
    else:
        # Check stdin
        if not sys.stdin.isatty():
            raw_data = json.load(sys.stdin)
        else:
            print("[ERROR] Please specify --input file or provide JSON via stdin.", file=sys.stderr)
            sys.exit(1)

    if isinstance(raw_data, dict) and "findings" in raw_data:
        findings = raw_data["findings"]
        recs = raw_data.get("recommendations_html")
        repo = raw_data.get("repo", args.repo)
        title = raw_data.get("title", args.title)
    elif isinstance(raw_data, list):
        findings = raw_data
        recs = None
        repo = args.repo
        title = args.title
    else:
        print("[ERROR] JSON input must be a list of findings or object with 'findings' key.", file=sys.stderr)
        sys.exit(1)

    generate_report(
        findings=findings,
        repo=repo,
        title=title,
        eyebrow=args.eyebrow,
        lede=args.lede,
        recommendations_html=recs,
        output_path=Path(args.output),
    )


if __name__ == "__main__":
    main()
