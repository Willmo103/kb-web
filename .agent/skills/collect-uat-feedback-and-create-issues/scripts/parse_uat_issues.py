#!/usr/bin/env python3
"""
Parses saved UAT JSON feedback data into actionable agent issues and task specs.
"""
import argparse
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Parse UAT JSON feedback into agent issues")
    parser.add_argument("--json-path", default="scratch/uat_feedback_data.json", help="Path to saved JSON file")
    args = parser.parse_args()

    json_file = Path(args.json_path)
    if not json_file.exists():
        print(f"[ERROR] Specified JSON file does not exist: {json_file}")
        return

    data = json.loads(json_file.read_text(encoding="utf-8"))
    task_name = data.get("task_name", "uat_task")
    tester = data.get("tester", "User")
    verdict = data.get("verdict", "UNKNOWN")
    issues = data.get("issues", [])

    print(f"\n=========================================")
    print(f"  UAT ISSUE PARSER & TASK GENERATOR")
    print(f"=========================================")
    print(f"Task: {task_name}")
    print(f"Tester: {tester}")
    print(f"Overall Verdict: {verdict}")
    print(f"Total Reported Issues: {len(issues)}\n")

    output_lines = [
        f"# UAT Actionable Issues Report: {task_name}",
        f"- **Tester**: {tester}",
        f"- **Overall Verdict**: {verdict}",
        f"- **Parsed Issues Count**: {len(issues)}\n",
        "## Agent Action Items\n"
    ]

    for idx, item in enumerate(issues, 1):
        title = item.get("title", "Untitled Issue")
        category = item.get("category", "General")
        severity = item.get("severity", "Major")
        desc = item.get("description", "No description provided")
        fix = item.get("requested_fix", "Investigate and resolve")

        print(f"[{idx}] [{severity}] [{category}] {title}")
        print(f"    Description: {desc}")
        print(f"    Agent Action: {fix}\n")

        output_lines.append(f"### Issue #{idx}: [{severity}] {title}")
        output_lines.append(f"- **Category**: {category}")
        output_lines.append(f"- **Description**: {desc}")
        output_lines.append(f"- **Required Action**: {fix}\n")

    output_file = json_file.parent / f"{task_name}_parsed_issues.md"
    output_file.write_text("\n".join(output_lines), encoding="utf-8")
    print(f"[SUCCESS] Parsed {len(issues)} issue(s) into agent task file: {output_file}")

if __name__ == "__main__":
    main()
