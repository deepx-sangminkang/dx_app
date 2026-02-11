# E2E Performance Report Comparison Tool

Compares two CSV E2E performance reports and generates a comparison report with regression detection.

## Prerequisites

- Python 3.6+
- No external dependencies (uses only standard library)

## Usage

```bash
python compare_reports.py <old_csv> <new_csv> [options]
```

### Arguments

| Argument | Description |
|:---------|:------------|
| `old_csv` | Baseline/old performance report CSV |
| `new_csv` | Current/new performance report CSV |

### Options

| Option | Default | Description |
|:-------|:--------|:------------|
| `--threshold`, `-t` | `30` | Regression threshold percentage (positive number: applied as -30% for FPS decrease, +30% for inflight increase) |
| `--md` | *(default)* | Output as markdown (`report_YYYYMMDD_HHMMSS.md`) |
| `--html` | | Output as HTML (`report_YYYYMMDD_HHMMSS.html`) |

### Examples

```bash
# Basic comparison (outputs markdown by default)
python compare_reports.py old_report.csv new_report.csv

# Custom threshold (20% - will check for -20% FPS decrease, +20% inflight increase)
python compare_reports.py old.csv new.csv --threshold 20

# HTML output
python compare_reports.py old.csv new.csv --html

# Strict threshold with HTML
python compare_reports.py old.csv new.csv --threshold 5 --html
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
old/new (+diff, +pct%)
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
