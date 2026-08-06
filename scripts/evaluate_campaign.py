from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import (
    append_jsonl,
    campaign_path,
    confidence_intervals_meet_targets,
    load_campaign,
    load_current,
    resolve_paths,
    set_current,
    utc_now,
    write_json,
)


def criteria_pass(campaign: dict, metrics: dict) -> bool:
    targets = campaign.get("acceptance", {}).get("targets", {})
    baseline = campaign.get("acceptance", {}).get("baseline_metrics", {})
    minimum_gain = float(campaign.get("acceptance", {}).get("minimum_absolute_improvement", 0.0))
    for name, target in targets.items():
        if name not in metrics:
            return False
        value = float(metrics[name])
        if name in {"hallucination_rate", "wer", "edit_distance", "false_positive_rate"}:
            if value > float(target):
                return False
        elif value < float(target):
            return False
        if name in baseline:
            if name in {"hallucination_rate", "wer", "edit_distance", "false_positive_rate"}:
                if float(baseline[name]) - value < minimum_gain:
                    return False
            elif value - float(baseline[name]) < minimum_gain:
                return False
    return bool(targets)


def evaluate(directory: Path, blind_review_file: Path | None = None) -> dict:
    campaign = load_campaign(directory)
    current = load_current(directory)
    metrics = current.get("best_metrics") or current.get("current_metrics") or {}
    blind_manifest = directory / "data-manifests" / "final_blind_test" / "manifest.jsonl"
    blind_test_used = blind_manifest.exists() and any(line.strip() for line in blind_manifest.read_text(encoding="utf-8").splitlines())
    human_status = current.get("human_review_status", "not_required")
    intervals = current.get("confidence_intervals", {})
    interval_required = bool(campaign.get("acceptance", {}).get("confidence_intervals_required"))
    targets = campaign.get("acceptance", {}).get("targets", {})
    missing_intervals = [name for name in targets if name not in intervals]
    interval_pass = (not interval_required) or confidence_intervals_meet_targets(targets, intervals)
    regression_results = current.get("regression_results", {})
    required_regressions = campaign.get("acceptance", {}).get("regression_checks", [])
    regression_pass = all(regression_results.get(name) is True for name in required_regressions)
    human_scores = None
    human_accepted = None
    if blind_review_file:
        payload = json.loads(blind_review_file.read_text(encoding="utf-8"))
        if payload.get("model_version") or payload.get("training_iteration"):
            raise ValueError("Blind review input must not reveal model version or training iteration.")
        human_scores = payload.get("scores")
        if not isinstance(human_scores, dict):
            raise ValueError("Blind review file requires a scores object.")
        human_accepted = payload.get("accepted")
        if not isinstance(human_accepted, bool):
            raise ValueError("Blind review file requires an explicit boolean accepted decision.")
        human_status = "confirmed"
    automatic_pass = criteria_pass(campaign, metrics)
    human_required = bool(campaign.get("acceptance", {}).get("human_review_required"))
    human_pass = (not human_required) or (human_status == "confirmed" and human_accepted is True)
    accepted = automatic_pass and interval_pass and regression_pass and blind_test_used and human_pass
    status = "completed" if accepted else ("evaluating" if automatic_pass and interval_pass and regression_pass and blind_test_used and human_required and human_status != "confirmed" else "blocked")
    blocking_reasons = (
        ([] if automatic_pass else ["automatic_metrics_or_minimum_gain_not_met"])
        + ([] if blind_test_used else ["final_blind_test_manifest_empty"])
        + ([] if not missing_intervals else ["confidence_intervals_missing"])
        + ([] if (not interval_required or interval_pass or missing_intervals) else ["confidence_intervals_do_not_support_targets"])
        + ([] if regression_pass else ["regression_checks_incomplete"])
        + ([] if not human_required or human_status == "confirmed" else ["human_review_pending"])
        + ([] if not human_required or human_status != "confirmed" or human_accepted is True else ["human_review_rejected"])
    )
    record = {
        "record_id": f"{campaign['campaign_id']}-evaluation-{current.get('current_iteration', 0):04d}",
        "campaign_id": campaign["campaign_id"],
        "model_id": campaign["model_id"],
        "variant_id": campaign["variant_id"],
        "evaluated_at": utc_now(),
        "automatic_metrics": metrics,
        "automatic_pass": automatic_pass,
        "baseline_metrics": campaign.get("acceptance", {}).get("baseline_metrics", {}),
        "minimum_absolute_improvement": campaign.get("acceptance", {}).get("minimum_absolute_improvement"),
        "confidence_level": campaign.get("acceptance", {}).get("confidence_level"),
        "confidence_intervals": intervals,
        "confidence_intervals_pass": interval_pass,
        "regression_results": regression_results,
        "regression_pass": regression_pass,
        "human_review_status": human_status,
        "human_scores": human_scores,
        "human_accepted": human_accepted,
        "accepted": accepted,
        "blind_test_used": bool(blind_test_used),
        "blocking_reasons": blocking_reasons,
    }
    write_json(record, directory / "evaluations" / f"{record['record_id']}.json")
    set_current(directory, {"status": status, "acceptance_met": accepted, "human_review_status": human_status, "last_evaluation": record["record_id"]}, "evaluation_completed")
    append_jsonl(directory / "logs" / "events.jsonl", {"timestamp": utc_now(), "event": "evaluation_completed", "record_id": record["record_id"], "accepted": accepted})
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign_id")
    parser.add_argument("--tasks")
    parser.add_argument("--blind-review-file")
    args = parser.parse_args()
    _, tasks_root, _ = resolve_paths(None, args.tasks, None)
    directory = campaign_path(tasks_root, args.campaign_id)
    record = evaluate(directory, Path(args.blind_review_file) if args.blind_review_file else None)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
