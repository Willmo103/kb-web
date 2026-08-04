#!/usr/bin/env python3
"""
Python script to generate standardized VCS testing artifacts (reports & logs) in uat/
"""
import argparse
import datetime
import os
import subprocess
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Generate UAT Testing Artifact for VCS")
    parser.add_argument("--task", default="ui_update", help="Task or feature name")
    parser.add_argument("--tester", default="Agent & User", help="Tester name")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[4]
    uat_dir = repo_root / "uat"
    reports_dir = uat_dir / "reports"
    logs_dir = uat_dir / "logs"

    reports_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"test_log_{args.task}_{timestamp}.log"
    report_file = reports_dir / f"uat_report_{args.task}_{timestamp}.md"

    # Run pytest and record log
    pytest_cmd = ["uv", "run", "pytest"]
    if os.name == "nt":
        venv_pytest = repo_root / ".venv" / "Scripts" / "pytest.exe"
        if venv_pytest.exists():
            pytest_cmd = [str(venv_pytest)]
        else:
            pytest_cmd = ["pytest"]
    else:
        venv_pytest = repo_root / ".venv" / "bin" / "pytest"
        if venv_pytest.exists():
            pytest_cmd = [str(venv_pytest)]
        else:
            pytest_cmd = ["pytest"]

    pytest_res = subprocess.run(pytest_cmd, capture_output=True, text=True, cwd=str(repo_root))
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("=== PYTEST OUTPUT LOG ===\n")
        f.write(pytest_res.stdout)
        if pytest_res.stderr:
            f.write("\n=== STDERR ===\n" + pytest_res.stderr)

    # Get git branch and commit hash
    branch_res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, cwd=str(repo_root))
    branch = branch_res.stdout.strip() if branch_res.returncode == 0 else "unknown"

    commit_res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=str(repo_root))
    commit = commit_res.stdout.strip() if commit_res.returncode == 0 else "unknown"

    template_file = Path(__file__).parent.parent / "templates" / "uat_report_template.md"
    if template_file.exists():
        template_text = template_file.read_text(encoding="utf-8")
    else:
        template_text = "# UAT Report\n\nTask: {{ TASK_NAME }}\nDate: {{ DATE }}\n"

    test_log_summary = pytest_res.stdout.strip().split("\n")[-5:]
    summary_str = "\n".join(test_log_summary)

    content = template_text.replace("{{ TASK_NAME }}", args.task)
    content = content.replace("{{ DATE }}", datetime.datetime.now().strftime("%B %d, %Y %H:%M"))
    content = content.replace("{{ BRANCH }}", branch)
    content = content.replace("{{ TESTER }}", args.tester)
    content = content.replace("{{ COMPONENTS }}", "FastAPI UI Templates, Jinja2, Chrome Extension, Qdrant/Ollama integration")
    content = content.replace("{{ COMMIT_HASH }}", commit)
    content = content.replace("{{ TEST_LOG_SUMMARY }}", summary_str)

    report_file.write_text(content, encoding="utf-8")
    print(f"[SUCCESS] Generated VCS UAT Log: {log_file}")
    print(f"[SUCCESS] Generated VCS UAT Report: {report_file}")

if __name__ == "__main__":
    main()
