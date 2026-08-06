from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from common import (
    confidence_intervals_meet_targets,
    ensure_campaign_workspace,
    load_current,
    save_campaign,
    scan_secrets,
    write_json,
)
from chunk_documents import parse_markdown_document, split_sections
import cli


def test_confidence_interval_targets() -> None:
    targets = {"accuracy": 0.80, "hallucination_rate": 0.10}
    assert confidence_intervals_meet_targets(
        targets,
        {"accuracy": [0.80, 0.86], "hallucination_rate": [0.04, 0.10]},
    )
    assert not confidence_intervals_meet_targets(
        targets,
        {"accuracy": [0.79, 0.86], "hallucination_rate": [0.04, 0.10]},
    )
    assert not confidence_intervals_meet_targets(
        targets,
        {"accuracy": [0.80, 0.86], "hallucination_rate": [0.04, 0.11]},
    )
    assert not confidence_intervals_meet_targets(targets, {"accuracy": [0.80, 0.86]})


def test_next_gpt_never_enters_real_supervisor() -> None:
    with tempfile.TemporaryDirectory(prefix="ai-model-adapter-self-test-") as temporary:
        root = Path(temporary)
        tasks = root / "tasks"
        database = root / "database"
        cache = root / "cache"
        campaign_id = "next-gpt-dry-run-guard"
        directory = tasks / campaign_id
        ensure_campaign_workspace(directory)
        campaign = {
            "campaign_id": campaign_id,
            "model_id": "NExT-GPT",
            "variant_id": "official-current",
            "acceptance": {"baseline_metrics": {"answer_accuracy": 0.50}},
            "authorization": {
                "budget": {
                    "max_iterations": 1,
                    "max_total_gpu_hours": 1.0,
                    "max_disk_usage_gb": 1.0,
                    "max_single_iteration_hours": 1.0,
                    "no_improvement_patience": 1,
                    "minimum_effective_improvement": 0.01,
                    "allowed_adaptation_methods": ["inference"],
                    "allow_partial_unfreeze": False,
                    "allow_full_finetuning": False,
                }
            },
            "status": "authorized",
        }
        save_campaign(directory, campaign)
        write_json(
            {
                "campaign_id": campaign_id,
                "status": "authorized",
                "current_iteration": 0,
                "acceptance_met": False,
            },
            directory / "status" / "current.json",
        )

        ready_adapter = Mock()
        ready_adapter.name = "next-gpt"
        ready_adapter.dry_run.return_value = {
            "status": "ready",
            "mode": "dry-run",
            "downloads": [],
            "weights_created": False,
            "metrics_created": False,
        }
        args = SimpleNamespace(
            campaign_id=campaign_id,
            db=str(database),
            tasks=str(tasks),
            cache=str(cache),
            real_training=True,
            monitor_interval_seconds=0.1,
            foreground=False,
        )
        with patch.object(cli, "adapter_for", return_value=ready_adapter), patch.object(
            cli.subprocess,
            "Popen",
        ) as popen:
            assert cli.cmd_start(args) == 0
            popen.assert_not_called()

        current = load_current(directory)
        assert current["status"] == "blocked"
        assert current["stop_reason"] == "next_gpt_adapter_dry_run_only"
        report = json.loads((directory / "reports" / "next-gpt-dry-run.json").read_text(encoding="utf-8"))
        assert report["real_training_requested"] is True
        assert report["real_training_supported"] is False


def test_semantic_chunks_exclude_frontmatter() -> None:
    source = """---
model_id: NExT-GPT
variant_id: official-current
source_revision: fixed-revision
checked_at: 2026-08-02
---

# Training

Keep the semantic section together.

```bash
python train.py
```
"""
    metadata, body, line_offset = parse_markdown_document(source)
    assert metadata["variant_id"] == "official-current"
    assert not body.lstrip().startswith("---")
    sections = split_sections(body, line_offset=line_offset, default_title="fixture")
    assert len(sections) == 1
    title, content, line_start = sections[0]
    assert title == "Training"
    assert line_start == 8
    assert content.count("```") == 2


def test_credential_scan_distinguishes_regression_names() -> None:
    assert scan_secrets({"regression_results": {"no_secret_leakage": True}}) == []
    assert scan_secrets({"api_key": "example"}) == ["api_key"]
    assert scan_secrets({"service_access_token": "example"}) == ["service_access_token"]


def test_unwatch_reconciles_stale_monitor() -> None:
    with tempfile.TemporaryDirectory(prefix="ai-model-adapter-monitor-test-") as temporary:
        tasks = Path(temporary) / "tasks"
        campaign_id = "stale-monitor-campaign"
        directory = tasks / campaign_id
        ensure_campaign_workspace(directory)
        write_json(
            {"campaign_id": campaign_id, "status": "evaluating"},
            directory / "status" / "current.json",
        )
        write_json(
            {"campaign_id": campaign_id, "pid": 2147483647, "status": "watching"},
            directory / "status" / "monitor.json",
        )
        write_json(
            {"campaign_id": campaign_id, "registered": True},
            directory / "status" / "watch.json",
        )
        args = SimpleNamespace(
            campaign_id=campaign_id,
            db=None,
            tasks=str(tasks),
            cache=None,
        )
        assert cli.cmd_unwatch(args) == 0
        monitor = json.loads(
            (directory / "status" / "monitor.json").read_text(encoding="utf-8")
        )
        assert monitor["status"] == "unwatched"
        assert monitor["stale_process_reconciled"] is True
        assert not (directory / "status" / "watch.json").exists()
        assert not (directory / "status" / "unwatch.request").exists()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic safety checks for ai-model-adapter.")
    parser.parse_args()
    tests = [
        test_confidence_interval_targets,
        test_next_gpt_never_enters_real_supervisor,
        test_semantic_chunks_exclude_frontmatter,
        test_credential_scan_distinguishes_regression_names,
        test_unwatch_reconciles_stale_monitor,
    ]
    for test in tests:
        test()
        print(f"[pass] {test.__name__}")
    print(f"self_test_passed={len(tests)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
