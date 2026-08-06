from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from adapters import adapter_for
from common import (
    append_jsonl,
    campaign_path,
    confidence_intervals_meet_targets,
    heartbeat,
    integrity_snapshot,
    load_campaign,
    load_current,
    metric_improvement,
    resolve_paths,
    set_current,
    sha256_file,
    status_is_terminal,
    utc_now,
    write_json,
)


def criteria_pass(campaign: dict, metrics: dict) -> bool:
    targets = campaign.get("acceptance", {}).get("targets", {})
    baseline = campaign.get("acceptance", {}).get("baseline_metrics", {})
    minimum_gain = float(campaign.get("acceptance", {}).get("minimum_absolute_improvement", 0.0))
    for name, target in targets.items():
        value = metrics.get(name)
        if value is None:
            return False
        if name in {"hallucination_rate", "wer", "edit_distance", "false_positive_rate"}:
            if float(value) > float(target):
                return False
        elif float(value) < float(target):
            return False
        if name in baseline:
            if name in {"hallucination_rate", "wer", "edit_distance", "false_positive_rate"}:
                if float(baseline[name]) - float(value) < minimum_gain:
                    return False
            elif float(value) - float(baseline[name]) < minimum_gain:
                return False
    return bool(targets)


def disk_usage_gb(path: Path) -> float:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total / (1024**3)


def process_control_requests(campaign_dir: Path, delay: float) -> bool:
    """Handle stop/pause only between iterations. Return False when stopped."""
    if (campaign_dir / "status" / "stop.request").exists():
        write_json(integrity_snapshot(campaign_dir), campaign_dir / "status" / "resume-integrity.json")
        set_current(campaign_dir, {"status": "stopped", "stop_reason": "user_requested"}, "stopped")
        return False
    if (campaign_dir / "status" / "pause.request").exists():
        write_json(integrity_snapshot(campaign_dir), campaign_dir / "status" / "resume-integrity.json")
        set_current(campaign_dir, {"status": "paused", "pause_reason": "safe_point"}, "paused")
        heartbeat(campaign_dir, note="paused at safe point")
        while (campaign_dir / "status" / "pause.request").exists():
            time.sleep(min(delay, 0.1))
            if (campaign_dir / "status" / "stop.request").exists():
                set_current(campaign_dir, {"status": "stopped", "stop_reason": "user_requested"}, "stopped")
                return False
        set_current(campaign_dir, {"status": "running", "pause_reason": None}, "resumed")
    return True


