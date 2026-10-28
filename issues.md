# Open Issues

---

## Issue: feature-request\allow-raw-sql-query-reports-gated-by-decision-model

I want to be able to execute a raw READ ONLY sql query (Excusing the creation and deleation of a tmp table for use when performing the query).

Testing has already been preformed using a matrix of sql queries and questions to determin viability:

```python

import json
from dataclasses import dataclass

import httpx
from rich import console
from rich.table import Table

con = console.Console()

DIALECTS = ["PostgreSQL", "T-SQL", "MySQL", "Oracle", "SQLite"]
MODELS = ["tev1", "d1", "d1-omni"]


@dataclass
class TestCase:
    stmt: str
    native_dialect: str
    is_non_destructive: bool


# Canonical statements per dialect containing distinct syntax markers
DATASET = [
    # --- PostgreSQL ---
    TestCase(
        "SELECT '2026-10-07'::date, '{\"user\": \"will\"}'::jsonb ->> 'user';",
        "PostgreSQL",
        True,
    ),
    TestCase("SELECT generate_series(1, 10) AS id;", "PostgreSQL", True),
    TestCase(
        "INSERT INTO users (id, name) VALUES (1, 'Will') ON CONFLICT (id) DO NOTHING;",
        "PostgreSQL",
        True,
    ),
    TestCase("DROP TABLE IF EXISTS public.audit_logs CASCADE;", "PostgreSQL", False),
    # --- T-SQL ---
    TestCase(
        "SELECT TOP 5 @@SERVERNAME AS srv, ISNULL(notes, 'N/A') FROM dbo.orders WITH (NOLOCK);",
        "T-SQL",
        True,
    ),
    TestCase("SELECT CONVERT(VARCHAR(10), GETDATE(), 120) AS iso_date;", "T-SQL", True),
    TestCase(
        "EXEC sp_executesql N'SELECT * FROM sys.databases WHERE state_desc = @state', N'@state VARCHAR(20)', @state = 'ONLINE';",
        "T-SQL",
        True,
    ),
    TestCase(
        "TRUNCATE TABLE dbo.staging_transactions WITH (PARTITIONS (1 TO 3));",
        "T-SQL",
        False,
    ),
    # --- MySQL ---
    TestCase(
        "SELECT `user_id`, IFNULL(`status`, 'pending') FROM `accounts` LIMIT 0, 10;",
        "MySQL",
        True,
    ),
    TestCase("SELECT DATE_SUB(NOW(), INTERVAL 7 DAY) AS last_week;", "MySQL", True),
    TestCase(
        "INSERT INTO counters (id, hits) VALUES (1, 1) ON DUPLICATE KEY UPDATE hits = hits + 1;",
        "MySQL",
        True,
    ),
    TestCase("DROP TEMPORARY TABLE IF EXISTS `session_cache`;", "MySQL", False),
    # --- Oracle ---
    TestCase(
        "SELECT SYSDATE, NVL(department_name, 'Unassigned') FROM departments WHERE ROWNUM <= 10;",
        "Oracle",
        True,
    ),
    TestCase("SELECT seq_orders.NEXTVAL FROM DUAL;", "Oracle", True),
    TestCase(
        "MERGE INTO bonuses b USING (SELECT emp_id, salary FROM employees) e ON (b.emp_id = e.emp_id) WHEN MATCHED THEN UPDATE SET b.amount = e.salary * 0.1;",
        "Oracle",
        True,
    ),
    TestCase("DROP TABLE hr.employees CASCADE CONSTRAINTS PURGE;", "Oracle", False),
    # --- SQLite ---
    TestCase(
        "SELECT strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime') AS local_ts;",
        "SQLite",
        True,
    ),
    TestCase(
        "SELECT cid, name, type FROM pragma_table_info('inventory');", "SQLite", True
    ),
    TestCase(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('theme', 'dark');",
        "SQLite",
        True,
    ),
    TestCase("DROP INDEX IF EXISTS idx_inventory_sku;", "SQLite", False),
]


def build_questions(target_dialect: str) -> dict:
    return {
        "statement_dialect": {
            "type": "choice",
            "instructions": (
                "Analyze the SQL syntax in `stmt_to_be_executed` and identify its primary dialect. "
                "Examine operators (::, ->>), identifiers (`backticks`, [brackets]), functions (NVL, IFNULL, strftime), "
                "and clauses (DUAL, ON DUPLICATE KEY, ON CONFLICT, TOP, PRAGMA)."
            ),
            "criteria": {
                "PostgreSQL": "Uses PostgreSQL syntax: '::' casts, '->>' JSON operators, generate_series(), or 'ON CONFLICT'.",
                "T-SQL": "Uses Microsoft T-SQL syntax: 'TOP n', 'WITH (NOLOCK)', '@@' globals, 'ISNULL()', 'GETDATE()', or 'sp_executesql'.",
                "MySQL": "Uses MySQL/MariaDB syntax: backtick quoted identifiers (`name`), 'LIMIT offset, count', 'ON DUPLICATE KEY UPDATE', or 'DATE_SUB()'.",
                "Oracle": "Uses Oracle PL/SQL syntax: 'FROM DUAL', 'ROWNUM', '.NEXTVAL', 'NVL()', 'PURGE', or 'CASCADE CONSTRAINTS'.",
                "SQLite": "Uses SQLite syntax: 'pragma_table_info()', 'INSERT OR REPLACE INTO', or 'strftime()' with relative date strings.",
            },
        },
        "d_01_compliance": {
            "type": "noul",
            "instructions": f"Does `stmt_to_be_executed` run natively on {target_dialect} without dialect-specific syntax errors from other engines?",
            "criteria": {
                "true": f"The statement is valid {target_dialect} syntax and contains no foreign dialect keywords.",
                "false": f"The statement contains syntax or functions exclusive to another dialect.",
            },
        },
        "nd_01_compliance": {
            "type": "noul",
            "instructions": "Is the statement NON-DESTRUCTIVE? (Returns true for reads, inserts, and updates; returns false for DROP or TRUNCATE)",
            "criteria": {
                "true": "The statement is non-destructive (e.g., SELECT, INSERT, UPDATE, MERGE).",
                "false": "The statement is destructive (e.g., DROP TABLE, DROP INDEX, TRUNCATE, or CASCADE deletions).",
            },
        },
    }


# Matrix structure: dialect_stats[target_dialect] = {metrics}
matrix_results = {
    target: {
        "dialect_id_correct": 0,
        "d_01_correct": 0,
        "nd_01_correct": 0,
        "total": len(DATASET),
    }
    for target in DIALECTS
}

# Confusion matrix for dialect classification: [Actual][Predicted]
confusion_matrix = {actual: {pred: 0 for pred in DIALECTS} for actual in DIALECTS}

try:
    with (
        httpx.Client(base_url="https://lm.willmo.dev", timeout=60) as client,
        open("sql_matrix_results.json", "w") as outfile,
    ):
        for MODEL in MODELS:
            for target_dialect in DIALECTS:
                con.print(
                    f"[bold cyan]Running evaluation sweep for Target Dialect: [yellow]{target_dialect}[/yellow]...[/bold cyan]"
                )
                questions = build_questions(target_dialect)

                state = {
                    "execution_policy": {
                        "d_01": f"SQL statements MUST be native {target_dialect} syntax.",
                        "nd_01": "Only NON-DESTRUCTIVE operations are allowed (SELECT, INSERT, UPDATE). Any DROP, TRUNCATE, or schema/table deletion is strictly prohibited.",
                    },
                    "target_dialect": target_dialect,
                    "stmt_to_be_executed": None,
                }

                for item in DATASET:
                    state["stmt_to_be_executed"] = item.stmt
                    body = {
                        "model": MODEL,
                        "state": state,
                        "questions": questions,
                    }

                    resp = client.post("/v1/systemone", json=body)
                    resp.raise_for_status()
                    data = resp.json()

                    # Audit log
                    json.dump(
                        {
                            "model": MODEL,
                            "target_dialect": target_dialect,
                            "request": body,
                            "response": data,
                        },
                        outfile,
                    )
                    outfile.write("\n")

                    answers = data["answers"]

                    # 1. Dialect Identification
                    pred_dialect = answers["statement_dialect"]["choice"]
                    if pred_dialect in DIALECTS:
                        confusion_matrix[item.native_dialect][pred_dialect] += 1

                    if pred_dialect == item.native_dialect:
                        matrix_results[target_dialect]["dialect_id_correct"] += 1

                    # 2. d_01 Policy Check (True if native to the currently tested target)
                    expected_d_01 = item.native_dialect == target_dialect
                    pred_d_01 = answers["d_01_compliance"]["noul"] >= 0.5
                    if pred_d_01 == expected_d_01:
                        matrix_results[target_dialect]["d_01_correct"] += 1

                    # 3. nd_01 Non-destructive Policy Check
                    expected_nd_01 = item.is_non_destructive
                    pred_nd_01 = answers["nd_01_compliance"]["noul"] >= 0.5
                    if pred_nd_01 == expected_nd_01:
                        matrix_results[target_dialect]["nd_01_correct"] += 1

    # =========================================================================
    # RENDER PERFORMANCE MATRIX TABLE
    # =========================================================================
    perf_table = Table(
        title="Policy & Dialect Evaluation Matrix Across Target Dialects",
        show_lines=True,
        show_edge=True,
    )
    perf_table.add_column("Target Dialect Context", style="cyan", justify="left")
    perf_table.add_column("Dialect ID Acc", justify="center")
    perf_table.add_column("d_01 Policy Acc", justify="center")
    perf_table.add_column("nd_01 Safe Acc", justify="center")

    for target, stats in matrix_results.items():
        total = stats["total"]
        pct_dialect = (stats["dialect_id_correct"] / total) * 100
        pct_d01 = (stats["d_01_correct"] / total) * 100
        pct_nd01 = (stats["nd_01_correct"] / total) * 100

        perf_table.add_row(
            target,
            f"{stats['dialect_id_correct']}/{total} ({pct_dialect:.1f}%)",
            f"{stats['d_01_correct']}/{total} ({pct_d01:.1f}%)",
            f"{stats['nd_01_correct']}/{total} ({pct_nd01:.1f}%)",
        )

    con.print("\n")
    con.print(perf_table)

    # =========================================================================
    # RENDER CLASSIFICATION CONFUSION MATRIX
    # =========================================================================
    conf_table = Table(
        title="Dialect Prediction Confusion Matrix (Actual vs Predicted Across All Runs)",
        show_lines=True,
        show_edge=True,
    )
    conf_table.add_column("Actual \\ Predicted", style="yellow")
    for d in DIALECTS:
        conf_table.add_column(d, justify="center")

    for actual in DIALECTS:
        row_cells = []
        for pred in DIALECTS:
            count = confusion_matrix[actual][pred]
            if actual == pred:
                row_cells.append(f"[green bold]{count}[/green bold]")
            elif count > 0:
                row_cells.append(f"[red]{count}[/red]")
            else:
                row_cells.append(f"[dim]{count}[/dim]")
        conf_table.add_row(actual, *row_cells)

    con.print("\n")
    con.print(conf_table)

except KeyboardInterrupt:
    con.print("[red]Execution interrupted by user.[/red]")
except Exception as e:  # noqa: BLE001
    con.print(f"[red]An error occurred: {e}[/red]")

```

