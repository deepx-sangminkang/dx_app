#!/usr/bin/env python3
"""
E2E Performance Report Comparison Tool

Compares two CSV E2E performance reports and generates a comprehensive comparison
including metrics differences, side-by-side values, and regression detection.
"""

import argparse
import csv
import json
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

def calculate_change(baseline_val: Optional[float], current_val: Optional[float]) -> tuple:
    """Calculate absolute and percentage change. Returns (diff, pct_change, is_regression)."""
    if baseline_val is None or current_val is None:
        return None, None, False

    diff = current_val - baseline_val
    if baseline_val != 0:
        pct_change = (diff / baseline_val) * 100
    else:
        pct_change = 100.0 if current_val > 0 else 0.0

    # For FPS, lower is worse (regression)
    is_regression = diff < 0
    return diff, pct_change, is_regression

def format_fps_cell(baseline_val: Optional[float], current_val: Optional[float], diff: Optional[float], pct: Optional[float], threshold: float = 30.0, higher_is_worse: bool = False) -> str:
    """Format FPS cell as: old / new (diff, %) with ❌ if failed.
    For FPS metrics (higher_is_worse=False): fail when pct < -threshold (decrease).
    For inflight metrics (higher_is_worse=True): fail when pct > +threshold (increase).
    """
    if baseline_val is None or current_val is None:
        return "-"
    sign = "+" if diff >= 0 else ""
    cell = f"{baseline_val:.1f}/{current_val:.1f} ({sign}{diff:.1f}, {sign}{pct:.1f}%)"
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

# Sync FPS column name → threshold.json key mapping
_SYNC_COL_TO_KEY = {
    "E2E FPS": "e2e_fps",
    "Read FPS": "read_fps",
    "Preprocess FPS": "preprocess_fps",
    "Inference FPS": "inference_fps",
    "Postprocess FPS": "postprocess_fps",
}

