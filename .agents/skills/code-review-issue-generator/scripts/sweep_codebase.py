#!/usr/bin/env python3
"""
Automated static heuristics scanner for Python codebases and Jinja2 templates.
Can output a structured findings JSON to feed into generate_audit_report.py.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_PY_PATTERNS = {
    "SEC_SHELL_TRUE": {
        "pattern": r"shell\s*=\s*True",
        "sev": "High",
        "cat": "Security",
        "labels": ["security", "bug"],
        "title": "Security: Subprocess call uses shell=True",
        "sum": "Running commands with shell=True on Windows or Linux introduces command injection vulnerabilities.",
    },
    "SEC_EVAL_EXEC": {
        "pattern": r"(?<![\w.])(eval|exec)\(",
        "sev": "Critical",
        "cat": "Security",
        "labels": ["security"],
        "title": "Security: Dangerous dynamic evaluation using eval() or exec()",
        "sum": "Direct invocation of eval or exec allows arbitrary code execution if user input is passed.",
    },
    "SEC_SQL_INJECTION": {
        "pattern": r"(execute|text)\(\s*f[\"']",
        "sev": "High",
        "cat": "Security",
        "labels": ["security", "bug"],
        "title": "Security: Potential SQL injection via formatted f-string query",
        "sum": "Raw queries should use parameterized binding rather than Python string formatting.",
    },
    "SEC_SSRF_UNVERIFIED": {
        "pattern": r"verify\s*=\s*False",
        "sev": "Medium",
        "cat": "Security",
        "labels": ["security"],
        "title": "Security: SSL verification disabled (verify=False)",
        "sum": "Disabling TLS certificate verification makes outbound requests vulnerable to man-in-the-middle attacks.",
    },
    "RELIABILITY_BARE_EXCEPT": {
        "pattern": r"except(\s+Exception)?\s*:\s*\n\s*pass",
        "sev": "Low",
        "cat": "Code Quality",
        "labels": ["enhancement"],
        "title": "Reliability: Silent exception swallowing (except: pass)",
        "sum": "Swallowing exceptions without logging obscures underlying errors and operational failures.",
    },
    "RELIABILITY_NAIVE_DATETIME": {
        "pattern": r"datetime\.now\(\)",
        "sev": "Low",
        "cat": "Code Quality",
        "labels": ["enhancement"],
        "title": "Code Quality: Naive local datetime instead of timezone-aware UTC",
        "sum": "Use datetime.now(timezone.utc) to prevent timezone drift across client and server environments.",
    },
    "CODE_PRINT_STMT": {
        "pattern": r"^\s*print\(",
        "sev": "Low",
        "cat": "Code Quality",
        "labels": ["enhancement"],
        "title": "Code Quality: Unstructured print() calls in server code",
        "sum": "Replace standard print statements with structured logging for observability.",
    },
}


def sweep(root_path: Path, src_subdir: str = "src") -> list:
    src_path = root_path / src_subdir if (root_path / src_subdir).exists() else root_path
    findings = []
    py_hits = defaultdict(list)

    # 1. Python file scan
    for py_file in src_path.rglob("*.py"):
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for rule_id, rule_info in DEFAULT_PY_PATTERNS.items():
            for m in re.finditer(rule_info["pattern"], text, re.M):
                ln = text.count("\n", 0, m.start()) + 1
                line_snippet = text.splitlines()[ln - 1].strip()[:140]
                rel_loc = f"{py_file.relative_to(root_path)}:{ln}"
                py_hits[rule_id].append((rel_loc, line_snippet))

    for rule_id, hits in py_hits.items():
        if not hits:
            continue
        info = DEFAULT_PY_PATTERNS[rule_id]
        locations = ", ".join(h[0] for h in hits[:5])
        if len(hits) > 5:
            locations += f" (+{len(hits)-5} more)"

        body_lines = [
            f"## Summary\n{info['sum']}\n",
            f"**Occurrences ({len(hits)} total):**\n",
        ]
        for loc, snippet in hits[:10]:
            body_lines.append(f"- `{loc}`: `{snippet}`")
        if len(hits) > 10:
            body_lines.append(f"- ... and {len(hits) - 10} additional occurrences.")

        findings.append({
            "id": rule_id,
            "sev": info["sev"],
            "cat": info["cat"],
            "labels": info["labels"],
            "loc": locations,
            "title": f"{info['title']} ({len(hits)} occurrences)",
            "sum": info["sum"],
            "body": "\n".join(body_lines),
        })

    # 2. Template scans
    templates_path = src_path / "templates" if (src_path / "templates").exists() else root_path / "templates"
    if templates_path.exists():
        for t_file in sorted(templates_path.glob("**/*.html")):
            try:
                t = t_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            stripped = re.sub(r"<script.*?</script>", "", t, flags=re.S)
            stripped = re.sub(r"<!--.*?-->", "", stripped, flags=re.S)
            opens = len(re.findall(r"<div[\s>]", stripped))
            closes = len(re.findall(r"</div>", stripped))
            if opens != closes:
                findings.append({
                    "id": f"HTML_DIV_{t_file.stem.upper()}",
                    "sev": "Medium",
                    "cat": "HTML",
                    "labels": ["bug"],
                    "loc": str(t_file.relative_to(root_path)),
                    "title": f"HTML: Div tag imbalance in {t_file.name} (open={opens}, close={closes})",
                    "sum": f"Mismatched div tags detected in {t_file.name}. Can break flex/grid layouts.",
                    "body": f"Found {opens} opening `<div>` tags and {closes} closing `</div>` tags.",
                })

    return findings


def main():
    parser = argparse.ArgumentParser(description="Sweep codebase for security, quality, and HTML heuristics")
    parser.add_argument("--root", "-r", type=str, default=".", help="Root repository directory")
    parser.add_argument("--output", "-o", type=str, help="Save findings as JSON")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    findings = sweep(root)
    print(f"Discovered {len(findings)} heuristic findings.")

    if args.output:
        out = Path(args.output)
        out.write_text(json.dumps(findings, indent=2), encoding="utf-8")
        print(f"Saved findings JSON to {out}")
    else:
        print(json.dumps(findings, indent=2))


if __name__ == "__main__":
    main()
