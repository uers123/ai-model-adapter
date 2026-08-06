"""Shared local-first helpers for ai-model-adapter.

The module intentionally uses only the Python standard library plus PyYAML
when YAML files are read. It never downloads data and redacts secrets before
writing any campaign artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover - a clear error is better than a silent fallback
    yaml = None

DB_ENV = "AI_MODEL_ADAPTER_DB"
TASKS_ENV = "AI_MODEL_ADAPTER_TASKS"
CACHE_ENV = "AI_MODEL_ADAPTER_CACHE"

DEFAULT_DB = Path(os.getenv(DB_ENV, r"D:\github-neirong\AI训练开源模型"))
DEFAULT_TASKS = Path(os.getenv(TASKS_ENV, r"D:\github-neirong\AI模型特调任务"))
DEFAULT_CACHE = Path(os.getenv(CACHE_ENV, r"D:\github-neirong\AI模型基础资源"))

SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|passwd|secret|private[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)https?://[^ \n]+[?&](token|signature|sig|key)="),
)

ALLOWED_STATES = {
    "awaiting_authorization",
    "authorized",
    "running",
    "pausing",
    "paused",
    "evaluating",
    "completed",
    "blocked",
    "failed",
    "stopped",
}

LOWER_IS_BETTER_METRICS = {
    "hallucination_rate",
    "wer",
    "edit_distance",
    "false_positive_rate",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_paths(db: str | None = None, tasks: str | None = None, cache: str | None = None) -> tuple[Path, Path, Path]:
    return (
        Path(db or os.getenv(DB_ENV, str(DEFAULT_DB))).expanduser(),
        Path(tasks or os.getenv(TASKS_ENV, str(DEFAULT_TASKS))).expanduser(),
        Path(cache or os.getenv(CACHE_ENV, str(DEFAULT_CACHE)).strip()).expanduser(),
    )


def require_yaml() -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML is required to read campaign/database YAML. Install PyYAML in the active Python environment.")
    return yaml


def load_yaml(path: Path) -> dict[str, Any]:
    parser = require_yaml()
    with path.open("r", encoding="utf-8") as handle:
        data = parser.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML object: {path}")
    return data


def dump_yaml(data: dict[str, Any], path: Path) -> None:
    parser = require_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = parser.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    atomic_write_text(path, text)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def write_json(data: Any, path: Path) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = redact(data)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(safe, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object")
            records.append(value)
    return records


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): redact(item) for key, item in value.items() if not looks_secret_key(str(key))}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        result = value
        for pattern in SECRET_PATTERNS:
            result = pattern.sub("[REDACTED]", result)
        return result
    return value


def looks_secret_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    exact = {
        "api_key",
        "apikey",
        "token",
        "access_token",
        "auth_token",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "private_key",
    }
    sensitive_suffixes = (
        "_api_key",
        "_access_token",
        "_auth_token",
        "_password",
        "_passwd",
        "_client_secret",
        "_private_key",
    )
    return normalized in exact or normalized.endswith(sensitive_suffixes)


def scan_secrets(value: Any) -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if looks_secret_key(str(key)):
                findings.append(str(key))
            findings.extend(scan_secrets(item))
    elif isinstance(value, list):
        for item in value:
            findings.extend(scan_secrets(item))
    elif isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            if pattern.search(value):
                findings.append("value-pattern")
    return sorted(set(findings))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def integrity_snapshot(campaign_dir: Path) -> dict[str, Any]:
    """Hash immutable/recoverable campaign inputs at a safe point."""
    candidates: list[Path] = [campaign_dir / "campaign.yaml"]
    for directory_name in ("source-code", "data-manifests", "configs", "scripts"):
        directory = campaign_dir / directory_name
        if directory.exists():
            candidates.extend(path for path in directory.rglob("*") if path.is_file())
    current = load_current(campaign_dir) if current_path(campaign_dir).exists() else {}
    best_checkpoint = current.get("best_checkpoint")
    if best_checkpoint:
        checkpoint = Path(best_checkpoint)
        if checkpoint.exists():
            candidates.append(checkpoint)
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(set(candidates)):
        if path.exists() and path.is_file():
            relative = str(path.resolve().relative_to(campaign_dir.resolve())).replace("\\", "/")
            files[relative] = {"size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
    return {"created_at": utc_now(), "files": files}


def verify_integrity_snapshot(campaign_dir: Path, snapshot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = snapshot.get("files", {})
    for relative, metadata in expected.items():
        path = (campaign_dir / relative).resolve()
        if campaign_dir.resolve() not in path.parents:
            errors.append(f"path escaped campaign: {relative}")
            continue
        if not path.exists():
            errors.append(f"missing: {relative}")
            continue
        if path.stat().st_size != metadata.get("size_bytes"):
            errors.append(f"size changed: {relative}")
            continue
        if sha256_file(path) != metadata.get("sha256"):
            errors.append(f"hash changed: {relative}")
    return errors


def campaign_path(tasks_root: Path, campaign_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,79}", campaign_id):
        raise ValueError("campaign_id must contain 2-80 ASCII letters, digits, '.', '_' or '-'.")
    root = tasks_root.resolve()
    target = (root / campaign_id).resolve()
    if target.parent != root:
        raise ValueError("campaign_id escaped the task root")
    return target


def model_record(db_root: Path, model_id: str) -> dict[str, Any]:
    candidates = [
        db_root / "models" / model_id / "records" / "model.json",
        db_root / "models" / model_id / "model.json",
    ]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"No model record found for model_id={model_id!r} under {db_root}")


def ensure_campaign_workspace(path: Path) -> None:
    for name in (
        "source-code",
        "data-manifests/train",
        "data-manifests/validation",
        "data-manifests/final_blind_test",
        "configs",
        "scripts",
        "checkpoints",
        "adapters",
        "evaluations",
        "status",
        "memory",
        "logs",
        "reports",
        "recycle-bin",
        "final",
    ):
        (path / name).mkdir(parents=True, exist_ok=True)


def current_path(campaign_dir: Path) -> Path:
    return campaign_dir / "status" / "current.json"


def load_campaign(campaign_dir: Path) -> dict[str, Any]:
    return load_yaml(campaign_dir / "campaign.yaml")


def save_campaign(campaign_dir: Path, campaign: dict[str, Any]) -> None:
    campaign["updated_at"] = utc_now()
    dump_yaml(campaign, campaign_dir / "campaign.yaml")


def load_current(campaign_dir: Path) -> dict[str, Any]:
    path = current_path(campaign_dir)
    if not path.exists():
        raise FileNotFoundError(f"Missing authoritative state: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def set_current(campaign_dir: Path, updates: dict[str, Any], event: str | None = None) -> dict[str, Any]:
    current = load_current(campaign_dir) if current_path(campaign_dir).exists() else {}
    current.update(updates)
    current["updated_at"] = utc_now()
    write_json(current, current_path(campaign_dir))
    if event:
        append_jsonl(campaign_dir / "status" / "history.jsonl", {"timestamp": current["updated_at"], "event": event, "state": current})
    return current


def heartbeat(campaign_dir: Path, metrics: dict[str, Any] | None = None, note: str = "") -> dict[str, Any]:
    current = load_current(campaign_dir)
    current["heartbeat_at"] = utc_now()
    current["system_metrics"] = collect_system_metrics(campaign_dir)
    if metrics:
        current.setdefault("current_metrics", {}).update(metrics)
    if note:
        current["last_note"] = note
    write_json(current, current_path(campaign_dir))
    append_jsonl(campaign_dir / "status" / "history.jsonl", {"timestamp": current["heartbeat_at"], "event": "heartbeat", "metrics": metrics or {}, "note": note})
    progress = campaign_dir / "reports" / "live-progress.md"
    lines = [
        "# Live Progress",
        "",
        f"- Last heartbeat: {current['heartbeat_at']}",
        f"- State: `{current.get('status')}`",
        f"- Iteration: {current.get('current_iteration', 0)}",
        f"- Best metrics: `{json.dumps(current.get('best_metrics', {}), ensure_ascii=False)}`",
        f"- Current metrics: `{json.dumps(current.get('current_metrics', {}), ensure_ascii=False)}`",
        f"- System metrics: `{json.dumps(current.get('system_metrics', {}), ensure_ascii=False)}`",
        f"- Note: {current.get('last_note', '')}",
    ]
    atomic_write_text(progress, "\n".join(lines) + "\n")
    return current


def collect_system_metrics(campaign_dir: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(campaign_dir)
    result: dict[str, Any] = {
        "disk_free_gb": round(usage.free / (1024**3), 3),
        "disk_total_gb": round(usage.total / (1024**3), 3),
        "gpu": [],
    }
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        result["gpu_status"] = "unavailable"
        return result
    try:
        completed = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=index,name,utilization.gpu,temperature.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        for line in completed.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) == 6:
                result["gpu"].append(
                    {
                        "index": int(parts[0]),
                        "name": parts[1],
                        "utilization_percent": float(parts[2]),
                        "temperature_c": float(parts[3]),
                        "memory_used_mb": float(parts[4]),
                        "memory_total_mb": float(parts[5]),
                    }
                )
        result["gpu_status"] = "ok"
    except Exception as exc:
        result["gpu_status"] = f"unavailable: {type(exc).__name__}"
    return result


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def metric_improvement(current: dict[str, float], previous: dict[str, float]) -> float:
    improvements = []
    for key, value in current.items():
        if isinstance(value, (int, float)) and isinstance(previous.get(key), (int, float)):
            if "error" in key or key in {"wer", "hallucination_rate", "false_positive_rate", "edit_distance"}:
                improvements.append(float(previous[key]) - float(value))
            elif "rate" in key or key.endswith("accuracy") or key in {"accuracy", "f1", "precision", "recall", "map"}:
                improvements.append(float(value) - float(previous[key]))
    return max(improvements, default=0.0)


def confidence_intervals_meet_targets(
    targets: dict[str, float],
    intervals: dict[str, Any],
) -> bool:
    """Return True only when every interval supports its acceptance target."""
    if not targets:
        return False
    for name, target in targets.items():
        bounds = intervals.get(name)
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            return False
        try:
            lower, upper = float(bounds[0]), float(bounds[1])
            target_value = float(target)
        except (TypeError, ValueError):
            return False
        if lower > upper:
            return False
        if name in LOWER_IS_BETTER_METRICS:
            if upper > target_value:
                return False
        elif lower < target_value:
            return False
    return True


def status_is_terminal(status: str) -> bool:
    return status in {"completed", "blocked", "failed", "stopped"}


def process_is_running(pid: Any) -> bool:
    try:
        process_id = int(pid)
    except (TypeError, ValueError):
        return False
    if process_id <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, process_id)
        if not handle:
            return ctypes.get_last_error() == 5
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def copytree_if_exists(source: Path, target: Path) -> None:
    if source.exists():
        shutil.copytree(source, target, dirs_exist_ok=True)


def human_duration(seconds: float) -> str:
    return f"{seconds / 3600:.2f}h"