def load_threshold_json(path: Path) -> dict:
    """Load per-model/variant thresholds from a JSON file."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    th_map: dict = {"async": {}, "sync": {}}
    for entry in data.get("async", []):
        key = (entry["model"], entry.get("variant", ""))
        th_map["async"][key] = entry
    for entry in data.get("sync", []):
        key = (entry["model"], entry.get("variant", ""))
        th_map["sync"][key] = entry
    return th_map

def get_async_thresholds(th_map: dict, model: str, short_variant: str, default: float) -> dict:
    """Return per-row async thresholds, falling back to default."""
    entry = (th_map.get("async", {}).get((model, short_variant))
             or th_map.get("async", {}).get((model, "")))
    if entry:
        return {
            "e2e_fps": entry.get("e2e_fps", default),
            "inflight_avg": entry.get("inflight_avg", default),
            "inflight_max": entry.get("inflight_max", default),
        }
    return {"e2e_fps": default, "inflight_avg": default, "inflight_max": default}

def get_sync_thresholds(th_map: dict, model: str, short_variant: str, default: float) -> dict:
    """Return per-row sync thresholds keyed by FPS_COLUMNS, falling back to default."""
    entry = (th_map.get("sync", {}).get((model, short_variant))
             or th_map.get("sync", {}).get((model, "")))
    return {col: (entry.get(key, default) if entry else default)
            for col, key in _SYNC_COL_TO_KEY.items()}

def generate_json_report(
    baseline_file: Path,
    current_file: Path,
    baseline_data: dict,
    current_data: dict,
    async_keys: List[tuple],
    sync_keys: List[tuple],
    threshold: float,
    th_map: dict = None,
) -> str:
    """Generate JSON formatted report."""

    def build_row_async(key):
        model, variant = key
        short_variant = shorten_variant(model, variant)
        baseline_row = baseline_data.get(key, {})
        current_row = current_data.get(key, {})
        row_th = get_async_thresholds(th_map or {}, model, short_variant, threshold)

        baseline_fps = parse_fps_value(baseline_row.get("E2E FPS", ""))
        current_fps = parse_fps_value(current_row.get("E2E FPS", ""))
        diff, pct, _ = calculate_change(baseline_fps, current_fps)

        baseline_inflight_avg = parse_fps_value(baseline_row.get("Infer Inflight Avg", ""))
        current_inflight_avg = parse_fps_value(current_row.get("Infer Inflight Avg", ""))
        _, avg_pct, _ = calculate_change(baseline_inflight_avg, current_inflight_avg)

        baseline_inflight_max = parse_fps_value(baseline_row.get("Infer Inflight Max", ""))
        current_inflight_max = parse_fps_value(current_row.get("Infer Inflight Max", ""))
        _, max_pct, _ = calculate_change(baseline_inflight_max, current_inflight_max)

        fps_fail = pct is not None and pct < -row_th["e2e_fps"]
        inflight_fail = (avg_pct is not None and avg_pct > row_th["inflight_avg"]) or (max_pct is not None and max_pct > row_th["inflight_max"])
        if fps_fail:
            status = "FAIL"
        elif inflight_fail:
            status = "WARN"
        else:
            status = "PASS"

        return {
            "model": model,
            "variant": short_variant,
            "status": status,
            "e2e_fps": {"baseline": baseline_fps, "current": current_fps, "diff": diff, "pct": round(pct, 2) if pct is not None else None},
            "inflight_avg": {"baseline": baseline_inflight_avg, "current": current_inflight_avg, "pct": round(avg_pct, 2) if avg_pct is not None else None},
            "inflight_max": {"baseline": baseline_inflight_max, "current": current_inflight_max, "pct": round(max_pct, 2) if max_pct is not None else None},
            "threshold": row_th,
        }

    def build_row_sync(key):
        model, variant = key
        short_variant = shorten_variant(model, variant)
        baseline_row = baseline_data.get(key, {})
        current_row = current_data.get(key, {})
        row_th = get_sync_thresholds(th_map or {}, model, short_variant, threshold)

        baseline_e2e = parse_fps_value(baseline_row.get("E2E FPS", ""))
        current_e2e = parse_fps_value(current_row.get("E2E FPS", ""))
        _, e2e_pct, _ = calculate_change(baseline_e2e, current_e2e)

        e2e_fail = e2e_pct is not None and e2e_pct < -row_th["E2E FPS"]
        sub_fail = False
        fps_metrics = {}
        for col in FPS_COLUMNS:
            baseline_val = parse_fps_value(baseline_row.get(col, ""))
            current_val = parse_fps_value(current_row.get(col, ""))
            diff, pct, _ = calculate_change(baseline_val, current_val)
            fps_metrics[col] = {"baseline": baseline_val, "current": current_val, "diff": diff, "pct": round(pct, 2) if pct is not None else None}
            if col != "E2E FPS" and pct is not None and pct < -row_th[col]:
                sub_fail = True

        if e2e_fail:
            status = "FAIL"
        elif sub_fail:
            status = "WARN"
        else:
            status = "PASS"

        return {"model": model, "variant": short_variant, "status": status, "fps": fps_metrics, "threshold": row_th}

    async_rows = [build_row_async(k) for k in async_keys]
    sync_rows = [build_row_sync(k) for k in sync_keys]

    def count_status(rows, s):
        return sum(1 for r in rows if r["status"] == s)

    report = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "baseline": baseline_file.name,
        "current": current_file.name,
        "threshold": threshold,
        "summary": {
            "async": {
                "total": len(async_rows),
                "pass": count_status(async_rows, "PASS"),
                "warn": count_status(async_rows, "WARN"),
                "fail": count_status(async_rows, "FAIL"),
            },
            "sync": {
                "total": len(sync_rows),
                "pass": count_status(sync_rows, "PASS"),
                "warn": count_status(sync_rows, "WARN"),
                "fail": count_status(sync_rows, "FAIL"),
            },
        },
        "async": async_rows,
        "sync": sync_rows,
    }
    return json.dumps(report, indent=2)


def generate_markdown_report(
    baseline_file: Path,
    current_file: Path,
    baseline_data: dict,
    current_data: dict,
    async_keys: List[tuple],
    sync_keys: List[tuple],
    threshold: float,
    th_map: dict = None,
) -> str:
    """Generate markdown formatted report."""
    lines = []

    # Header
    lines.append("# 📊 E2E Performance Report Comparison")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append(f"- **Baseline:** `{baseline_file.name}`")
    lines.append(f"- **Current:** `{current_file.name}`")
    lines.append(f"- **Threshold:** {threshold}%")
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
        _ath = get_async_thresholds(th_map or {}, key[0], shorten_variant(key[0], key[1]), threshold)
        baseline_row = baseline_data.get(key, {})
        current_row = current_data.get(key, {})
        baseline_fps = parse_fps_value(baseline_row.get("E2E FPS", ""))
        current_fps = parse_fps_value(current_row.get("E2E FPS", ""))
        _, pct, _ = calculate_change(baseline_fps, current_fps)
        status = get_status(pct, _ath["e2e_fps"])
        if "FAIL" in status:
            async_fail += 1
        else:
            inflight_fail = False
            baseline_inflight_avg = parse_fps_value(baseline_row.get("Infer Inflight Avg", ""))
            current_inflight_avg = parse_fps_value(current_row.get("Infer Inflight Avg", ""))
            _, avg_pct, _ = calculate_change(baseline_inflight_avg, current_inflight_avg)
            if avg_pct is not None and avg_pct > _ath["inflight_avg"]:
                inflight_fail = True
            baseline_inflight_max = parse_fps_value(baseline_row.get("Infer Inflight Max", ""))
            current_inflight_max = parse_fps_value(current_row.get("Infer Inflight Max", ""))
            _, max_pct, _ = calculate_change(baseline_inflight_max, current_inflight_max)
            if max_pct is not None and max_pct > _ath["inflight_max"]:
                inflight_fail = True
            if inflight_fail:
                async_warn += 1
            else:
                async_success += 1

    for key in sync_keys:
        _sth = get_sync_thresholds(th_map or {}, key[0], shorten_variant(key[0], key[1]), threshold)
        baseline_row = baseline_data.get(key, {})
        current_row = current_data.get(key, {})
        baseline_e2e = parse_fps_value(baseline_row.get("E2E FPS", ""))
        current_e2e = parse_fps_value(current_row.get("E2E FPS", ""))
        _, e2e_pct, _ = calculate_change(baseline_e2e, current_e2e)
        status = get_status(e2e_pct, _sth["E2E FPS"])
        if "FAIL" in status:
            sync_fail += 1
        else:
            sub_fail = False
            for col in FPS_COLUMNS[1:]:
                baseline_val = parse_fps_value(baseline_row.get(col, ""))
                current_val = parse_fps_value(current_row.get(col, ""))
                _, pct, _ = calculate_change(baseline_val, current_val)
                if pct is not None and pct < -_sth[col]:
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
        baseline_row = baseline_data.get(key, {})
        current_row = current_data.get(key, {})
        row_th = get_async_thresholds(th_map or {}, model, short_variant, threshold)

        baseline_fps = parse_fps_value(baseline_row.get("E2E FPS", ""))
        current_fps = parse_fps_value(current_row.get("E2E FPS", ""))
        diff, pct, is_reg = calculate_change(baseline_fps, current_fps)

        fps_cell = format_fps_cell(baseline_fps, current_fps, diff, pct, row_th["e2e_fps"])
        status = get_status(pct, row_th["e2e_fps"])

        # Inflight metrics
        baseline_inflight_avg = parse_fps_value(baseline_row.get("Infer Inflight Avg", ""))
        current_inflight_avg = parse_fps_value(current_row.get("Infer Inflight Avg", ""))
        inflight_avg_diff, inflight_avg_pct, _ = calculate_change(baseline_inflight_avg, current_inflight_avg)
        inflight_avg_cell = format_fps_cell(baseline_inflight_avg, current_inflight_avg, inflight_avg_diff, inflight_avg_pct, row_th["inflight_avg"], higher_is_worse=True)

        baseline_inflight_max = parse_fps_value(baseline_row.get("Infer Inflight Max", ""))
        current_inflight_max = parse_fps_value(current_row.get("Infer Inflight Max", ""))
        inflight_max_diff, inflight_max_pct, _ = calculate_change(baseline_inflight_max, current_inflight_max)
        inflight_max_cell = format_fps_cell(baseline_inflight_max, current_inflight_max, inflight_max_diff, inflight_max_pct, row_th["inflight_max"], higher_is_worse=True)

        if "FAIL" in status:
            status_md = "❌ **FAIL**"
        else:
            status_md = "✅ PASS"

        # Check for inflight failures
        inflight_fail = False
        if inflight_avg_pct is not None and inflight_avg_pct > row_th["inflight_avg"]:
            inflight_fail = True
        if inflight_max_pct is not None and inflight_max_pct > row_th["inflight_max"]:
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
        baseline_row = baseline_data.get(key, {})
        current_row = current_data.get(key, {})
        row_th = get_sync_thresholds(th_map or {}, model, short_variant, threshold)

        # Status based on E2E FPS only
        baseline_e2e = parse_fps_value(baseline_row.get("E2E FPS", ""))
        current_e2e = parse_fps_value(current_row.get("E2E FPS", ""))
        _, e2e_pct, _ = calculate_change(baseline_e2e, current_e2e)
        status = get_status(e2e_pct, row_th["E2E FPS"])

        if "FAIL" in status:
            status_md = "❌ **FAIL**"
        else:
            status_md = "✅ PASS"

        fps_cells = []
        sub_fail = False
        for col in FPS_COLUMNS:
            baseline_val = parse_fps_value(baseline_row.get(col, ""))
            current_val = parse_fps_value(current_row.get(col, ""))
            diff, pct, is_reg = calculate_change(baseline_val, current_val)
            fps_cell = format_fps_cell(baseline_val, current_val, diff, pct, row_th[col])
            fps_cells.append(fps_cell)
            if col != "E2E FPS" and pct is not None and pct < -row_th[col]:
                sub_fail = True

        if status_md == "✅ PASS" and sub_fail:
            status_md = "⚠️ WARN"

        row_cells = [model, short_variant, status_md] + fps_cells
        lines.append("| " + " | ".join(row_cells) + " |")

    lines.append("")

    return "\n".join(lines)


def generate_html_report(
    baseline_file: Path,
    current_file: Path,
    baseline_data: dict,
    current_data: dict,
    async_keys: List[tuple],
    sync_keys: List[tuple],
    threshold: float,
    th_map: dict = None,
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
        baseline_row = baseline_data.get(key, {})
        current_row = current_data.get(key, {})
        row_th = get_async_thresholds(th_map or {}, model, short_variant, threshold)

        baseline_fps = parse_fps_value(baseline_row.get("E2E FPS", ""))
        current_fps = parse_fps_value(current_row.get("E2E FPS", ""))
        diff, pct, is_reg = calculate_change(baseline_fps, current_fps)

        fps_cell = format_fps_cell(baseline_fps, current_fps, diff, pct, row_th["e2e_fps"])
        is_fail = pct is not None and pct < -row_th["e2e_fps"]

        # Inflight metrics
        baseline_inflight_avg = parse_fps_value(baseline_row.get("Infer Inflight Avg", ""))
        current_inflight_avg = parse_fps_value(current_row.get("Infer Inflight Avg", ""))
        inflight_avg_diff, inflight_avg_pct, _ = calculate_change(baseline_inflight_avg, current_inflight_avg)
        inflight_avg_cell = format_fps_cell(baseline_inflight_avg, current_inflight_avg, inflight_avg_diff, inflight_avg_pct, row_th["inflight_avg"], higher_is_worse=True)

        baseline_inflight_max = parse_fps_value(baseline_row.get("Infer Inflight Max", ""))
        current_inflight_max = parse_fps_value(current_row.get("Infer Inflight Max", ""))
        inflight_max_diff, inflight_max_pct, _ = calculate_change(baseline_inflight_max, current_inflight_max)
        inflight_max_cell = format_fps_cell(baseline_inflight_max, current_inflight_max, inflight_max_diff, inflight_max_pct, row_th["inflight_max"], higher_is_worse=True)

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
        if inflight_avg_pct is not None and inflight_avg_pct > row_th["inflight_avg"]:
            inflight_fail = True
        if inflight_max_pct is not None and inflight_max_pct > row_th["inflight_max"]:
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
        baseline_row = baseline_data.get(key, {})
        current_row = current_data.get(key, {})
        row_th = get_sync_thresholds(th_map or {}, model, short_variant, threshold)

        # Status based on E2E FPS only
        baseline_e2e = parse_fps_value(baseline_row.get("E2E FPS", ""))
        current_e2e = parse_fps_value(current_row.get("E2E FPS", ""))
        _, e2e_pct, _ = calculate_change(baseline_e2e, current_e2e)
        is_fail = e2e_pct is not None and e2e_pct < -row_th["E2E FPS"]

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
            baseline_val = parse_fps_value(baseline_row.get(col, ""))
            current_val = parse_fps_value(current_row.get(col, ""))
            diff, pct, is_reg = calculate_change(baseline_val, current_val)
            fps_cell = format_fps_cell(baseline_val, current_val, diff, pct, row_th[col])
            fps_cells.append(f"<td>{fps_cell}</td>")
            if col != "E2E FPS" and pct is not None and pct < -row_th[col]:
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
    <strong>Baseline:</strong> {baseline_file.name}<br>
    <strong>Current:</strong> {current_file.name}<br>
    <strong>Threshold:</strong> {threshold}%
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

def compare_reports(
    baseline_file: Path,
    current_file: Path,
    threshold: float = 30.0,
    output_format: str = "json",
    threshold_json: Optional[Path] = None,
):
    """Compare two performance reports and generate a report file."""

    # Load per-model/variant threshold overrides if provided
    th_map = load_threshold_json(threshold_json) if threshold_json else {}

    # Load data
    baseline_data = load_csv(baseline_file)
    current_data = load_csv(current_file)

    # Find all unique keys and separate async/sync, sorted by model name alphabetically
    all_keys = set(baseline_data.keys()) | set(current_data.keys())
    async_keys = sorted([k for k in all_keys if "async" in k[1].lower()], key=lambda x: (x[0].lower(), x[1].lower()))
    sync_keys = sorted([k for k in all_keys if "sync" in k[1].lower() and "async" not in k[1].lower()], key=lambda x: (x[0].lower(), x[1].lower()))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if output_format == "html":
        content = generate_html_report(
            baseline_file, current_file, baseline_data, current_data,
            async_keys, sync_keys, threshold, th_map
        )
        output_file = Path(f"report_{timestamp}.html")
        output_file.write_text(content, encoding="utf-8")
        print(f"HTML report saved to: {output_file}")
    elif output_format == "md":
        content = generate_markdown_report(
            baseline_file, current_file, baseline_data, current_data,
            async_keys, sync_keys, threshold, th_map
        )
        output_file = Path(f"report_{timestamp}.md")
        output_file.write_text(content, encoding="utf-8")
        print(f"Markdown report saved to: {output_file}")
    else:  # json (default)
        content = generate_json_report(
            baseline_file, current_file, baseline_data, current_data,
            async_keys, sync_keys, threshold, th_map
        )
        output_file = Path(f"report_{timestamp}.json")
        output_file.write_text(content, encoding="utf-8")
        print(f"JSON report saved to: {output_file}")

def main():
    parser = argparse.ArgumentParser(
        description="Compare two performance report CSV files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s baseline.csv current.csv
  %(prog)s baseline.csv current.csv --threshold 30
  %(prog)s baseline.csv current.csv --json
  %(prog)s baseline.csv current.csv --md
  %(prog)s baseline.csv current.csv --html
        """
    )
    parser.add_argument("baseline_file", type=Path, help="Baseline performance report CSV")
    parser.add_argument("current_file", type=Path, help="Current performance report CSV")
    parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=30.0,
        help="Threshold percentage (default: 30, applied as -30%%)"
    )
    parser.add_argument(
        "--threshold-json", "-tj",
        type=Path,
        default=None,
        metavar="FILE",
        help="JSON file with per-model/variant threshold overrides (e.g. threshold.json)"
    )
    format_group = parser.add_mutually_exclusive_group()
    format_group.add_argument(
        "--json",
        dest="format",
        action="store_const",
        const="json",
        help="Output report as JSON file (default)"
    )
    format_group.add_argument(
        "--md",
        dest="format",
        action="store_const",
        const="md",
        help="Output report as Markdown file"
    )
    format_group.add_argument(
        "--html",
        dest="format",
        action="store_const",
        const="html",
        help="Output report as HTML file"
    )
    parser.set_defaults(format="json")

    args = parser.parse_args()

    # Validate files exist
    if not args.baseline_file.exists():
        print(f"Error: File not found: {args.baseline_file}", file=sys.stderr)
        sys.exit(1)
    if not args.current_file.exists():
        print(f"Error: File not found: {args.current_file}", file=sys.stderr)
        sys.exit(1)
    if args.threshold_json and not args.threshold_json.exists():
        print(f"Error: File not found: {args.threshold_json}", file=sys.stderr)
        sys.exit(1)

    # Run comparison
    compare_reports(args.baseline_file, args.current_file, args.threshold, args.format, args.threshold_json)


if __name__ == "__main__":
    main()
