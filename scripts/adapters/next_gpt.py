from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Adapter


class NextGPTAdapter(Adapter):
    """NExT-GPT qualification and no-weight dry-run adapter."""

    name = "next-gpt"

    def qualify(self, campaign: dict[str, Any], database_root: Path, cache_root: Path) -> dict[str, Any]:
        record = campaign.get("qualification_snapshot", {})
        required = record.get("required_resources", [])
        missing = []
        for resource in required:
            local_path = resource.get("local_path")
            if local_path and not Path(local_path).exists():
                missing.append({"resource_id": resource.get("resource_id"), "local_path": local_path})
        return {
            "qualified": bool(record.get("training_entrypoints")) and not missing,
            "mode": "dry-run-only" if missing else "resource-ready",
            "missing_resources": missing,
            "reasons": ["official training is Bash/DeepSpeed and resource paths are not present"] if missing else [],
        }

    def dry_run(self, campaign: dict[str, Any], database_root: Path, cache_root: Path) -> dict[str, Any]:
        qualification = self.qualify(campaign, database_root, cache_root)
        return {
            "status": "blocked" if qualification["missing_resources"] else "ready",
            "mode": "dry-run",
            "real_training_supported": False,
            "qualification": qualification,
            "variant_id": campaign.get("variant_id"),
            "source_revision": campaign.get("source_revision"),
            "planned_stages": campaign.get("qualification_snapshot", {}).get("training_entrypoints", []),
            "downloads": [],
            "weights_created": False,
            "metrics_created": False,
        }
