from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import atomic_write_text, resolve_paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Build catalog.jsonl from model records.")
    parser.add_argument("--db")
    args = parser.parse_args()
    db_root, _, _ = resolve_paths(args.db, None, None)
    records = []
    for path in sorted((db_root / "models").glob("*/records/model.json")):
        model = json.loads(path.read_text(encoding="utf-8"))
        records.append({"record_type": "model", "record_id": model["record_id"], "model_id": model["model_id"], "name": model.get("display_name"), "path": str(path.parent.parent.relative_to(db_root)).replace("\\", "/"), "status": model.get("status"), "modalities": model.get("modalities", [])})
    for path in sorted((db_root / "models").glob("*/records/resources.jsonl")):
        for resource in path.read_text(encoding="utf-8").splitlines():
            if resource.strip():
                item = json.loads(resource)
                records.append({"record_type": "resource", "record_id": item["record_id"], "model_id": item.get("model_id"), "name": item.get("name"), "path": str(path.parent.parent.relative_to(db_root)).replace("\\", "/")})
    output = "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in records)
    atomic_write_text(db_root / "catalog.jsonl", output)
    print(json.dumps({"catalog": str(db_root / "catalog.jsonl"), "records": len(records)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
