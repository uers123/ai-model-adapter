from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import ALLOWED_STATES, campaign_path, load_campaign, load_current, resolve_paths, scan_secrets


REQUIRED_CAMPAIGN = {"campaign_id", "model_id", "variant_id", "goal", "task_type", "acceptance"}
REQUIRED_BUDGET = {
    "max_iterations",
    "max_total_gpu_hours",
    "max_disk_usage_gb",
    "max_single_iteration_hours",
    "no_improvement_patience",
    "minimum_effective_improvement",
    "allowed_adaptation_methods",
    "allow_partial_unfreeze",
    "allow_full_finetuning",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one isolated campaign.")
    parser.add_argument("campaign_id")
    parser.add_argument("--tasks")
    args = parser.parse_args()
    _, tasks_root, _ = resolve_paths(None, args.tasks, None)
    directory = campaign_path(tasks_root, args.campaign_id)
    errors: list[str] = []
    try:
        campaign = load_campaign(directory)
        current = load_current(directory)
    except Exception as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    missing = sorted(REQUIRED_CAMPAIGN - set(campaign))
    if missing:
        errors.append(f"missing campaign fields: {missing}")
    status = current.get("status")
    if status not in ALLOWED_STATES:
        errors.append(f"invalid status: {status}")
    if status in {"authorized", "running", "pausing", "paused", "evaluating", "completed"}:
        budget = campaign.get("authorization", {}).get("budget", {})
        missing_budget = sorted(REQUIRED_BUDGET - set(budget))
        if missing_budget:
            errors.append(f"missing authorization budget fields: {missing_budget}")
    if scan_secrets(campaign):
        errors.append("secret-like data found in campaign")
    for split in ("train", "validation", "final_blind_test"):
        split_dir = directory / "data-manifests" / split
        if not split_dir.exists():
            errors.append(f"missing isolated split directory: {split_dir}")
    if current.get("current_iteration", 0) < 0:
        errors.append("current_iteration cannot be negative")
    result = {"campaign_id": args.campaign_id, "status": status, "valid": not errors, "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