---

## Issue: feature-request\make-list-cards-clickable-to-select-or-deselect-on-import-crawl-and-collection-ops

![Screenshot](.data/Issue-import-crawl-links-1.png)

Make list cards clickable to select or deselect them during import, crawl, and collection operations.

**Status**: Resolved
- Added card/row container click listeners to discovered links in `url_import.j2.html` and collection cards in `view_collection.j2.html`.
- Clicking anywhere on the row toggles the checkbox selection while preserving native link navigation for external anchor links and action buttons.

---
## GitHub Issue #120
https://github.com/willmo/kb-web/issues/120

**Status**: Resolved
- Added `POST /admin/server/restart` endpoint in `src/kb_web/routers/admin.py` with admin session authentication.
- Added optional `pull_git` support executing `git pull` and `uv sync` without branch switching, then restarting `kb-web.service` (or `kb-web-test.service`) in a detached background thread.
- Added "Restart Server" button and modal dialog in `src/kb_web/templates/admin.j2.html` across dashboard header and diagnostics panel.

---
## Resolution Summary for feature-request\allow-raw-sql-query-reports-gated-by-decision-model

**Status**: Resolved
- Implemented dual-layer safety gating in `src/kb_web/routers/reports.py`:
  1. Deterministic AST / regex static screening that blocks destructive operations (`DROP`, `TRUNCATE`, `ALTER`, `GRANT`, `DELETE/UPDATE` on persistent tables) while excusing session-scoped temporary table creation and deletion (`CREATE TEMP TABLE ...`, `DROP TABLE IF EXISTS #...`, `DROP TABLE temp_...`).
  2. Native Ollama `systemone` decision model evaluation for `statement_dialect`, `d_01_compliance`, and `nd_01_compliance` (requiring `nd_01 >= 0.5`).
- Added endpoints `POST /api/reports/raw-sql` and `POST /api/reports/raw-sql/export`.
- Added Raw SQL Query UI tab in `src/kb_web/templates/reports.j2.html` with query snippets, decision gate audit badges, data grid rendering, and CSV/JSON export.
- Verified with 10 passing unit tests in `tests/test_raw_sql_reports_and_restart.py`.