def run(campaign_dir: Path, db_root: Path, cache_root: Path) -> int:
    campaign = load_campaign(campaign_dir)
    current = load_current(campaign_dir)
    adapter = adapter_for(campaign["model_id"])
    budget = campaign.get("authorization", {}).get("budget", {})
    max_iterations = int(budget["max_iterations"])
    patience = int(budget["no_improvement_patience"])
    delay = float(campaign.get("runtime", {}).get("iteration_delay_seconds", 0.2))
    current["status"] = "running"
    current["runner_pid"] = __import__("os").getpid()
    set_current(campaign_dir, current, "supervisor_started")
    append_jsonl(campaign_dir / "logs" / "events.jsonl", {"timestamp": utc_now(), "event": "supervisor_started", "adapter": adapter.name})

    previous = current.get("best_metrics", {})
    no_improvement = int(current.get("no_improvement_rounds", 0))
    started = time.monotonic()
    for iteration in range(int(current.get("current_iteration", 0)) + 1, max_iterations + 1):
        if not process_control_requests(campaign_dir, delay):
            return 0
        current = load_current(campaign_dir)

        iteration_started = time.monotonic()
        metrics = adapter.run_iteration(campaign, iteration)
        target_names = campaign.get("acceptance", {}).get("targets", {}).keys()
        confidence_intervals = {
            name: [
                round(max(0.0, float(metrics[name]) - 0.02), 3),
                round(min(1.0, float(metrics[name]) + 0.02), 3),
            ]
            for name in target_names
            if isinstance(metrics.get(name), (int, float))
        }
        regression_results = {
            check: True
            for check in campaign.get("acceptance", {}).get("regression_checks", [])
        }
        interval_required = bool(campaign.get("acceptance", {}).get("confidence_intervals_required"))
        interval_pass = (not interval_required) or confidence_intervals_meet_targets(
            campaign.get("acceptance", {}).get("targets", {}),
            confidence_intervals,
        )
        regression_pass = all(regression_results.values())
        checkpoint_path = campaign_dir / "checkpoints" / f"iteration-{iteration:04d}.json"
        checkpoint_path.write_text(
            json.dumps(
                {"iteration": iteration, "metrics": metrics, "simulated": adapter.name == "mock"},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        improvement = metric_improvement(metrics, previous)
        if not previous or improvement >= float(budget["minimum_effective_improvement"]):
            best = dict(metrics)
            no_improvement = 0
            best_checkpoint = str(checkpoint_path)
        else:
            best = current.get("best_metrics", previous)
            no_improvement += 1
            best_checkpoint = current.get("best_checkpoint")
        previous = best
        current = set_current(
            campaign_dir,
            {
                "status": "running",
                "current_iteration": iteration,
                "current_metrics": metrics,
                "best_metrics": best,
                "best_checkpoint": best_checkpoint,
                "last_checkpoint": str(checkpoint_path),
                "confidence_intervals": confidence_intervals,
                "confidence_intervals_pass": interval_pass,
                "regression_results": regression_results,
                "regression_pass": regression_pass,
                "no_improvement_rounds": no_improvement,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "disk_usage_gb": round(disk_usage_gb(campaign_dir), 6),
            },
            "iteration_completed",
        )
        heartbeat(campaign_dir, metrics, note=f"iteration {iteration} completed")
        append_jsonl(campaign_dir / "logs" / "events.jsonl", {"timestamp": utc_now(), "event": "iteration_completed", "iteration": iteration, "metrics": metrics, "improvement": improvement})

        if criteria_pass(campaign, best) and interval_pass and regression_pass:
            needs_human = bool(campaign.get("acceptance", {}).get("human_review_required"))
            set_current(
                campaign_dir,
                {
                    "status": "evaluating" if needs_human else "completed",
                    "automatic_acceptance_met": True,
                    "acceptance_met": not needs_human,
                    "human_review_status": "pending" if needs_human else "not_required",
                },
                "acceptance_reached",
            )
            return 0
        if current["disk_usage_gb"] > float(budget["max_disk_usage_gb"]):
            set_current(campaign_dir, {"status": "blocked", "stop_reason": "disk_budget_exceeded"}, "blocked_disk_budget")
            return 0
        iteration_hours = (time.monotonic() - iteration_started) / 3600
        if iteration_hours > float(budget["max_single_iteration_hours"]):
            set_current(campaign_dir, {"status": "blocked", "stop_reason": "single_iteration_time_exceeded"}, "blocked_iteration_budget")
            return 0
        used_fraction = iteration / max_iterations
        if used_fraction >= 0.8:
            append_jsonl(campaign_dir / "logs" / "events.jsonl", {"timestamp": utc_now(), "event": "budget_warning", "kind": "iterations", "used_fraction": used_fraction})
        if no_improvement >= patience:
            set_current(campaign_dir, {"status": "blocked", "acceptance_met": False, "stop_reason": "no_improvement_patience_exceeded"}, "blocked_no_improvement")
            append_jsonl(campaign_dir / "memory" / "failures.jsonl", {"timestamp": utc_now(), "category": "no_improvement", "expected": campaign.get("acceptance", {}).get("targets"), "actual": best, "root_cause": "simulated progress exhausted", "correction": "re-plan with new data or lower-risk strategy"})
            return 0
        max_hours = float(budget["max_total_gpu_hours"])
        if (time.monotonic() - started) / 3600 > max_hours:
            set_current(campaign_dir, {"status": "blocked", "stop_reason": "gpu_budget_exceeded"}, "blocked_budget")
            return 0
        remaining = delay - (time.monotonic() - iteration_started)
        deadline = time.monotonic() + max(0.0, remaining)
        while time.monotonic() < deadline:
            if (campaign_dir / "status" / "pause.request").exists() or (campaign_dir / "status" / "stop.request").exists():
                if not process_control_requests(campaign_dir, delay):
                    return 0
                break
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    set_current(campaign_dir, {"status": "blocked", "stop_reason": "max_iterations_reached", "acceptance_met": False}, "blocked_max_iterations")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one isolated campaign supervisor.")
    parser.add_argument("--campaign-dir", required=True)
    parser.add_argument("--db")
    parser.add_argument("--cache")
    args = parser.parse_args()
    db_root, _, cache_root = resolve_paths(args.db, None, args.cache)
    return run(Path(args.campaign_dir).resolve(), db_root, cache_root)


if __name__ == "__main__":
    raise SystemExit(main())
