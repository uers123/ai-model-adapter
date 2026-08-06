from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from adapters import adapter_for
from common import (
    append_jsonl,
    atomic_write_text,
    campaign_path,
    dump_yaml,
    ensure_campaign_workspace,
    load_campaign,
    load_current,
    load_yaml,
    model_record,
    parse_csv,
    process_is_running,
    read_jsonl,
    resolve_paths,
    save_campaign,
    set_current,
    integrity_snapshot,
    status_is_terminal,
    utc_now,
    verify_integrity_snapshot,
    write_json,
)


def targets_for(task_type: str) -> tuple[dict[str, float], bool]:
    task_type = task_type.lower()
    if task_type == "classification":
        return {"accuracy": 0.80, "f1": 0.78}, False
    if task_type == "detection":
        return {"map": 0.70, "recall": 0.80, "false_positive_rate": 0.10}, False
    if task_type == "ocr":
        return {"character_accuracy": 0.90, "edit_distance": 0.10}, False
    if task_type == "asr":
        return {"wer": 0.20}, False
    if task_type == "image_qa":
        return {"answer_accuracy": 0.80, "hallucination_rate": 0.10}, True
    if task_type == "generation":
        return {"task_metric": 0.75, "relevance": 0.80, "safety": 0.95}, True
    return {"endpoint_success_rate": 0.80, "key_case_pass_rate": 0.90, "hallucination_rate": 0.10}, True


def mock_baseline_for(task_type: str) -> dict[str, float]:
    task_type = task_type.lower()
    if task_type == "classification":
        return {"accuracy": 0.60, "f1": 0.56}
    if task_type == "multimodal":
        return {"endpoint_success_rate": 0.58, "key_case_pass_rate": 0.68, "hallucination_rate": 0.20}
    return {}


def parse_metric_pairs(values: list[str], flag: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"{flag} requires metric=value, got {item!r}")
        name, value = item.split("=", 1)
        result[name.strip()] = float(value)
    return result


def qualification_snapshot(db_root: Path, model_id: str, variant_id: str) -> dict[str, Any]:
    if model_id.lower() in {"mock", "mock-model", "simulator"}:
        return {"model_id": model_id, "license": "simulation-only", "training_entrypoints": ["mock"], "evaluation_methods": ["deterministic simulated metrics"], "source_revision": "built-in", "required_resources": []}
    record = model_record(db_root, model_id)
    qualification = record.get("qualification", {})
    variant_path = db_root / "models" / model_id / "variants" / variant_id / "variant.yaml"
    if not variant_path.exists():
        raise FileNotFoundError(f"variant record not found: {variant_path}")
    variant = load_yaml(variant_path)
    resources = []
    resource_path = db_root / "models" / model_id / "records" / "resources.jsonl"
    if resource_path.exists():
        for resource in read_jsonl(resource_path):
            if resource.get("training_required") and resource.get("variant_id") in {None, variant_id}:
                resources.append(
                    {
                        "resource_id": resource.get("record_id"),
                        "local_path": resource.get("recommended_cache_path"),
                        "url": resource.get("url"),
                        "download_policy": resource.get("download_policy"),
                    }
                )
    return {
        "model_id": model_id,
        "license": record.get("license"),
        "variant_id": variant_id,
        "training_entrypoints": variant.get("training_entrypoints", qualification.get("training_entrypoints", [])),
        "inference_entrypoint": variant.get("inference_entrypoint", qualification.get("inference_entrypoint")),
        "required_resources": resources,
        "source_revision": variant.get("source_revision", record.get("source_revision")),
        "evaluation_methods": qualification.get("evaluation_methods", []),
        "compatibility": variant.get("compatibility", {}),
    }


def qualification_errors(snapshot: dict[str, Any]) -> list[str]:
    required = ("license", "training_entrypoints", "evaluation_methods", "source_revision")
    return [name for name in required if not snapshot.get(name)]


