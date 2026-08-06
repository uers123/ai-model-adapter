from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Adapter


class MockAdapter(Adapter):
    """Deterministic simulator used to test the orchestration loop.

    It emits synthetic automatic metrics only. It never claims human review,
    never writes model weights, and never touches external resources.
    """

    name = "mock"

    def qualify(self, campaign: dict[str, Any], database_root: Path, cache_root: Path) -> dict[str, Any]:
        return {"qualified": True, "mode": "simulation", "reasons": ["built-in simulator"]}

    def dry_run(self, campaign: dict[str, Any], database_root: Path, cache_root: Path) -> dict[str, Any]:
        return {"status": "ready", "mode": "simulation", "downloads": [], "artifacts": []}

    def run_iteration(self, campaign: dict[str, Any], iteration: int) -> dict[str, Any]:
        progress = min(iteration, 4)
        return {
            "accuracy": round(0.60 + progress * 0.07, 3),
            "f1": round(0.56 + progress * 0.075, 3),
            "endpoint_success_rate": round(0.58 + progress * 0.095, 3),
            "key_case_pass_rate": round(0.68 + progress * 0.07, 3),
            "hallucination_rate": round(max(0.05, 0.20 - progress * 0.04), 3),
            "simulated": True,
        }
