from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import load_current, status_is_terminal, utc_now, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent local campaign monitor.")
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=10)
    args = parser.parse_args()
    directory = args.campaign_dir.resolve()
    monitor_path = directory / "status" / "monitor.json"
    stop_path = directory / "status" / "unwatch.request"
    while True:
        if stop_path.exists():
            write_json({"campaign_id": directory.name, "pid": os.getpid(), "status": "unwatched", "updated_at": utc_now()}, monitor_path)
            stop_path.unlink()
            return 0
        current = load_current(directory)
        terminal = status_is_terminal(str(current.get("status")))
        write_json(
            {
                "campaign_id": directory.name,
                "pid": os.getpid(),
                "status": "terminal" if terminal else "watching",
                "campaign_status": current.get("status"),
                "last_campaign_heartbeat": current.get("heartbeat_at"),
                "updated_at": utc_now(),
                "authoritative_source": "status/current.json",
            },
            monitor_path,
        )
        if terminal:
            return 0
        time.sleep(max(0.1, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
