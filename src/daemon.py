"""
Background daemon for resume-sync.

Runs a single check cycle against all tracked projects, sends
notifications for any detected changes, and exits. Designed to be
called by Windows Task Scheduler every N minutes.

Usage:
    python -m src.daemon              # Single check cycle
    python -m src.daemon --loop       # Run in loop mode (per config interval)
"""

import argparse
import io
import sys
import time
from datetime import datetime
from pathlib import Path

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Ensure the project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.checker import Checker
from src.notifier import notify_changes


def run_check(config_path: str = "config.yaml") -> dict:
    """
    Execute a single check cycle. Returns the check results.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Daemon: checking projects...")
    checker = Checker(config_path=config_path)
    results = checker.check()

    for key, result in results.items():
        if result.get("message"):
            print(f"  {key}: {result['message']}")
        elif result.get("error"):
            print(f"  {key}: ERROR — {result['error']}")
        elif result.get("has_changes"):
            commits = result.get("new_commits", [])
            print(f"  {key}: {len(commits)} new commits detected")
            for c in commits:
                print(f"    - {c['hash'][:8]} {c['message'][:80]}")

            # Send notification
            notify_changes(key, len(commits))
        else:
            print(f"  {key}: no changes")

    return results


def main():
    parser = argparse.ArgumentParser(description="Resume-Sync Daemon")
    parser.add_argument("--loop", action="store_true",
                        help="Run continuously with interval from config")
    parser.add_argument("--interval", type=int, default=None,
                        help="Override check interval in minutes")
    args = parser.parse_args()

    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    config_path = str(config_path)

    if args.loop:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        interval_min = args.interval or cfg.get("daemon", {}).get("interval_minutes", 30)
        print(f"Daemon loop started — checking every {interval_min} minutes. Press Ctrl+C to stop.")
        try:
            while True:
                try:
                    run_check(config_path)
                except Exception as e:
                    print(f"  ERROR: {e}")
                time.sleep(interval_min * 60)
        except KeyboardInterrupt:
            print("\nDaemon stopped.")
    else:
        run_check(config_path)


if __name__ == "__main__":
    main()
