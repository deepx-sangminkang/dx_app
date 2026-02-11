#!/usr/bin/env python3
"""
E2E Performance Report Comparison Tool

Compares two CSV E2E performance reports and generates a comprehensive comparison
including metrics differences, side-by-side values, and regression detection.
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List

# FPS columns to compare (higher is better)
FPS_COLUMNS = [
    "E2E FPS",
    "Read FPS",
    "Preprocess FPS",
    "Inference FPS",
    "Postprocess FPS",
]

# Key columns to identify unique rows
KEY_COLUMNS = ["Model", "Variant"]

def parse_fps_value(value: str) -> Optional[float]:
    """Parse FPS value, handling asterisk markers and empty values."""
    if not value or value.strip() == "":
        return None
    # Remove asterisk marker (indicates bottleneck)
    clean_value = value.replace("*", "").strip()
    try:
        return float(clean_value)
    except ValueError:
        return None

def load_csv(filepath: Path) -> dict:
    """Load CSV file and return dict keyed by (Task, Model, Variant)."""
    data = {}
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = tuple(row[col] for col in KEY_COLUMNS)
            data[key] = row
    return data

def calculate_change(old_val: Optional[float], new_val: Optional[float]) -> tuple:
    """Calculate absolute and percentage change. Returns (diff, pct_change, is_regression)."""
    if old_val is None or new_val is None:
        return None, None, False

    diff = new_val - old_val
    if old_val != 0:
        pct_change = (diff / old_val) * 100
    else:
        pct_change = 100.0 if new_val > 0 else 0.0

    # For FPS, lower is worse (regression)
    is_regression = diff < 0
    return diff, pct_change, is_regression

def format_fps_cell(old_val: Optional[float], new_val: Optional[float], diff: Optional[float], pct: Optional[float], threshold: float = 30.0, higher_is_worse: bool = False) -> str:
    """Format FPS cell as: old / new (diff, %) with ❌ if failed.
    For FPS metrics (higher_is_worse=False): fail when pct < -threshold (decrease).
    For inflight metrics (higher_is_worse=True): fail when pct > +threshold (increase).
    """
    if old_val is None or new_val is None:
        return "-"
    sign = "+" if diff >= 0 else ""
    cell = f"{old_val:.1f}/{new_val:.1f} ({sign}{diff:.1f}, {sign}{pct:.1f}%)"
    if pct is not None:
        if higher_is_worse and pct > threshold:
            return f"❌ {cell}"
        elif not higher_is_worse and pct < -threshold:
            return f"❌ {cell}"
    return cell

def get_status(pct: Optional[float], threshold: float) -> str:
    """Get status based on percentage change (for FPS: decrease beyond threshold is fail)."""
    if pct is None:
        return "N/A"
    if pct < -threshold:
        return "❌ FAIL"
    else:
        return "✅ PASS"

def shorten_variant(model: str, variant: str) -> str:
    """Shorten variant by removing model name prefix."""
    # Remove model name from beginning of variant
    if variant.lower().startswith(model.lower()):
        shortened = variant[len(model):].lstrip("_")
        return shortened if shortened else variant
    return variant

def generate_markdown_report(
    old_file: Path,
    new_file: Path,
    old_data: dict,
    new_data: dict,
    async_keys: List[tuple],
    sync_keys: List[tuple],
    regression_threshold: float,
) -> str:
    """Generate markdown formatted report."""
    lines = []

    # Header
    lines.append("# 📊 E2E Performance Report Comparison")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append(f"- **Baseline (old):** `{old_file.name}`")
    lines.append(f"- **Current (new):** `{new_file.name}`")
    lines.append(f"- **Regression threshold:** {regression_threshold}%")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Track counts
    async_success = 0
    async_warn = 0
    async_fail = 0
    sync_success = 0
    sync_warn = 0
    sync_fail = 0

    # Pre-calculate counts for summary
    for key in async_keys:
        old_row = old_data.get(key, {})
        new_row = new_data.get(key, {})
        old_fps = parse_fps_value(old_row.get("E2E FPS", ""))
        new_fps = parse_fps_value(new_row.get("E2E FPS", ""))
        _, pct, _ = calculate_change(old_fps, new_fps)
        status = get_status(pct, regression_threshold)
        if "FAIL" in status:
            async_fail += 1
        else:
            inflight_fail = False
            old_inflight_avg = parse_fps_value(old_row.get("Infer Inflight Avg", ""))
            new_inflight_avg = parse_fps_value(new_row.get("Infer Inflight Avg", ""))
            _, avg_pct, _ = calculate_change(old_inflight_avg, new_inflight_avg)
            if avg_pct is not None and avg_pct > regression_threshold:
                inflight_fail = True
            old_inflight_max = parse_fps_value(old_row.get("Infer Inflight Max", ""))
            new_inflight_max = parse_fps_value(new_row.get("Infer Inflight Max", ""))
            _, max_pct, _ = calculate_change(old_inflight_max, new_inflight_max)
            if max_pct is not None and max_pct > regression_threshold:
                inflight_fail = True
            if inflight_fail:
                async_warn += 1
            else:
                async_success += 1

    for key in sync_keys:
        old_row = old_data.get(key, {})
        new_row = new_data.get(key, {})
        old_e2e = parse_fps_value(old_row.get("E2E FPS", ""))
        new_e2e = parse_fps_value(new_row.get("E2E FPS", ""))
        _, e2e_pct, _ = calculate_change(old_e2e, new_e2e)
        status = get_status(e2e_pct, regression_threshold)
        if "FAIL" in status:
            sync_fail += 1
        else:
            sub_fail = False
            for col in FPS_COLUMNS[1:]:
                old_val = parse_fps_value(old_row.get(col, ""))
                new_val = parse_fps_value(new_row.get(col, ""))
                _, pct, _ = calculate_change(old_val, new_val)
                if pct is not None and pct < -regression_threshold:
                    sub_fail = True
            if sub_fail:
                sync_warn += 1
            else:
                sync_success += 1

    # Summary
    lines.append("## 📈 Summary")
    lines.append("")
    lines.append("### 🔄 Async")
    lines.append("")
    lines.append(f"| Metric | Count |")
    lines.append("|:-------|------:|")
    lines.append(f"| TOTAL | {len(async_keys)} |")
    lines.append(f"| ✅ PASS | {async_success} |")
    lines.append(f"| ⚠️ WARN | {async_warn} |")
    lines.append(f"| ❌ FAIL | {async_fail} |")
    lines.append("")
    lines.append("### ⚡ Sync")
    lines.append("")
    lines.append(f"| Metric | Count |")
    lines.append("|:-------|------:|")
    lines.append(f"| TOTAL | {len(sync_keys)} |")
    lines.append(f"| ✅ PASS | {sync_success} |")
    lines.append(f"| ⚠️ WARN | {sync_warn} |")
    lines.append(f"| ❌ FAIL | {sync_fail} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 1: Async Comparison
    lines.append("## 🔄 Section 1: Async Comparison")
    lines.append("")
    lines.append("| Model | Variant | Status | E2E FPS | Inflight Avg | Inflight Max |")
    lines.append("|:------|:--------|:-------|:--------------------|:-------------|:-------------|")

    for key in async_keys:
        model, variant = key
        short_variant = shorten_variant(model, variant)
        old_row = old_data.get(key, {})
        new_row = new_data.get(key, {})

        old_fps = parse_fps_value(old_row.get("E2E FPS", ""))
        new_fps = parse_fps_value(new_row.get("E2E FPS", ""))
        diff, pct, is_reg = calculate_change(old_fps, new_fps)

        fps_cell = format_fps_cell(old_fps, new_fps, diff, pct, regression_threshold)
        status = get_status(pct, regression_threshold)

        # Inflight metrics
        old_inflight_avg = parse_fps_value(old_row.get("Infer Inflight Avg", ""))
        new_inflight_avg = parse_fps_value(new_row.get("Infer Inflight Avg", ""))
        inflight_avg_diff, inflight_avg_pct, _ = calculate_change(old_inflight_avg, new_inflight_avg)
        inflight_avg_cell = format_fps_cell(old_inflight_avg, new_inflight_avg, inflight_avg_diff, inflight_avg_pct, regression_threshold, higher_is_worse=True)

        old_inflight_max = parse_fps_value(old_row.get("Infer Inflight Max", ""))
        new_inflight_max = parse_fps_value(new_row.get("Infer Inflight Max", ""))
        inflight_max_diff, inflight_max_pct, _ = calculate_change(old_inflight_max, new_inflight_max)
        inflight_max_cell = format_fps_cell(old_inflight_max, new_inflight_max, inflight_max_diff, inflight_max_pct, regression_threshold, higher_is_worse=True)

        if "FAIL" in status:
            status_md = "❌ **FAIL**"
        else:
            status_md = "✅ PASS"

        # Check for inflight failures
        inflight_fail = False
        if inflight_avg_pct is not None and inflight_avg_pct > regression_threshold:
            inflight_fail = True
        if inflight_max_pct is not None and inflight_max_pct > regression_threshold:
            inflight_fail = True

        if status_md == "✅ PASS" and inflight_fail:
            status_md = "⚠️ WARN"

        lines.append(f"| {model} | {short_variant} | {status_md} | {fps_cell} | {inflight_avg_cell} | {inflight_max_cell} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 2: Sync Comparison
    lines.append("## ⚡ Section 2: Sync Comparison")
    lines.append("")

    # Build header - Status first
    header_cols = ["Model", "Variant", "Status"]
    for col in FPS_COLUMNS:
        col_short = col.replace(" FPS", "")
        header_cols.append(col_short)

    lines.append("| " + " | ".join(header_cols) + " |")
    lines.append("|" + "|".join([":---"] * len(header_cols)) + "|")

    for key in sync_keys:
        model, variant = key
        short_variant = shorten_variant(model, variant)
        old_row = old_data.get(key, {})
        new_row = new_data.get(key, {})

        # Status based on E2E FPS only
        old_e2e = parse_fps_value(old_row.get("E2E FPS", ""))
        new_e2e = parse_fps_value(new_row.get("E2E FPS", ""))
        _, e2e_pct, _ = calculate_change(old_e2e, new_e2e)
        status = get_status(e2e_pct, regression_threshold)

        if "FAIL" in status:
            status_md = "❌ **FAIL**"
        else:
            status_md = "✅ PASS"

        fps_cells = []
        sub_fail = False
        for col in FPS_COLUMNS:
            old_val = parse_fps_value(old_row.get(col, ""))
            new_val = parse_fps_value(new_row.get(col, ""))
            diff, pct, is_reg = calculate_change(old_val, new_val)
            fps_cell = format_fps_cell(old_val, new_val, diff, pct, regression_threshold)
            fps_cells.append(fps_cell)
            if col != "E2E FPS" and pct is not None and pct < -regression_threshold:
                sub_fail = True

        if status_md == "✅ PASS" and sub_fail:
            status_md = "⚠️ WARN"

        row_cells = [model, short_variant, status_md] + fps_cells
        lines.append("| " + " | ".join(row_cells) + " |")

    lines.append("")

    return "\n".join(lines)


def generate_html_report(
    old_file: Path,
    new_file: Path,
    old_data: dict,
    new_data: dict,
    async_keys: List[tuple],
    sync_keys: List[tuple],
    regression_threshold: float,
) -> str:
    """Generate HTML formatted report."""

    # Track counts
    async_success = 0
    async_warn = 0
    async_fail = 0
    sync_success = 0
    sync_warn = 0
    sync_fail = 0

    # Build async rows
    async_rows = []
    for key in async_keys:
        model, variant = key
        short_variant = shorten_variant(model, variant)
        old_row = old_data.get(key, {})
        new_row = new_data.get(key, {})

        old_fps = parse_fps_value(old_row.get("E2E FPS", ""))
        new_fps = parse_fps_value(new_row.get("E2E FPS", ""))
        diff, pct, is_reg = calculate_change(old_fps, new_fps)

        fps_cell = format_fps_cell(old_fps, new_fps, diff, pct, regression_threshold)
        is_fail = pct is not None and pct < -regression_threshold

        # Inflight metrics
        old_inflight_avg = parse_fps_value(old_row.get("Infer Inflight Avg", ""))
        new_inflight_avg = parse_fps_value(new_row.get("Infer Inflight Avg", ""))
        inflight_avg_diff, inflight_avg_pct, _ = calculate_change(old_inflight_avg, new_inflight_avg)
        inflight_avg_cell = format_fps_cell(old_inflight_avg, new_inflight_avg, inflight_avg_diff, inflight_avg_pct, regression_threshold, higher_is_worse=True)

        old_inflight_max = parse_fps_value(old_row.get("Infer Inflight Max", ""))
        new_inflight_max = parse_fps_value(new_row.get("Infer Inflight Max", ""))
        inflight_max_diff, inflight_max_pct, _ = calculate_change(old_inflight_max, new_inflight_max)
        inflight_max_cell = format_fps_cell(old_inflight_max, new_inflight_max, inflight_max_diff, inflight_max_pct, regression_threshold, higher_is_worse=True)

        if is_fail:
            async_fail += 1
            status_html = '<span class="badge fail">FAIL</span>'
            row_class = "fail-row"
        else:
            async_success += 1
            status_html = '<span class="badge pass">PASS</span>'
            row_class = "pass-row"

        # Check for inflight failures
        inflight_fail = False
        if inflight_avg_pct is not None and inflight_avg_pct > regression_threshold:
            inflight_fail = True
        if inflight_max_pct is not None and inflight_max_pct > regression_threshold:
            inflight_fail = True

        if not is_fail and inflight_fail:
            async_success -= 1
            async_warn += 1
            status_html = '<span class="badge warn">WARN</span>'
            row_class = "warn-row"

        async_rows.append(f'<tr class="{row_class}"><td>{model}</td><td>{short_variant}</td><td>{status_html}</td><td>{fps_cell}</td><td>{inflight_avg_cell}</td><td>{inflight_max_cell}</td></tr>')

    # Build sync rows
    sync_rows = []
    for key in sync_keys:
        model, variant = key
        short_variant = shorten_variant(model, variant)
        old_row = old_data.get(key, {})
        new_row = new_data.get(key, {})

        # Status based on E2E FPS only
        old_e2e = parse_fps_value(old_row.get("E2E FPS", ""))
        new_e2e = parse_fps_value(new_row.get("E2E FPS", ""))
        _, e2e_pct, _ = calculate_change(old_e2e, new_e2e)
        is_fail = e2e_pct is not None and e2e_pct < -regression_threshold

        if is_fail:
            sync_fail += 1
            status_html = '<span class="badge fail">FAIL</span>'
            row_class = "fail-row"
        else:
            sync_success += 1
            status_html = '<span class="badge pass">PASS</span>'
            row_class = "pass-row"

        fps_cells = []
        sub_fail = False
        for col in FPS_COLUMNS:
            old_val = parse_fps_value(old_row.get(col, ""))
            new_val = parse_fps_value(new_row.get(col, ""))
            diff, pct, is_reg = calculate_change(old_val, new_val)
            fps_cell = format_fps_cell(old_val, new_val, diff, pct, regression_threshold)
            fps_cells.append(f"<td>{fps_cell}</td>")
            if col != "E2E FPS" and pct is not None and pct < -regression_threshold:
                sub_fail = True

        if not is_fail and sub_fail:
            sync_success -= 1
            sync_warn += 1
            status_html = '<span class="badge warn">WARN</span>'
            row_class = "warn-row"

        cells = f"<td>{model}</td><td>{short_variant}</td><td>{status_html}</td>" + "".join(fps_cells)
        sync_rows.append(f'<tr class="{row_class}">{cells}</tr>')

    # Build sync header columns
    sync_header_cols = "".join(f"<th>{col.replace(' FPS', '')}</th>" for col in FPS_COLUMNS)

    generated_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>E2E Performance Report Comparison</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; color: #333; padding: 24px; }}
  .container {{ max-width: 1400px; margin: 0 auto; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 8px; }}
  h2 {{ font-size: 1.2rem; margin: 24px 0 12px 0; color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 6px; }}
  .meta {{ background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 0.9rem; line-height: 1.8; }}
  .meta strong {{ color: #555; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 24px; font-size: 0.85rem; }}
  th {{ background: #2c3e50; color: #fff; padding: 10px 12px; text-align: left; font-weight: 600; white-space: nowrap; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #eee; white-space: nowrap; }}
  tr:hover {{ background: #f0f4f8; }}
  .pass-row {{ }}
  .fail-row {{ background: #fff5f5; }}
  .fail-row:hover {{ background: #ffe8e8; }}
  .warn-row {{ background: #fffdf5; }}
  .warn-row:hover {{ background: #fff8e1; }}
  .badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.78rem; font-weight: 700; }}
  .badge.pass {{ background: #d4edda; color: #155724; }}
  .badge.warn {{ background: #fff3cd; color: #856404; }}
  .badge.fail {{ background: #f8d7da; color: #721c24; }}
  .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }}
  .summary-card {{ background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .summary-card h3 {{ font-size: 1rem; margin-bottom: 10px; }}
  .summary-card table {{ box-shadow: none; margin-bottom: 0; }}
  .summary-card th {{ background: #34495e; }}
  .count-pass {{ color: #155724; font-weight: 700; }}
  .count-warn {{ color: #856404; font-weight: 700; }}
  .count-fail {{ color: #721c24; font-weight: 700; }}
</style>
</head>
<body>
<div class="container">
  <h1>&#x1F4CA; E2E Performance Report Comparison</h1>
  <div class="meta">
    <strong>Generated:</strong> {generated_time}<br>
    <strong>Baseline (old):</strong> {old_file.name}<br>
    <strong>Current (new):</strong> {new_file.name}<br>
    <strong>Regression threshold:</strong> {regression_threshold}%
  </div>

  <h2>&#x1F4C8; Summary</h2>
  <div class="summary-grid">
    <div class="summary-card">
      <h3>&#x1F504; Async</h3>
      <table>
        <thead><tr><th>Metric</th><th>Count</th></tr></thead>
        <tbody>
          <tr><td>TOTAL</td><td>{len(async_keys)}</td></tr>
          <tr><td>✅ PASS</td><td class="count-pass">{async_success}</td></tr>
          <tr><td>⚠️ WARN</td><td class="count-warn">{async_warn}</td></tr>
          <tr><td>❌ FAIL</td><td class="count-fail">{async_fail}</td></tr>
        </tbody>
      </table>
    </div>
    <div class="summary-card">
      <h3>&#x26A1; Sync</h3>
      <table>
        <thead><tr><th>Metric</th><th>Count</th></tr></thead>
        <tbody>
          <tr><td>TOTAL</td><td>{len(sync_keys)}</td></tr>
          <tr><td>✅ PASS</td><td class="count-pass">{sync_success}</td></tr>
          <tr><td>⚠️ WARN</td><td class="count-warn">{sync_warn}</td></tr>
          <tr><td>❌ FAIL</td><td class="count-fail">{sync_fail}</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <h2>&#x1F504; Section 1: Async Comparison</h2>
  <table>
    <thead><tr><th>Model</th><th>Variant</th><th>Status</th><th>E2E FPS</th><th>Inflight Avg</th><th>Inflight Max</th></tr></thead>
    <tbody>
      {''.join(async_rows)}
    </tbody>
  </table>

  <h2>&#x26A1; Section 2: Sync Comparison</h2>
  <table>
    <thead><tr><th>Model</th><th>Variant</th><th>Status</th>{sync_header_cols}</tr></thead>
    <tbody>
      {''.join(sync_rows)}
    </tbody>
  </table>
</div>
</body>
</html>"""
    return html

