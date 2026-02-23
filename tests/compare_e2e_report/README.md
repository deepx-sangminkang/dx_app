# E2E Performance Report Comparison Tool

Compares two CSV E2E performance reports and generates a comparison report with regression detection.

## Prerequisites

- Python 3.6+
- No external dependencies (uses only standard library)

## Usage

```bash
python compare_reports.py <baseline_csv> <current_csv> [options]
```

### Arguments

| Argument | Description |
|:---------|:------------|
| `baseline_file` | Baseline performance report CSV |
| `current_file` | Current performance report CSV |

### Options

| Option | Default | Description |
|:-------|:--------|:------------|
| `--threshold`, `-t` | `30` | Global regression threshold percentage (applied as -30% for FPS decrease, +30% for inflight increase) |
| `--threshold-json FILE`, `-tj FILE` | | JSON file with per-model/variant threshold overrides (e.g. `threshold.json`) |
| `--json` | *(default)* | Output as JSON (`report_YYYYMMDD_HHMMSS.json`) |
| `--md` | | Output as Markdown (`report_YYYYMMDD_HHMMSS.md`) |
| `--html` | | Output as HTML (`report_YYYYMMDD_HHMMSS.html`) |

### Examples

```bash
# Basic comparison (outputs JSON by default)
python compare_reports.py baseline.csv current.csv

# Custom global threshold (20%)
python compare_reports.py baseline.csv current.csv --threshold 20

# Per-model/variant threshold overrides
python compare_reports.py baseline.csv current.csv -tj threshold.json

# Combined: global fallback + per-model overrides
python compare_reports.py baseline.csv current.csv -t 20 -tj threshold.json

# Markdown output
python compare_reports.py baseline.csv current.csv --md

# HTML output with strict threshold
python compare_reports.py baseline.csv current.csv --threshold 5 --html
```

## Threshold JSON Format

The threshold JSON file allows configuring per-model (and optionally per-variant) thresholds.
Entries without a `variant` field match all variants of that model. A more specific
`(model, variant)` entry takes precedence. Entries fall back to `--threshold` if not found.

### Async section

```json
{
  "async": [
    {
      "model": "yolov8",
      "variant": "async",
      "e2e_fps": 10.0,
      "inflight_avg": 30.0,
      "inflight_max": 30.0
    },
    {
      "model": "deeplabv3",
      "e2e_fps": 10.0,
      "inflight_avg": 30.0,
      "inflight_max": 30.0
    }
  ]
}
```

### Sync section

```json
{
  "sync": [
    {
      "model": "yolov8",
      "variant": "sync",
      "e2e_fps": 10.0,
      "read_fps": 30.0,
      "preprocess_fps": 30.0,
      "inference_fps": 30.0,
      "postprocess_fps": 30.0
    }
  ]
}
```

## Report Sections

### Summary

Aggregated pass/warn/fail counts for both async and sync sections. Displayed first for quick overview.

**Status Definitions:**
- **PASS**: Main metric (E2E FPS) passes threshold, all sub-metrics pass
- **WARN**: Main metric passes, but sub-metrics exceed threshold (marked with ❌)
- **FAIL**: Main metric (E2E FPS) exceeds threshold

### Section 1: Async Comparison

Compares async variants. **Status is based on E2E FPS only.**

| Metric | Threshold Condition | Affects Status |
|:-------|:-------------------|:---------------|
| **E2E FPS** | Decrease > threshold (e.g. -30%) | ✅ Yes (FAIL if exceeded) |
| **Inflight Avg** | Increase > threshold (e.g. +30%) | ⚠️ WARN only (if E2E passes) |
| **Inflight Max** | Increase > threshold (e.g. +30%) | ⚠️ WARN only (if E2E passes) |

- Row is **FAIL** if E2E FPS decreases beyond threshold
- Row is **WARN** if E2E passes but Inflight Avg or Max increases beyond threshold
- Row is **PASS** if E2E passes and inflights pass

### Section 2: Sync Comparison

Compares sync variants across all FPS metrics. **Status is based on E2E FPS only.**

| Metric | Threshold Condition | Affects Status |
|:-------|:-------------------|:---------------|
| **E2E FPS** | Decrease > threshold (e.g. -30%) | ✅ Yes (FAIL if exceeded) |
| **Read FPS** | Decrease > threshold (e.g. -30%) | ⚠️ WARN only (if E2E passes) |
| **Preprocess FPS** | Decrease > threshold (e.g. -30%) | ⚠️ WARN only (if E2E passes) |
| **Inference FPS** | Decrease > threshold (e.g. -30%) | ⚠️ WARN only (if E2E passes) |
| **Postprocess FPS** | Decrease > threshold (e.g. -30%) | ⚠️ WARN only (if E2E passes) |

- Row is **FAIL** if E2E FPS decreases beyond threshold
- Row is **WARN** if E2E passes but any other FPS metric decreases beyond threshold
- Row is **PASS** if E2E passes and all other metrics pass

## Cell Format

Each metric cell is displayed as:

```
baseline/current (+diff, +pct%)
```

- Cells exceeding the threshold are prefixed with ❌
- For FPS metrics: ❌ appears when decrease exceeds threshold (e.g., -30%)
- For inflight metrics: ❌ appears when increase exceeds threshold (e.g., +30%)
- ❌ on sub-metrics (non-E2E) results in **WARN** status if E2E passes

## CSV Input Format

The input CSV files must contain the following columns:

| Column | Required |
|:-------|:---------|
| `Model` | Yes |
| `Variant` | Yes |
| `E2E FPS` | Yes |
| `Read FPS` | Yes |
| `Preprocess FPS` | Yes |
| `Inference FPS` | Yes |
| `Postprocess FPS` | Yes |
| `Infer Inflight Avg` | For async |
| `Infer Inflight Max` | For async |
