#!/usr/bin/env python3
"""
dx_app Aging Test Script

Runs yolo_multi workload with npu_usage monitoring for 48 hours.
Generates HTML report on completion or error.
"""

import subprocess
import sys
import os
import time
import signal
import threading
import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List

# Configuration
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # ~/workspace/dx_app2

TEST_DURATION_SECONDS = 12 * 3600  # 12 hours
RUN_MULTI_DEMO_SCRIPT = PROJECT_ROOT / "run_multi_demo.sh"
NPU_USAGE_PATH = PROJECT_ROOT / "internal" / "npu_usage" / "build" / "npu_usage"
REPORT_DIR = PROJECT_ROOT / "internal" / "npu_usage" / "reports"


@dataclass
class TestResult:
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: float = 0
    status: str = "RUNNING"
    yolo_exit_code: Optional[int] = None
    npu_usage_exit_code: Optional[int] = None
    error_message: str = ""
    yolo_output: str = ""
    npu_usage_output: str = ""
    events: List[str] = field(default_factory=list)

    def add_event(self, msg: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.events.append(f"[{timestamp}] {msg}")
        print(f"[{timestamp}] {msg}")


class AgingTest:
    def __init__(self, no_display: bool = False):
        self.result = TestResult(start_time=datetime.now())
        self.yolo_process: Optional[subprocess.Popen] = None
        self.npu_usage_process: Optional[subprocess.Popen] = None
        self.stop_event = threading.Event()
        self.yolo_output_lines: List[str] = []
        self.npu_output_lines: List[str] = []
        self.no_display = no_display

    def signal_handler(self, signum, frame):
        self.result.add_event(f"Received signal {signum}, stopping test...")
        self.stop_event.set()

    def read_output(self, process: subprocess.Popen, output_list: List[str], name: str):
        """Read process output in a thread"""
        try:
            for line in iter(process.stdout.readline, ''):
                if not line:
                    break
                line = line.strip()
                output_list.append(line)
                # Keep only last 1000 lines
                if len(output_list) > 1000:
                    output_list.pop(0)
        except Exception as e:
            self.result.add_event(f"{name} output reader error: {e}")

    def start_yolo_multi(self) -> bool:
        """Start run_multi_demo.sh script"""
        if not RUN_MULTI_DEMO_SCRIPT.exists():
            self.result.add_event(f"ERROR: run_multi_demo.sh not found at {RUN_MULTI_DEMO_SCRIPT}")
            return False

        try:
            cmd = [str(RUN_MULTI_DEMO_SCRIPT)]
            if self.no_display:
                cmd.append("--no-display")

            self.result.add_event(f"Starting: {' '.join(cmd)}")
            self.result.add_event(f"Working directory: {PROJECT_ROOT}")
            self.yolo_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(PROJECT_ROOT),
                bufsize=1
            )

            # Start output reader thread
            reader = threading.Thread(
                target=self.read_output,
                args=(self.yolo_process, self.yolo_output_lines, "run_multi_demo"),
                daemon=True
            )
            reader.start()

            self.result.add_event(f"run_multi_demo.sh started (PID: {self.yolo_process.pid})")
            return True

        except Exception as e:
            self.result.add_event(f"ERROR starting run_multi_demo.sh: {e}")
            return False

    def start_npu_usage(self) -> bool:
        """Start npu_usage monitor process"""
        if not NPU_USAGE_PATH.exists():
            self.result.add_event(f"ERROR: npu_usage not found at {NPU_USAGE_PATH}")
            return False

        try:
            self.result.add_event(f"Starting npu_usage monitor: {NPU_USAGE_PATH} -c")
            self.npu_usage_process = subprocess.Popen(
                [str(NPU_USAGE_PATH), "-c"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(PROJECT_ROOT),
                bufsize=1
            )

            # Start output reader thread
            reader = threading.Thread(
                target=self.read_output,
                args=(self.npu_usage_process, self.npu_output_lines, "npu_usage"),
                daemon=True
            )
            reader.start()

            self.result.add_event(f"npu_usage started (PID: {self.npu_usage_process.pid})")
            return True

        except Exception as e:
            self.result.add_event(f"ERROR starting npu_usage: {e}")
            return False

    def stop_processes(self):
        """Stop all running processes"""
        # Kill yolo_multi process directly
        if self.yolo_process and self.yolo_process.poll() is None:
            self.result.add_event("Killing yolo_multi process...")
            try:
                subprocess.run(["pkill", "-f", "yolo_multi"], timeout=2, capture_output=True)
                time.sleep(1)
            except Exception as e:
                self.result.add_event(f"pkill failed: {e}")

        for name, proc in [("yolo_multi", self.yolo_process), ("npu_usage", self.npu_usage_process)]:
            if proc and proc.poll() is None:
                self.result.add_event(f"Stopping {name} (PID: {proc.pid})...")
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                self.result.add_event(f"{name} stopped")

    def check_processes(self) -> tuple[bool, str]:
        """Check if processes are still running. Returns (ok, error_msg)"""
        # Check yolo_multi
        if self.yolo_process:
            ret = self.yolo_process.poll()
            if ret is not None:
                self.result.yolo_exit_code = ret
                return False, f"yolo_multi exited with code {ret}"

        # Check for bbox error in yolo output
        for line in self.yolo_output_lines[-10:]:  # Check last 10 lines
            if "[BBOX_ERROR]" in line:
                return False, f"yolo_multi: Abnormal bbox count detected - {line}"

        # Check npu_usage
        if self.npu_usage_process:
            ret = self.npu_usage_process.poll()
            if ret is not None:
                self.result.npu_usage_exit_code = ret
                if ret == 2:
                    return False, "npu_usage: Utilization was 0% for 10+ seconds"
                elif ret == 3:
                    return False, "npu_usage: Temperature >= 90C for 10+ seconds"
                elif ret != 0:
                    return False, f"npu_usage exited with code {ret}"

        return True, ""

    def run(self) -> int:
        """Run the aging test"""
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        self.result.add_event("=" * 50)
        self.result.add_event("dx_app Aging Test Started")
        self.result.add_event(f"Duration: {TEST_DURATION_SECONDS} seconds")
        self.result.add_event("=" * 50)

        # Start processes
        if not self.start_yolo_multi():
            self.result.status = "FAILED"
            self.result.error_message = "Failed to start yolo_multi"
            self.generate_report()
            return 1

        # Wait a bit for yolo to initialize
        time.sleep(2)

        if not self.start_npu_usage():
            self.result.status = "FAILED"
            self.result.error_message = "Failed to start npu_usage"
            self.stop_processes()
            self.generate_report()
            return 1

        # Calculate end time
        end_time = self.result.start_time + timedelta(seconds=TEST_DURATION_SECONDS)
        self.result.add_event(f"Test will end at: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # Main monitoring loop
        check_interval = 1  # seconds
        status_interval = 300  # Print status every 5 minutes
        last_status_time = time.time()

        try:
            while not self.stop_event.is_set():
                # Check if test duration exceeded
                now = datetime.now()
                if now >= end_time:
                    self.result.add_event("Test duration completed successfully!")
                    self.result.status = "PASSED"
                    break

                # Check processes
                ok, error_msg = self.check_processes()
                if not ok:
                    self.result.add_event(f"ERROR: {error_msg}")
                    self.result.status = "FAILED"
                    self.result.error_message = error_msg
                    break

                # Print periodic status
                current_time = time.time()
                if current_time - last_status_time >= status_interval:
                    elapsed = now - self.result.start_time
                    remaining = end_time - now
                    self.result.add_event(
                        f"Status: Running | Elapsed: {elapsed} | Remaining: {remaining}"
                    )
                    last_status_time = current_time

                time.sleep(check_interval)

        except Exception as e:
            self.result.add_event(f"Unexpected error: {e}")
            self.result.status = "FAILED"
            self.result.error_message = str(e)

        finally:
            # Cleanup
            self.result.end_time = datetime.now()
            self.result.duration_seconds = (self.result.end_time - self.result.start_time).total_seconds()

            # Capture final outputs
            self.result.yolo_output = "\n".join(self.yolo_output_lines[-100:])
            self.result.npu_usage_output = "\n".join(self.npu_output_lines[-100:])

            self.stop_processes()
            self.result.add_event(f"Test finished with status: {self.result.status}")
            self.generate_report()

        return 0 if self.result.status == "PASSED" else 1

    def generate_report(self):
        """Generate HTML report"""
        REPORT_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = self.result.start_time.strftime("%Y%m%d_%H%M%S")
        report_path = REPORT_DIR / f"aging_test_{timestamp}.html"

        # Determine status color
        if self.result.status == "PASSED":
            status_color = "#28a745"
            status_bg = "#d4edda"
        elif self.result.status == "FAILED":
            status_color = "#dc3545"
            status_bg = "#f8d7da"
        else:
            status_color = "#ffc107"
            status_bg = "#fff3cd"

        # Format duration
        hours = int(self.result.duration_seconds // 3600)
        minutes = int((self.result.duration_seconds % 3600) // 60)
        seconds = int(self.result.duration_seconds % 60)
        duration_str = f"{hours}h {minutes}m {seconds}s"

        # Generate events HTML
        events_html = ""
        for event in self.result.events:
            if "ERROR" in event:
                events_html += f'<div class="event error">{self._escape_html(event)}</div>\n'
            elif "WARN" in event:
                events_html += f'<div class="event warning">{self._escape_html(event)}</div>\n'
            else:
                events_html += f'<div class="event">{self._escape_html(event)}</div>\n'

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>dx_app Aging Test Report - {timestamp}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            padding: 30px;
        }}
        h1 {{
            color: #333;
            border-bottom: 2px solid #eee;
            padding-bottom: 15px;
        }}
        .status-banner {{
            background: {status_bg};
            color: {status_color};
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            font-size: 24px;
            font-weight: bold;
            text-align: center;
        }}
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        .summary-item {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            border-left: 4px solid #007bff;
        }}
        .summary-item label {{
            color: #666;
            font-size: 12px;
            text-transform: uppercase;
        }}
        .summary-item value {{
            display: block;
            font-size: 18px;
            font-weight: bold;
            color: #333;
            margin-top: 5px;
        }}
        .section {{
            margin: 30px 0;
        }}
        .section h2 {{
            color: #444;
            font-size: 18px;
            margin-bottom: 15px;
        }}
        .event {{
            font-family: 'Monaco', 'Consolas', monospace;
            font-size: 13px;
            padding: 5px 10px;
            border-left: 3px solid #ddd;
            margin: 2px 0;
            background: #fafafa;
        }}
        .event.error {{
            border-left-color: #dc3545;
            background: #fff5f5;
            color: #c0392b;
        }}
        .event.warning {{
            border-left-color: #ffc107;
            background: #fffbf0;
            color: #856404;
        }}
        .output {{
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 15px;
            border-radius: 6px;
            font-family: 'Monaco', 'Consolas', monospace;
            font-size: 12px;
            overflow-x: auto;
            white-space: pre-wrap;
            max-height: 400px;
            overflow-y: auto;
        }}
        .error-box {{
            background: #f8d7da;
            border: 1px solid #f5c6cb;
            color: #721c24;
            padding: 15px;
            border-radius: 6px;
            margin: 20px 0;
        }}
        .footer {{
            text-align: center;
            color: #999;
            font-size: 12px;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #eee;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>dx_app Aging Test Report</h1>

        <div class="status-banner">
            {self.result.status}
        </div>

        {"<div class='error-box'><strong>Error:</strong> " + self._escape_html(self.result.error_message) + "</div>" if self.result.error_message else ""}

        <div class="summary">
            <div class="summary-item">
                <label>Start Time</label>
                <value>{self.result.start_time.strftime("%Y-%m-%d %H:%M:%S")}</value>
            </div>
            <div class="summary-item">
                <label>End Time</label>
                <value>{self.result.end_time.strftime("%Y-%m-%d %H:%M:%S") if self.result.end_time else "N/A"}</value>
            </div>
            <div class="summary-item">
                <label>Duration</label>
                <value>{duration_str}</value>
            </div>
            <div class="summary-item">
                <label>Target Duration</label>
                <value>{TEST_DURATION_SECONDS} seconds</value>
            </div>
            <div class="summary-item">
                <label>yolo_multi Exit Code</label>
                <value>{self.result.yolo_exit_code if self.result.yolo_exit_code is not None else "Running/Terminated"}</value>
            </div>
            <div class="summary-item">
                <label>npu_usage Exit Code</label>
                <value>{self.result.npu_usage_exit_code if self.result.npu_usage_exit_code is not None else "Running/Terminated"}</value>
            </div>
        </div>

        <div class="section">
            <h2>Event Log</h2>
            {events_html}
        </div>

        <div class="section">
            <h2>yolo_multi Output (last 100 lines)</h2>
            <div class="output">{self._escape_html(self.result.yolo_output) or "(no output captured)"}</div>
        </div>

        <div class="section">
            <h2>npu_usage Output (last 100 lines)</h2>
            <div class="output">{self._escape_html(self.result.npu_usage_output) or "(no output captured)"}</div>
        </div>

        <div class="footer">
            Generated at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        </div>
    </div>
</body>
</html>
"""
        with open(report_path, 'w') as f:
            f.write(html)

        self.result.add_event(f"Report saved to: {report_path}")
        print(f"\nReport: {report_path}")

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters and strip ANSI escape codes"""
        if not text:
            return ""
        # Strip ANSI escape codes (e.g., \033[2J, \033[H)
        text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
        return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))


def main():
    parser = argparse.ArgumentParser(
        description="dx_app Aging Test - Runs yolo_multi with NPU monitoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 aging_test.py                  Run with display
  python3 aging_test.py --no-display     Run in headless mode (no display)

Exit codes:
  0  Test passed successfully
  1  Test failed (process error, NPU issue, or bbox anomaly)
"""
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="Run yolo_multi without display output (headless mode)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("dx_app Aging Test")
    print("=" * 60)

    test = AgingTest(no_display=args.no_display)
    return test.run()


if __name__ == "__main__":
    sys.exit(main())
