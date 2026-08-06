from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import campaign_path, load_current, resolve_paths, utc_now, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a safe cleanup plan; optionally move named paths to recycle-bin.")
    parser.add_argument("campaign_id")
    parser.add_argument("--tasks")
    parser.add_argument("--move", nargs="*", default=[])
    args = parser.parse_args()
    _, tasks_root, _ = resolve_paths(None, args.tasks, None)
    directory = campaign_path(tasks_root, args.campaign_id)
    current = load_current(directory)
    keep = {"final", "status", "evaluations", "memory", "logs", "reports", "campaign.yaml"}
    protected_files = {
        str(Path(value).resolve())
        for value in (current.get("best_checkpoint"), current.get("last_checkpoint"))
        if value
    }
    candidates = []
    for relative in args.move:
        source = (directory / relative).resolve()
        if source == directory or directory not in source.parents:
            raise ValueError(f"Refusing path outside campaign: {relative}")
        relative_path = Path(relative)
        protected = (relative_path.parts and relative_path.parts[0] in keep) or str(source) in protected_files
        if source.exists() and not protected and source.name not in keep:
            candidates.append({"relative_path": relative, "bytes": source.stat().st_size if source.is_file() else None})
    plan = {"campaign_id": args.campaign_id, "created_at": utc_now(), "status": "proposed", "keep": sorted(keep), "protected_checkpoints": sorted(protected_files), "candidates": candidates, "reversible": True}
    write_json(plan, directory / "cleanup-plan.json")
    if args.move:
        recycle = directory / "recycle-bin"
        for item in candidates:
            source = directory / item["relative_path"]
            target = recycle / Path(item["relative_path"]).name
            if target.exists():
                target = recycle / f"{target.stem}-{utc_now().replace(':','')}{target.suffix}"
            shutil.move(str(source), str(target))
        plan["status"] = "moved_to_recycle_bin"
        write_json(plan, directory / "cleanup-plan.json")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
