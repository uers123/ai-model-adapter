from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class Adapter(ABC):
    """Small hook surface shared by real adapters and the deterministic mock."""

    name = "base"

    @abstractmethod
    def qualify(self, campaign: dict[str, Any], database_root: Path, cache_root: Path) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def dry_run(self, campaign: dict[str, Any], database_root: Path, cache_root: Path) -> dict[str, Any]:
        raise NotImplementedError

    def run_iteration(self, campaign: dict[str, Any], iteration: int) -> dict[str, Any]:
        raise RuntimeError(f"{self.name} does not implement real training")