def compare_reports(old_file: Path, new_file: Path, regression_threshold: float = 30.0, html_output: bool = False):
    """Compare two performance reports and generate a report file."""

    # Load data
    old_data = load_csv(old_file)
    new_data = load_csv(new_file)

    # Find all unique keys and separate async/sync, sorted by model name alphabetically
    all_keys = set(old_data.keys()) | set(new_data.keys())
    async_keys = sorted([k for k in all_keys if "async" in k[1].lower()], key=lambda x: (x[0].lower(), x[1].lower()))
    sync_keys = sorted([k for k in all_keys if "sync" in k[1].lower() and "async" not in k[1].lower()], key=lambda x: (x[0].lower(), x[1].lower()))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Generate HTML if requested, otherwise default to markdown
    if html_output:
        html_content = generate_html_report(
            old_file, new_file, old_data, new_data,
            async_keys, sync_keys, regression_threshold
        )
        output_file = Path(f"report_{timestamp}.html")
        output_file.write_text(html_content, encoding="utf-8")
        print(f"HTML report saved to: {output_file}")
    else:
        md_content = generate_markdown_report(
            old_file, new_file, old_data, new_data,
            async_keys, sync_keys, regression_threshold
        )
        output_file = Path(f"report_{timestamp}.md")
        output_file.write_text(md_content, encoding="utf-8")
        print(f"Markdown report saved to: {output_file}")

def main():
    parser = argparse.ArgumentParser(
        description="Compare two performance report CSV files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s old_report.csv new_report.csv
  %(prog)s baseline.csv current.csv --threshold 30
  %(prog)s old.csv new.csv --html
        """
    )
    parser.add_argument("old_file", type=Path, help="Baseline/old performance report CSV")
    parser.add_argument("new_file", type=Path, help="Current/new performance report CSV")
    parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=30.0,
        help="Regression threshold percentage (default: 30, applied as -30%%)"
    )
    parser.add_argument(
        "--md",
        action="store_true",
        default=True,
        help="Output report as markdown file (default)"
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="Output report as HTML file instead of markdown"
    )

    args = parser.parse_args()

    # Validate files exist
    if not args.old_file.exists():
        print(f"Error: File not found: {args.old_file}", file=sys.stderr)
        sys.exit(1)
    if not args.new_file.exists():
        print(f"Error: File not found: {args.new_file}", file=sys.stderr)
        sys.exit(1)

    # Run comparison
    compare_reports(args.old_file, args.new_file, args.threshold, args.html)


if __name__ == "__main__":
    main()
