from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import campaign_path, load_current, resolve_paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Read the local authoritative campaign state.")
    parser.add_argument("campaign_id")
    parser.add_argument("--tasks")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=10)
    args = parser.parse_args()
    _, tasks_root, _ = resolve_paths(None, args.tasks, None)
    directory = campaign_path(tasks_root, args.campaign_id)
    while True:
        print(json.dumps(load_current(directory), ensure_ascii=False, indent=2))
        if args.once or load_current(directory).get("status") in {"completed", "blocked", "failed", "stopped"}:
            return 0
        time.sleep(max(0.1, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
