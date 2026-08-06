from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import load_yaml, resolve_paths, scan_secrets


def validate_json_schema(instance: object, schema_path: Path, errors: list[str]) -> None:
    try:
        import jsonschema
    except ImportError:
        errors.append("jsonschema is unavailable; install it before schema validation")
        return
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance, schema)
    except Exception as exc:
        errors.append(f"{schema_path.name}: {exc}")


def check_markdown_links(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count("```") % 2:
        errors.append(f"unclosed code fence: {path}")
    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)|\[[^\]]+\]\(([^)]+)\)", text):
        target = match.group(1) or match.group(2)
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        target_path = (path.parent / target.split("#", 1)[0]).resolve()
        if target_path and not target_path.exists():
            errors.append(f"missing local link: {path} -> {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the AI training model database.")
    parser.add_argument("--db")
    args = parser.parse_args()
    db_root, _, _ = resolve_paths(args.db, None, None)
    errors: list[str] = []
    counts = {"yaml": 0, "json": 0, "jsonl": 0, "markdown": 0, "schemas": 0}
    if not db_root.exists():
        errors.append(f"database root does not exist: {db_root}")
    for path in db_root.rglob("*") if db_root.exists() else []:
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        try:
            if suffix in {".yaml", ".yml"}:
                data = load_yaml(path)
                counts["yaml"] += 1
                if scan_secrets(data):
                    errors.append(f"secret-like YAML field: {path}")
                schema_name = {
                    "family.yaml": "model-family.schema.json",
                    "variant.yaml": "model-variant.schema.json",
                }.get(path.name)
                if schema_name and (db_root / "schemas" / schema_name).exists():
                    validate_json_schema(data, db_root / "schemas" / schema_name, errors)
            elif suffix == ".json":
                data = json.loads(path.read_text(encoding="utf-8"))
                counts["json"] += 1
                if scan_secrets(data):
                    errors.append(f"secret-like JSON field: {path}")
                schema_path = db_root / "schemas" / {"model.json": "model-family.schema.json"}.get(path.name, "")
                if schema_path.exists() and path.name == "model.json":
                    validate_json_schema(data, schema_path, errors)
            elif suffix == ".jsonl":
                counts["jsonl"] += 1
                for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if scan_secrets(item):
                        errors.append(f"secret-like JSONL field: {path}:{line_number}")
                    schema_name = {
                        "catalog.jsonl": None,
                        "resources.jsonl": "resource-record.schema.json",
                        "knowledge-chunks.jsonl": "knowledge-chunk.schema.json",
                        "evaluations.jsonl": "evaluation-record.schema.json",
                        "training.jsonl": "campaign-summary.schema.json",
                        "verified-lessons.jsonl": "verified-lesson.schema.json",
                    }.get(path.name)
                    if schema_name and (db_root / "schemas" / schema_name).exists():
                        validate_json_schema(item, db_root / "schemas" / schema_name, errors)
            elif suffix == ".md":
                counts["markdown"] += 1
                check_markdown_links(path, errors)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    for schema in (db_root / "schemas").glob("*.json") if (db_root / "schemas").exists() else []:
        counts["schemas"] += 1
        try:
            json.loads(schema.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid schema {schema}: {exc}")
    forbidden = {".pth", ".pt", ".bin", ".safetensors", ".ckpt", ".onnx", ".gguf"}
    for path in db_root.rglob("*") if db_root.exists() else []:
        if path.is_file() and path.suffix.lower() in forbidden:
            errors.append(f"model weight found in database (forbidden): {path}")
    result = {"database": str(db_root), "counts": counts, "errors": errors, "valid": not errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