def required_budget_errors(campaign: dict[str, Any]) -> list[str]:
    required = {
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
    budget = campaign.get("authorization", {}).get("budget", {}) if campaign.get("authorization") else {}
    return sorted(required - set(budget))


def cmd_plan(args: argparse.Namespace) -> int:
    db_root, tasks_root, cache_root = resolve_paths(args.db, args.tasks, args.cache)
    if not args.model:
        candidates = []
        for path in (db_root / "models").glob("*/records/model.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            candidates.append({"model_id": data.get("model_id"), "display_name": data.get("display_name"), "modalities": data.get("modalities"), "status": data.get("status")})
        print(json.dumps({"action": "recommend", "candidates": candidates, "reason": "model must be specified or selected explicitly before authorization"}, ensure_ascii=False, indent=2))
        return 2
    campaign_id = args.campaign_id or f"campaign-{utc_now().replace(':','').replace('-','')}"
    directory = campaign_path(tasks_root, campaign_id)
    if directory.exists() and any(directory.iterdir()):
        raise FileExistsError(f"campaign already exists: {directory}")
    ensure_campaign_workspace(directory)
    targets, human_review = targets_for(args.task_type)
    if args.targets_json:
        targets.update(json.loads(args.targets_json))
    targets.update(parse_metric_pairs(args.target, "--target"))
    baseline = parse_metric_pairs(args.baseline, "--baseline")
    if args.model.lower() in {"mock", "mock-model", "simulator"} and not baseline:
        baseline = mock_baseline_for(args.task_type)
    variant_id = args.variant_id or ("official-current" if args.model.lower().replace("_", "-") in {"next-gpt", "next-gpt"} else "simulated")
    snapshot = qualification_snapshot(db_root, args.model, variant_id)
    lesson_path = db_root / "models" / args.model / "records" / "verified-lessons.jsonl"
    prior_lessons = read_jsonl(lesson_path) if lesson_path.exists() else []
    campaign = {
        "campaign_id": campaign_id,
        "created_at": utc_now(),
        "model_id": args.model,
        "variant_id": variant_id,
        "goal": args.goal,
        "task_type": args.task_type,
        "input_modalities": parse_csv(args.input_modalities),
        "output_modalities": parse_csv(args.output_modalities),
        "source_revision": snapshot.get("source_revision", "local-plan"),
        "qualification_snapshot": snapshot,
        "qualification_errors": qualification_errors(snapshot),
        "prior_verified_lessons": prior_lessons,
        "acceptance": {
            "targets": targets,
            "baseline_metrics": baseline,
            "baseline_status": "available" if baseline else "required_before_real_training",
            "minimum_absolute_improvement": args.minimum_absolute_improvement,
            "confidence_level": args.confidence_level,
            "confidence_intervals_required": True,
            "regression_checks": args.regression_check
            or ["preserve_supported_modalities", "no_secret_leakage", "no_unapproved_downloads"],
            "human_review_required": human_review,
            "blind_test_manifest": "data-manifests/final_blind_test/manifest.jsonl",
        },
        "adaptation_plan": {
            "stage_order": ["inference", "rag", "data_quality", "lora", "partial_unfreeze", "full_finetuning", "projection", "architecture", "replacement"],
            "selected_stage": "inference",
            "requires_architecture_approval": False,
        },
        "runtime": {
            "host_platform": "windows-native",
            "execution_environment": snapshot.get("compatibility", {}).get("windows", "windows-native"),
            "requires_separate_environment_approval": snapshot.get("compatibility", {}).get("windows") in {"wsl2-required", "linux-only"},
            "iteration_delay_seconds": args.iteration_delay_seconds,
            "dry_run": args.model.lower().replace("_", "-") in {"next-gpt", "next-gpt"},
        },
        "status": "awaiting_authorization",
        "authorization": None,
        "updated_at": utc_now(),
    }
    save_campaign(directory, campaign)
    write_json({"campaign_id": campaign_id, "status": "awaiting_authorization", "current_iteration": 0, "best_metrics": {}, "current_metrics": {}, "acceptance_met": False, "created_at": campaign["created_at"], "updated_at": utc_now()}, directory / "status" / "current.json")
    append_jsonl(directory / "status" / "history.jsonl", {"timestamp": utc_now(), "event": "planned", "status": "awaiting_authorization"})
    for split in ("train", "validation", "final_blind_test"):
        manifest_path = directory / "data-manifests" / split / "manifest.jsonl"
        if args.model.lower() in {"mock", "mock-model", "simulator"}:
            atomic_write_text(
                manifest_path,
                json.dumps(
                    {
                        "sample_id": f"mock-{split}-001",
                        "split": split,
                        "source": "built-in-synthetic-fixture",
                        "license": "simulation-only",
                        "sha256": "not-a-real-file",
                        "modalities": campaign["input_modalities"],
                        "synthetic": True,
                    },
                    ensure_ascii=False,
                )
                + "\n",
            )
        else:
            atomic_write_text(manifest_path, "")
    print(json.dumps({"campaign_id": campaign_id, "path": str(directory), "status": "awaiting_authorization", "acceptance": campaign["acceptance"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_authorize(args: argparse.Namespace) -> int:
    _, tasks_root, _ = resolve_paths(args.db, args.tasks, args.cache)
    directory = campaign_path(tasks_root, args.campaign_id)
    campaign = load_campaign(directory)
    current = load_current(directory)
    if current.get("status") != "awaiting_authorization":
        raise ValueError(f"authorize requires awaiting_authorization, got {current.get('status')}")
    errors = qualification_errors(campaign.get("qualification_snapshot", {}))
    if errors:
        raise ValueError(f"model is not execution-qualified; missing fields: {errors}")
    methods = parse_csv(args.allowed_adaptation_methods)
    if "architecture" in methods and not args.architecture_approved:
        raise ValueError("architecture adaptation requires separate --architecture-approved")
    execution_environment = campaign.get("runtime", {}).get("execution_environment")
    if execution_environment == "wsl2-required" and not args.approve_wsl2:
        raise ValueError("this variant requires separate --approve-wsl2 authorization")
    if execution_environment == "linux-only" and not args.approve_linux:
        raise ValueError("this variant requires separate --approve-linux authorization")
    campaign["authorization"] = {
        "authorized_at": utc_now(),
        "budget": {
            "max_iterations": args.max_iterations,
            "max_total_gpu_hours": args.max_total_gpu_hours,
            "max_disk_usage_gb": args.max_disk_usage_gb,
            "max_single_iteration_hours": args.max_single_iteration_hours,
            "no_improvement_patience": args.no_improvement_patience,
            "minimum_effective_improvement": args.minimum_effective_improvement,
            "allowed_adaptation_methods": methods,
            "allow_partial_unfreeze": args.allow_partial_unfreeze == "yes",
            "allow_full_finetuning": args.allow_full_finetuning == "yes",
        },
        "architecture_approved": bool(args.architecture_approved),
        "wsl2_approved": bool(args.approve_wsl2),
        "linux_approved": bool(args.approve_linux),
        "data_scope": args.data_scope,
        "stop_conditions": ["acceptance_met", "budget_exhausted", "no_improvement", "user_stop", "blocking_error"],
    }
    campaign["status"] = "authorized"
    save_campaign(directory, campaign)
    set_current(directory, {"status": "authorized", "authorized_at": campaign["authorization"]["authorized_at"]}, "authorized")
    print(json.dumps({"campaign_id": args.campaign_id, "status": "authorized"}, ensure_ascii=False))
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    db_root, tasks_root, cache_root = resolve_paths(args.db, args.tasks, args.cache)
    directory = campaign_path(tasks_root, args.campaign_id)
    campaign = load_campaign(directory)
    current = load_current(directory)
    if current.get("status") != "authorized":
        raise ValueError(f"start requires authorized, got {current.get('status')}")
    missing_budget = required_budget_errors(campaign)
    if missing_budget:
        raise ValueError(f"start blocked; missing authorization budget fields: {missing_budget}")
    if args.real_training and not campaign.get("acceptance", {}).get("baseline_metrics"):
        raise ValueError("real training blocked; baseline_metrics are required")
    write_json({"campaign_id": args.campaign_id, "registered_at": utc_now(), "interval_minutes": 10, "authoritative_source": "status/current.json", "automatic": True}, directory / "status" / "watch.json")
    adapter = adapter_for(campaign["model_id"])
    if adapter.name == "next-gpt":
        report = adapter.dry_run(campaign, db_root, cache_root)
        report["real_training_requested"] = bool(args.real_training)
        report["real_training_supported"] = False
        write_json(report, directory / "reports" / "next-gpt-dry-run.json")
        stop_reason = "next_gpt_missing_resources" if report["status"] != "ready" else "next_gpt_adapter_dry_run_only"
        set_current(directory, {"status": "blocked", "stop_reason": stop_reason, "dry_run_report": "reports/next-gpt-dry-run.json"}, "next_gpt_dry_run_blocked")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    set_current(directory, {"status": "running", "started_at": utc_now()}, "started")
    supervisor = SCRIPT_DIR / "campaign_supervisor.py"
    monitor = SCRIPT_DIR / "campaign_monitor.py"
    command = [sys.executable, str(supervisor), "--campaign-dir", str(directory), "--db", str(db_root), "--cache", str(cache_root)]
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    monitor_process = subprocess.Popen([sys.executable, str(monitor), "--campaign-dir", str(directory), "--interval-seconds", str(args.monitor_interval_seconds)], creationflags=flags)
    set_current(directory, {"monitor_pid": monitor_process.pid}, "monitor_spawned")
    if args.foreground:
        return subprocess.run(command, check=False).returncode
    process = subprocess.Popen(command, creationflags=flags)
    set_current(directory, {"runner_pid": process.pid, "monitor_pid": monitor_process.pid}, "supervisor_spawned")
    print(json.dumps({"campaign_id": args.campaign_id, "status": "running", "pid": process.pid, "monitor_pid": monitor_process.pid}, ensure_ascii=False))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    _, tasks_root, _ = resolve_paths(args.db, args.tasks, args.cache)
    print(json.dumps(load_current(campaign_path(tasks_root, args.campaign_id)), ensure_ascii=False, indent=2))
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    _, tasks_root, _ = resolve_paths(args.db, args.tasks, args.cache)
    directory = campaign_path(tasks_root, args.campaign_id)
    write_json({"campaign_id": args.campaign_id, "registered_at": utc_now(), "interval_minutes": args.interval_minutes, "authoritative_source": "status/current.json"}, directory / "status" / "watch.json")
    current = load_current(directory)
    monitor_path = directory / "status" / "monitor.json"
    monitor_state = json.loads(monitor_path.read_text(encoding="utf-8")) if monitor_path.exists() else {}
    if monitor_state.get("status") != "watching" and not status_is_terminal(str(current.get("status"))):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0
        process = subprocess.Popen([sys.executable, str(SCRIPT_DIR / "campaign_monitor.py"), "--campaign-dir", str(directory), "--interval-seconds", str(max(0.1, args.interval_minutes * 60))], creationflags=flags)
        set_current(directory, {"monitor_pid": process.pid}, "monitor_spawned")
    print(json.dumps({"watching": args.campaign_id, "interval_minutes": args.interval_minutes}, ensure_ascii=False))
    return 0


def cmd_unwatch(args: argparse.Namespace) -> int:
    _, tasks_root, _ = resolve_paths(args.db, args.tasks, args.cache)
    path = campaign_path(tasks_root, args.campaign_id) / "status" / "watch.json"
    directory = campaign_path(tasks_root, args.campaign_id)
    request = directory / "status" / "unwatch.request"
    monitor_path = directory / "status" / "monitor.json"
    atomic_write_text(request, utc_now() + "\n")
    if path.exists():
        path.unlink()
    monitor_state = json.loads(monitor_path.read_text(encoding="utf-8")) if monitor_path.exists() else {}
    stale_reconciled = False
    if not process_is_running(monitor_state.get("pid")):
        write_json(
            {
                "campaign_id": args.campaign_id,
                "pid": monitor_state.get("pid"),
                "status": "unwatched",
                "updated_at": utc_now(),
                "stale_process_reconciled": True,
            },
            monitor_path,
        )
        if request.exists():
            request.unlink()
        stale_reconciled = True
    print(json.dumps({"watching": False, "campaign_id": args.campaign_id, "stale_process_reconciled": stale_reconciled}, ensure_ascii=False))
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    _, tasks_root, _ = resolve_paths(args.db, args.tasks, args.cache)
    directory = campaign_path(tasks_root, args.campaign_id)
    current = load_current(directory)
    if current.get("status") != "running":
        raise ValueError(f"pause requires running, got {current.get('status')}")
    atomic_write_text(directory / "status" / "pause.request", utc_now() + "\n")
    set_current(directory, {"status": "pausing"}, "pause_requested")
    print(json.dumps({"campaign_id": args.campaign_id, "status": "pausing"}, ensure_ascii=False))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    db_root, tasks_root, cache_root = resolve_paths(args.db, args.tasks, args.cache)
    directory = campaign_path(tasks_root, args.campaign_id)
    current = load_current(directory)
    original_status = current.get("status")
    if original_status not in {"paused", "pausing", "stopped"}:
        raise ValueError(f"resume requires paused, pausing or stopped, got {original_status}")
    request = directory / "status" / "pause.request"
    stop_request = directory / "status" / "stop.request"
    snapshot_path = directory / "status" / "resume-integrity.json"
    if not snapshot_path.exists():
        raise ValueError("resume blocked; safe-point integrity snapshot is missing")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    integrity_errors = verify_integrity_snapshot(directory, snapshot)
    if integrity_errors:
        set_current(directory, {"status": "blocked", "stop_reason": "resume_integrity_failed", "integrity_errors": integrity_errors}, "resume_blocked")
        raise ValueError(f"resume integrity verification failed: {integrity_errors}")
    if request.exists():
        request.unlink()
    if stop_request.exists():
        stop_request.unlink()
    set_current(directory, {"status": "running", "resumed_at": utc_now()}, "resume_requested")
    result: dict[str, Any] = {"campaign_id": args.campaign_id, "status": "running"}
    if original_status == "stopped":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0
        supervisor = subprocess.Popen(
            [sys.executable, str(SCRIPT_DIR / "campaign_supervisor.py"), "--campaign-dir", str(directory), "--db", str(db_root), "--cache", str(cache_root)],
            creationflags=flags,
        )
        monitor = subprocess.Popen(
            [sys.executable, str(SCRIPT_DIR / "campaign_monitor.py"), "--campaign-dir", str(directory), "--interval-seconds", str(args.monitor_interval_seconds)],
            creationflags=flags,
        )
        set_current(directory, {"runner_pid": supervisor.pid, "monitor_pid": monitor.pid}, "resumed_processes_spawned")
        result.update({"pid": supervisor.pid, "monitor_pid": monitor.pid})
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    _, tasks_root, _ = resolve_paths(args.db, args.tasks, args.cache)
    directory = campaign_path(tasks_root, args.campaign_id)
    current = load_current(directory)
    if current.get("status") not in {"running", "pausing", "paused"}:
        raise ValueError(f"stop requires running, pausing or paused, got {current.get('status')}")
    atomic_write_text(directory / "status" / "stop.request", utc_now() + "\n")
    set_current(directory, {"stop_requested_at": utc_now()}, "stop_requested")
    for _ in range(50):
        current = load_current(directory)
        if current.get("status") == "stopped":
            break
        __import__("time").sleep(0.1)
    print(json.dumps({"campaign_id": args.campaign_id, "status": current.get("status"), "stop_pending": current.get("status") != "stopped"}, ensure_ascii=False))
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    from evaluate_campaign import evaluate
    _, tasks_root, _ = resolve_paths(args.db, args.tasks, args.cache)
    directory = campaign_path(tasks_root, args.campaign_id)
    record = evaluate(directory, Path(args.blind_review_file) if args.blind_review_file else None)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    db_root, tasks_root, _ = resolve_paths(args.db, args.tasks, args.cache)
    directory = campaign_path(tasks_root, args.campaign_id)
    campaign = load_campaign(directory)
    current = load_current(directory)
    if current.get("status") != "completed" or not current.get("acceptance_met"):
        raise ValueError("export requires completed campaign with acceptance_met=true")
    version = args.version or "v1.0.0"
    final = directory / "final" / version
    final.mkdir(parents=True, exist_ok=False)
    for name in ("adapters", "configs", "inference", "evaluation", "data-manifest", "dependency-lock"):
        (final / name).mkdir(parents=True, exist_ok=True)
    manifest = {
        "model_id": campaign["model_id"],
        "variant_id": campaign["variant_id"],
        "campaign_id": campaign["campaign_id"],
        "version": version,
        "artifact_type": "adapter-summary",
        "base_model_unchanged": True,
        "weights_downloaded_by_skill": False,
        "best_metrics": current.get("best_metrics", {}),
        "evaluation_record": current.get("last_evaluation"),
        "limitations": ["This first-party export contains orchestration metadata only; no model weights are created by the mock or NExT-GPT dry-run adapter."],
    }
    dump_yaml(manifest, final / "model-manifest.yaml")
    write_json(campaign.get("acceptance", {}), final / "evaluation" / "acceptance.json")
    write_json(current.get("best_metrics", {}), final / "evaluation" / "metrics.json")
    write_json({"train": "data-manifests/train", "validation": "data-manifests/validation", "final_blind_test": "data-manifests/final_blind_test"}, final / "data-manifest" / "splits.json")
    write_json({"python": sys.version, "adapter": adapter_for(campaign["model_id"]).name}, final / "dependency-lock" / "runtime.json")
    atomic_write_text(final / "inference" / "README.md", "# Inference\n\nThis export contains orchestration metadata only. No base-model weights are bundled.\n")
    checksum_lines = []
    for path in sorted(final.rglob("*")):
        if path.is_file() and path.name != "checksums.sha256":
            digest = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
            checksum_lines.append(f"{digest}  {str(path.relative_to(final)).replace(chr(92), '/')}")
    atomic_write_text(final / "checksums.sha256", "\n".join(checksum_lines) + "\n")
    print(json.dumps({"exported": str(final), "manifest": manifest}, ensure_ascii=False, indent=2))
    return 0


def cmd_update_db(args: argparse.Namespace) -> int:
    db_root, tasks_root, _ = resolve_paths(args.db, args.tasks, args.cache)
    directory = campaign_path(tasks_root, args.campaign_id)
    campaign = load_campaign(directory)
    current = load_current(directory)
    proposal = {
        "proposal_id": f"{args.campaign_id}-{utc_now()[:10]}",
        "created_at": utc_now(),
        "status": "pending_review",
        "source_campaign": args.campaign_id,
        "model_id": campaign["model_id"],
        "variant_id": campaign["variant_id"],
        "summary": {"status": current.get("status"), "best_metrics": current.get("best_metrics", {}), "stop_reason": current.get("stop_reason")},
        "evidence": [str(path.relative_to(directory)).replace("\\", "/") for path in (directory / "evaluations").glob("*.json")],
        "failure_records": read_jsonl(directory / "memory" / "failures.jsonl"),
        "lesson_candidates": [
            {
                "scope": "model",
                "status": "pending_review",
                "lesson": record.get("root_cause") or record.get("category"),
                "prevention_rule": record.get("correction"),
            }
            for record in read_jsonl(directory / "memory" / "failures.jsonl")
        ],
    }
    model_directory = db_root / "models" / campaign["model_id"]
    target_root = model_directory / "pending-updates" if model_directory.exists() else db_root / "pending-updates" / campaign["model_id"]
    target = target_root / f"{proposal['proposal_id']}.json"
    write_json(proposal, target)
    print(json.dumps({"pending_update": str(target), "status": proposal["status"]}, ensure_ascii=False, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="/ai-model-adapter", description="Explicitly authorized local-first model adaptation orchestration.")
    sub = p.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--campaign-id")
    plan.add_argument("--model")
    plan.add_argument("--variant-id")
    plan.add_argument("--goal", required=True)
    plan.add_argument("--task-type", required=True)
    plan.add_argument("--input-modalities", required=True)
    plan.add_argument("--output-modalities", required=True)
    plan.add_argument("--targets-json")
    plan.add_argument("--target", action="append", default=[], help="Override one acceptance target as metric=value; repeatable.")
    plan.add_argument("--baseline", action="append", default=[], help="Record one baseline metric as metric=value; repeatable.")
    plan.add_argument("--minimum-absolute-improvement", type=float, default=0.05)
    plan.add_argument("--confidence-level", type=float, default=0.95)
    plan.add_argument("--regression-check", action="append", default=[])
    plan.add_argument("--iteration-delay-seconds", type=float, default=0.2)
    for name in ("db", "tasks", "cache"):
        plan.add_argument(f"--{name}")
    plan.set_defaults(func=cmd_plan)

    auth = sub.add_parser("authorize")
    auth.add_argument("campaign_id")
    auth.add_argument("--max-iterations", type=int, required=True)
    auth.add_argument("--max-total-gpu-hours", type=float, required=True)
    auth.add_argument("--max-disk-usage-gb", type=float, required=True)
    auth.add_argument("--max-single-iteration-hours", type=float, required=True)
    auth.add_argument("--no-improvement-patience", type=int, required=True)
    auth.add_argument("--minimum-effective-improvement", type=float, required=True)
    auth.add_argument("--allowed-adaptation-methods", required=True)
    auth.add_argument("--allow-partial-unfreeze", choices=("yes", "no"), required=True)
    auth.add_argument("--allow-full-finetuning", choices=("yes", "no"), required=True)
    auth.add_argument("--data-scope", required=True)
    auth.add_argument("--architecture-approved", action="store_true")
    auth.add_argument("--approve-wsl2", action="store_true")
    auth.add_argument("--approve-linux", action="store_true")
    for name in ("db", "tasks", "cache"):
        auth.add_argument(f"--{name}")
    auth.set_defaults(func=cmd_authorize)

    start = sub.add_parser("start")
    start.add_argument("campaign_id")
    start.add_argument("--foreground", action="store_true")
    start.add_argument("--real-training", action="store_true")
    start.add_argument("--monitor-interval-seconds", type=float, default=10)
    for name in ("db", "tasks", "cache"):
        start.add_argument(f"--{name}")
    start.set_defaults(func=cmd_start)

    for name, func in (("status", cmd_status), ("watch", cmd_watch), ("unwatch", cmd_unwatch), ("pause", cmd_pause), ("resume", cmd_resume), ("stop", cmd_stop)):
        subparser = sub.add_parser(name)
        subparser.add_argument("campaign_id")
        if name == "watch":
            subparser.add_argument("--interval-minutes", type=float, default=10)
        if name == "resume":
            subparser.add_argument("--monitor-interval-seconds", type=float, default=10)
        for root_name in ("db", "tasks", "cache"):
            subparser.add_argument(f"--{root_name}")
        subparser.set_defaults(func=func)

    evaluate_parser = sub.add_parser("evaluate")
    evaluate_parser.add_argument("campaign_id")
    evaluate_parser.add_argument("--blind-review-file")
    for name in ("db", "tasks", "cache"):
        evaluate_parser.add_argument(f"--{name}")
    evaluate_parser.set_defaults(func=cmd_evaluate)

    export_parser = sub.add_parser("export")
    export_parser.add_argument("campaign_id")
    export_parser.add_argument("--version")
    for name in ("db", "tasks", "cache"):
        export_parser.add_argument(f"--{name}")
    export_parser.set_defaults(func=cmd_export)

    update = sub.add_parser("update-db")
    update.add_argument("campaign_id")
    for name in ("db", "tasks", "cache"):
        update.add_argument(f"--{name}")
    update.set_defaults(func=cmd_update_db)
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
