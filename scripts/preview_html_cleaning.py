#!/usr/bin/env python3
"""
Interactive HTML Cleaning & Markdown Preview Tool for kb-web.

Samples imported HTML pages from the database, strips boilerplate, converts
to clean Markdown, and generates an interactive side-by-side visual HTML comparison report.

Default mode is DRY RUN (safe inspection, no database writes).
Pass --apply to persist cleaned markdown to fetched_pages (with automatic version archival).
"""

import argparse
from datetime import datetime
import html
import hashlib
from pathlib import Path
import sys

# Ensure src is on python path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

from kb_web.base import db_session
from kb_web.models_orm import FetchedPage, PageVersion
from kb_web.html_cleaner import html_to_clean_markdown, compare_markdown_cleaning


def generate_html_comparison_report(results: list, output_path: Path):
    """Generates an aesthetic, interactive side-by-side comparison HTML document."""
    total_orig = sum(r["original_len"] for r in results)
    total_clean = sum(r["cleaned_len"] for r in results)
    overall_reduction = round(((total_orig - total_clean) / total_orig * 100), 2) if total_orig > 0 else 0.0

    cards_html = []
    for idx, r in enumerate(results, start=1):
        orig_escaped = html.escape(r["original_md"] or "(empty)")
        clean_escaped = html.escape(r["cleaned_md"] or "(empty)")
        title_escaped = html.escape(r["title"] or r["url"])
        url_escaped = html.escape(r["url"])
        badge_color = "#10b981" if r["reduction_pct"] > 0 else "#6b7280"

        cards_html.append(f"""
        <div class="article-card" id="article-{idx}">
            <div class="card-header">
                <div class="card-title-group">
                    <span class="card-index">#{idx}</span>
                    <h2 class="card-title">{title_escaped}</h2>
                </div>
                <div class="card-meta">
                    <a href="{url_escaped}" target="_blank" class="card-link">{url_escaped}</a>
                    <span class="badge" style="background-color: {badge_color}">
                        {r['reduction_pct']}% noise reduction (-{r['char_diff']:,} chars)
                    </span>
                </div>
            </div>

            <div class="metrics-bar">
                <span>Original: <strong>{r['original_len']:,} chars</strong> ({r['original_lines']} lines)</span>
                <span>&rarr;</span>
                <span>Cleaned: <strong>{r['cleaned_len']:,} chars</strong> ({r['cleaned_lines']} lines)</span>
            </div>

            <div class="comparison-grid">
                <div class="column">
                    <div class="column-header original">
                        <span>Original Raw Markdown (with header/nav clutter)</span>
                    </div>
                    <pre class="code-box">{orig_escaped}</pre>
                </div>
                <div class="column">
                    <div class="column-header cleaned">
                        <span>Sanitized Clean Markdown (core content only)</span>
                    </div>
                    <pre class="code-box">{clean_escaped}</pre>
                </div>
            </div>
        </div>
        """)

    report_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HTML Cleaning & Markdown Preview Report</title>
    <style>
        :root {{
            --bg: #0f172a;
            --card-bg: #1e293b;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --border: #334155;
            --accent: #38bdf8;
            --orig-header: #ef4444;
            --clean-header: #10b981;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            padding: 24px;
            line-height: 1.5;
        }}
        .header {{
            max-width: 1400px;
            margin: 0 auto 24px auto;
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3);
        }}
        .header h1 {{ font-size: 24px; font-weight: 700; color: #fff; margin-bottom: 8px; }}
        .header p {{ color: var(--text-muted); font-size: 14px; margin-bottom: 16px; }}
        .summary-stats {{
            display: flex;
            gap: 24px;
            flex-wrap: wrap;
            border-top: 1px solid var(--border);
            padding-top: 16px;
        }}
        .stat-item {{ display: flex; flex-direction: column; }}
        .stat-label {{ font-size: 12px; text-transform: uppercase; color: var(--text-muted); font-weight: 600; }}
        .stat-value {{ font-size: 20px; font-weight: 700; color: var(--accent); }}
        .article-card {{
            max-width: 1400px;
            margin: 0 auto 32px auto;
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
        }}
        .card-header {{
            padding: 16px 20px;
            border-bottom: 1px solid var(--border);
            background: rgba(15, 23, 42, 0.6);
        }}
        .card-title-group {{ display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }}
        .card-index {{
            background: var(--border);
            color: var(--accent);
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 6px;
            font-size: 12px;
        }}
        .card-title {{ font-size: 18px; font-weight: 600; color: #fff; }}
        .card-meta {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }}
        .card-link {{ color: var(--accent); font-size: 13px; text-decoration: none; word-break: break-all; }}
        .card-link:hover {{ text-decoration: underline; }}
        .badge {{
            font-size: 12px;
            font-weight: 600;
            padding: 4px 10px;
            border-radius: 9999px;
            color: #fff;
        }}
        .metrics-bar {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 20px;
            background: #111827;
            border-bottom: 1px solid var(--border);
            font-size: 13px;
            color: var(--text-muted);
        }}
        .metrics-bar strong {{ color: #e2e8f0; }}
        .comparison-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            min-height: 480px;
            max-height: 700px;
        }}
        @media (max-width: 900px) {{
            .comparison-grid {{ grid-template-columns: 1fr; max-height: none; }}
        }}
        .column {{
            display: flex;
            flex-direction: column;
            overflow: hidden;
            border-right: 1px solid var(--border);
        }}
        .column:last-child {{ border-right: none; }}
        .column-header {{
            padding: 8px 16px;
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #fff;
        }}
        .column-header.original {{ background: #991b1b; }}
        .column-header.cleaned {{ background: #065f46; }}
        .code-box {{
            flex: 1;
            padding: 16px;
            background: #090d16;
            color: #cbd5e1;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 12px;
            line-height: 1.6;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-word;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🧼 HTML Boilerplate Cleaner: Before & After Markdown Comparison</h1>
        <p>Interactive verification report for sampled database articles before applying updates.</p>
        <div class="summary-stats">
            <div class="stat-item">
                <span class="stat-label">Sampled Articles</span>
                <span class="stat-value">{len(results)}</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Total Character Reduction</span>
                <span class="stat-value">-{total_orig - total_clean:,} chars</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Average Noise Reduction</span>
                <span class="stat-value">{overall_reduction}%</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Mode</span>
                <span class="stat-value" style="color: #f59e0b;">DRY-RUN PREVIEW</span>
            </div>
        </div>
    </div>

    {''.join(cards_html)}
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_html, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Preview and apply HTML boilerplate stripping to markdown.")
    parser.add_argument("--sample", type=int, default=5, help="Number of real database pages to sample (default: 5)")
    parser.add_argument("--url", type=str, default=None, help="Specific page URL in database to clean and inspect")
    parser.add_argument("--fetch-url", type=str, default=None, help="Fetch a live web URL on the fly to test cleaning")
    parser.add_argument("--output-html", type=Path, default=None, help="Path to write the interactive HTML preview report")
    parser.add_argument("--apply", action="store_true", help="Apply cleaned markdown to database (defaults to dry-run)")
    args = parser.parse_args()

    print("=" * 65)
    print("🧼 kb-web HTML Boilerplate Stripper & Markdown Cleaner")
    print(f"Mode: {'⚠️ APPLY TO DATABASE' if args.apply else '🔍 DRY RUN (SAFE PREVIEW)'}")
    print("=" * 65)

    default_report_path = project_root / ".artifacts" / "feature-html-boilerplate-stripper-and-cleaner" / "html_cleaning_preview.html"
    output_report = args.output_html or default_report_path

    if args.fetch_url:
        import httpx
        from html2text import HTML2Text
        print(f"\n[FETCH] Fetching live URL: {args.fetch_url}...")
        resp = httpx.get(args.fetch_url, timeout=15, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        raw_html = resp.text
        raw_h = HTML2Text()
        raw_h.ignore_links = True
        raw_md = raw_h.handle(raw_html)

        comp = compare_markdown_cleaning(raw_html, raw_md)
        results = [{
            "url": args.fetch_url,
            "title": f"Live Fetch: {args.fetch_url}",
            "original_md": raw_md,
            "cleaned_md": comp["cleaned_markdown"],
            "original_len": comp["original_len"],
            "cleaned_len": comp["cleaned_len"],
            "char_diff": comp["char_diff"],
            "reduction_pct": comp["reduction_pct"],
            "original_lines": comp["original_lines"],
            "cleaned_lines": comp["cleaned_lines"],
        }]

        print(f"\n[{args.fetch_url}]")
        print(f"  Original (Raw HTML2Text): {comp['original_len']:,} chars ({comp['original_lines']} lines)")
        print(f"  Cleaned (Sanitized MD):   {comp['cleaned_len']:,} chars ({comp['cleaned_lines']} lines)")
        print(f"  Reduction:               {comp['reduction_pct']}% (-{comp['char_diff']:,} chars)")

        generate_html_comparison_report(results, output_report)
        print(f"\n[REPORT] Interactive HTML preview written to:\n  {output_report.resolve()}")
        return

    with db_session() as session:
        query = session.query(FetchedPage).filter(
            FetchedPage.html_content.isnot(None),
            FetchedPage.html_content != "",
            (FetchedPage.url.like("http://%") | FetchedPage.url.like("https://%")),
        )

        if args.url:
            pages = query.filter_by(url=args.url).all()
            if not pages:
                print(f"[ERROR] No page found for URL: {args.url}")
                sys.exit(1)
        else:
            pages = query.order_by(FetchedPage.fetched_at.desc()).limit(args.sample).all()

        if not pages:
            print("[INFO] No eligible HTML pages found in database.")
            return

        results = []
        applied_count = 0

        for p in pages:
            comp = compare_markdown_cleaning(p.html_content, p.md_content)
            results.append({
                "url": p.url,
                "title": p.title,
                "original_md": p.md_content,
                "cleaned_md": comp["cleaned_markdown"],
                "original_len": comp["original_len"],
                "cleaned_len": comp["cleaned_len"],
                "char_diff": comp["char_diff"],
                "reduction_pct": comp["reduction_pct"],
                "original_lines": comp["original_lines"],
                "cleaned_lines": comp["cleaned_lines"],
            })

            print(f"\n[{p.url}]")
            print(f"  Title:      {p.title}")
            print(f"  Original:   {comp['original_len']:,} chars ({comp['original_lines']} lines)")
            print(f"  Cleaned:    {comp['cleaned_len']:,} chars ({comp['cleaned_lines']} lines)")
            print(f"  Reduction:  {comp['reduction_pct']}% (-{comp['char_diff']:,} chars)")

            if args.apply:
                if getattr(p, "is_frozen", 0):
                    print("  [SKIP] Page is marked as FROZEN (immutable).")
                    continue

                # Archive previous version into page_versions
                now_str = datetime.now().isoformat()
                version = PageVersion(
                    url=p.url,
                    title=p.title,
                    html_content=p.html_content,
                    md_content=p.md_content,
                    links=p.links,
                    html_content_hash=p.html_content_hash,
                    md_content_hash=p.md_content_hash,
                    fetched_at=p.fetched_at or now_str,
                    description=p.description,
                    keywords=p.keywords,
                    tags=p.tags,
                )
                session.add(version)

                # Overwrite md_content with cleaned version
                p.md_content = comp["cleaned_markdown"]
                p.md_content_hash = hashlib.sha256(comp["cleaned_markdown"].encode("utf-8")).hexdigest()
                applied_count += 1
                print("  [SAVED] Overwrote md_content and archived previous version.")

        if args.apply and applied_count > 0:
            session.commit()
            print(f"\n[SUCCESS] Successfully applied cleaned markdown to {applied_count} page(s).")

        # Generate HTML report
        default_report_path = project_root / ".artifacts" / "feature-html-boilerplate-stripper-and-cleaner" / "html_cleaning_preview.html"
        output_report = args.output_html or default_report_path
        generate_html_comparison_report(results, output_report)
        print(f"\n[REPORT] Interactive HTML preview written to:\n  {output_report.resolve()}")


if __name__ == "__main__":
    main()
