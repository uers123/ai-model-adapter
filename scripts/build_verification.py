from __future__ import annotations

import argparse
import compileall
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import load_yaml, scan_secrets, sha256_file, write_json


FORBIDDEN_WEIGHT_SUFFIXES = {".pth", ".pt", ".bin", ".safetensors", ".ckpt", ".onnx", ".gguf"}
PAYLOAD_CACHE_DIRECTORIES = {"repositories", "models", "datasets", "downloads"}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def add_check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    evidence: Any,
) -> None:
    checks.append({"name": name, "passed": bool(passed), "evidence": evidence})


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        records.append(value)
    return records


def run_json_command(command: list[str]) -> tuple[int, dict[str, Any] | None, str]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    output = completed.stdout.strip()
    data = None
    if output:
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            data = None
    return completed.returncode, data, (completed.stderr or "").strip()


def structured_audit(roots: list[Path]) -> dict[str, Any]:
    counts = {"yaml": 0, "json": 0, "jsonl": 0}
    parse_errors: list[str] = []
    credential_findings: list[str] = []
    for root in roots:
        if not root.exists():
            parse_errors.append(f"missing root: {root}")
            continue
        for path in root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            suffix = path.suffix.lower()
            try:
                values: list[Any] = []
                if suffix in {".yaml", ".yml"}:
                    counts["yaml"] += 1
                    values = [load_yaml(path)]
                elif suffix == ".json":
                    counts["json"] += 1
                    values = [json.loads(path.read_text(encoding="utf-8"))]
                elif suffix == ".jsonl":
                    counts["jsonl"] += 1
                    values = read_jsonl(path)
                else:
                    continue
                for value in values:
                    findings = scan_secrets(value)
                    if findings:
                        credential_findings.append(f"{path}: {findings}")
            except Exception as exc:
                parse_errors.append(f"{path}: {type(exc).__name__}: {exc}")
    return {
        "counts": counts,
        "parse_errors": parse_errors,
        "credential_findings": credential_findings,
    }


def audit_skill(skill_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    skill_md = skill_root / "SKILL.md"
    openai_yaml = skill_root / "agents" / "openai.yaml"
    if not skill_md.exists():
        errors.append("SKILL.md missing")
        skill_text = ""
    else:
        skill_text = skill_md.read_text(encoding="utf-8")
    if not openai_yaml.exists():
        errors.append("agents/openai.yaml missing")
        openai = {}
    else:
        openai = load_yaml(openai_yaml)
    if not skill_text.startswith("---\n"):
        errors.append("SKILL.md frontmatter missing")
    if len(skill_text.splitlines()) > 500:
        errors.append("SKILL.md exceeds 500 lines")
    if re.search(r"\b(?:TODO|TBD)\b", skill_text):
        errors.append("SKILL.md contains placeholders")
    if "Require the exact `/ai-model-adapter` prefix" not in skill_text:
        errors.append("explicit trigger instruction missing")
    if openai.get("policy", {}).get("allow_implicit_invocation") is not False:
        errors.append("implicit invocation is not disabled")
    default_prompt = openai.get("interface", {}).get("default_prompt", "")
    if "$ai-model-adapter" not in default_prompt:
        errors.append("default prompt does not name $ai-model-adapter")

    compile_errors: list[str] = []
    python_files = sorted((skill_root / "scripts").rglob("*.py"))
    for path in python_files:
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except Exception as exc:
            compile_errors.append(f"{path}: {type(exc).__name__}: {exc}")
    errors.extend(compile_errors)

    self_test = subprocess.run(
        [sys.executable, str(skill_root / "scripts" / "self_test.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    if self_test.returncode != 0:
        errors.append(f"self_test failed: {self_test.stderr.strip() or self_test.stdout.strip()}")
    return {
        "valid": not errors,
        "errors": errors,
        "skill_lines": len(skill_text.splitlines()),
        "python_files": len(python_files),
        "self_test_output": self_test.stdout.strip(),
    }


def audit_campaigns(tasks_root: Path, required_campaigns: list[str]) -> dict[str, Any]:
    validator = SCRIPT_DIR / "validate_campaign.py"
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    directories = sorted(path for path in tasks_root.iterdir() if path.is_dir()) if tasks_root.exists() else []
    for directory in directories:
        code, data, stderr = run_json_command(
            [sys.executable, str(validator), directory.name, "--tasks", str(tasks_root)]
        )
        if code != 0 or not data or not data.get("valid"):
            errors.append(f"{directory.name}: {stderr or data}")
        if data:
            records.append(data)
    names = {directory.name for directory in directories}
    missing_required = sorted(set(required_campaigns) - names)
    if missing_required:
        errors.append(f"missing required campaigns: {missing_required}")
    statuses = Counter(str(record.get("status")) for record in records)
    return {
        "valid": not errors,
        "errors": errors,
        "count": len(directories),
        "statuses": dict(sorted(statuses.items())),
        "records": records,
    }


def audit_resources(db_root: Path) -> dict[str, Any]:
    path = db_root / "models" / "NExT-GPT" / "records" / "resources.jsonl"
    resources = read_jsonl(path)
    invalid = [
        record.get("record_id")
        for record in resources
        if record.get("download_policy") != "link-only"
        or not str(record.get("url", "")).startswith(("https://", "http://"))
        or not record.get("checked_at")
        or not record.get("verification_method")
    ]
    return {"valid": not invalid and bool(resources), "count": len(resources), "invalid_records": invalid}


def extract_code_blocks(text: str) -> list[str]:
    return re.findall(r"```[^\n]*\n.*?```", text, flags=re.DOTALL)


def audit_knowledge_chunks(db_root: Path) -> dict[str, Any]:
    model_root = db_root / "models" / "NExT-GPT"
    path = model_root / "records" / "knowledge-chunks.jsonl"
    records = read_jsonl(path)
    errors: list[str] = []
    ids: set[str] = set()
    variants: Counter[str] = Counter()
    chunk_blocks: list[str] = []
    for record in records:
        chunk_id = str(record.get("chunk_id", ""))
        if not chunk_id or chunk_id in ids:
            errors.append(f"duplicate or empty chunk_id: {chunk_id}")
        ids.add(chunk_id)
        variants[str(record.get("variant_id"))] += 1
        content = str(record.get("content_zh", ""))
        if content.lstrip().startswith("---"):
            errors.append(f"frontmatter chunk: {chunk_id}")
        if record.get("title") == "document":
            errors.append(f"generic document title: {chunk_id}")
        if content.count("```") % 2:
            errors.append(f"unbalanced code fence: {chunk_id}")
        contains_code = "```" in content
        if bool(record.get("contains_code_block")) != contains_code:
            errors.append(f"contains_code_block mismatch: {chunk_id}")
        if bool(record.get("contains_complete_code_block")) != (
            contains_code and content.count("```") % 2 == 0
        ):
            errors.append(f"contains_complete_code_block mismatch: {chunk_id}")
        source_file = Path(str(record.get("source_file", "")))
        if not source_file.exists():
            errors.append(f"missing source file: {chunk_id}")
        else:
            location = str(record.get("source_location", ""))
            if not location.startswith("line:"):
                errors.append(f"invalid source location: {chunk_id}")
            else:
                line_number = int(location.split(":", 1)[1])
                source_lines = source_file.read_text(encoding="utf-8").splitlines()
                first_content_line = content.splitlines()[0].strip() if content.splitlines() else ""
                if line_number < 1 or line_number > len(source_lines):
                    errors.append(f"source line out of range: {chunk_id}")
                elif source_lines[line_number - 1].strip() != first_content_line:
                    errors.append(f"source line mismatch: {chunk_id}")
        if not record.get("source_url") and not record.get("source_document"):
            errors.append(f"missing origin reference: {chunk_id}")
        if record.get("source_revision") in {None, "", "local-derived"}:
            errors.append(f"weak source revision: {chunk_id}")
        chunk_blocks.extend(extract_code_blocks(content))

    document_blocks: list[str] = []
    for document in sorted((model_root / "documents").glob("*.md")):
        document_blocks.extend(extract_code_blocks(document.read_text(encoding="utf-8")))
    missing_blocks = Counter(document_blocks) - Counter(chunk_blocks)
    extra_blocks = Counter(chunk_blocks) - Counter(document_blocks)
    if missing_blocks:
        errors.append(f"missing code blocks: {sum(missing_blocks.values())}")
    if extra_blocks:
        errors.append(f"extra code blocks: {sum(extra_blocks.values())}")
    required_variants = {"shared", "official-current", "legacy-chapter8"}
    if not required_variants.issubset(variants):
        errors.append(f"missing variants: {sorted(required_variants - set(variants))}")
    return {
        "valid": not errors,
        "errors": errors,
        "count": len(records),
        "unique_ids": len(ids),
        "variants": dict(sorted(variants.items())),
        "document_code_blocks": len(document_blocks),
        "chunk_code_blocks": len(chunk_blocks),
    }


def audit_catalog(db_root: Path) -> dict[str, Any]:
    records = read_jsonl(db_root / "catalog.jsonl")
    catalog_models = {
        str(record.get("model_id"))
        for record in records
        if record.get("record_type") == "model"
    }
    directory_models = {
        directory.name
        for directory in (db_root / "models").iterdir()
        if directory.is_dir() and (directory / "records" / "model.json").exists()
    }
    return {
        "valid": catalog_models == directory_models,
        "catalog_models": sorted(catalog_models),
        "directory_models": sorted(directory_models),
        "records": len(records),
    }


def verify_manifest_files(root: Path, entries: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for entry in entries:
        relative = str(entry["relative_path"]).replace("/", "\\")
        path = root / relative
        if not path.exists():
            errors.append(f"missing: {relative}")
            continue
        if path.stat().st_size != int(entry["size_bytes"]):
            errors.append(f"size: {relative}")
            continue
        if sha256_file(path) != str(entry["sha256"]):
            errors.append(f"sha256: {relative}")
    return errors


def audit_sources(
    db_root: Path,
    old_source: Path,
    expect_old_source: str,
) -> dict[str, Any]:
    source_root = db_root / "models" / "NExT-GPT" / "sources" / "chapter8"
    manifest_path = source_root / "source-manifest.yaml"
    manifest = load_yaml(manifest_path)
    original_entries = list(manifest.get("original_files", []))
    derived_entries = list(manifest.get("derived_files", []))
    target_errors = verify_manifest_files(source_root, original_entries)
    derived_errors = verify_manifest_files(source_root, derived_entries)
    old_exists = old_source.exists()
    old_errors: list[str] = []
    if expect_old_source == "present":
        if not old_exists:
            old_errors.append("old source is absent")
        else:
            old_errors.extend(verify_manifest_files(old_source, original_entries))
    elif old_exists:
        old_errors.append("old source still exists")

    pdf_path = source_root / "mllms.pdf"
    notebook_path = source_root / "mllms.ipynb"
    visual_audit_path = source_root / "pdf-visual-audit.json"
    try:
        from pypdf import PdfReader

        pdf_pages = len(PdfReader(str(pdf_path)).pages)
    except Exception as exc:
        pdf_pages = -1
        target_errors.append(f"PDF page inspection failed: {type(exc).__name__}: {exc}")
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    notebook_cells = len(notebook.get("cells", []))
    expected_pdf_pages = next(
        (int(item.get("page_count", -1)) for item in derived_entries if item.get("source_file") == "mllms.pdf"),
        -1,
    )
    expected_notebook_cells = next(
        (int(item.get("cell_count", -1)) for item in derived_entries if item.get("source_file") == "mllms.ipynb"),
        -1,
    )
    if pdf_pages != expected_pdf_pages:
        target_errors.append(f"PDF pages: expected {expected_pdf_pages}, got {pdf_pages}")
    if notebook_cells != expected_notebook_cells:
        target_errors.append(
            f"Notebook cells: expected {expected_notebook_cells}, got {notebook_cells}"
        )
    if not visual_audit_path.exists():
        visual_audit = {}
        target_errors.append("PDF visual audit record is missing")
    else:
        visual_audit = json.loads(visual_audit_path.read_text(encoding="utf-8"))
        if visual_audit.get("source_sha256") != sha256_file(pdf_path):
            target_errors.append("PDF visual audit source hash mismatch")
        if int(visual_audit.get("rendered_pages", -1)) != pdf_pages:
            target_errors.append("PDF visual audit page count mismatch")
        if visual_audit.get("all_contact_sheets_inspected") is not True:
            target_errors.append("PDF contact sheets were not fully inspected")
        if visual_audit.get("result") != "passed":
            target_errors.append("PDF visual audit did not pass")
    return {
        "valid": not target_errors and not derived_errors and not old_errors,
        "source_root": str(source_root),
        "old_source": str(old_source),
        "old_source_exists": old_exists,
        "expected_old_source": expect_old_source,
        "original_files": len(original_entries),
        "derived_files": len(derived_entries),
        "target_errors": target_errors,
        "derived_errors": derived_errors,
        "old_errors": old_errors,
        "pdf_pages": pdf_pages,
        "notebook_cells": notebook_cells,
        "pdf_visual_audit": visual_audit,
    }


def audit_storage(db_root: Path, tasks_root: Path, cache_root: Path) -> dict[str, Any]:
    database_weights = [
        str(path)
        for path in db_root.rglob("*")
        if path.is_file() and path.suffix.lower() in FORBIDDEN_WEIGHT_SUFFIXES
    ]
    task_weights = [
        str(path)
        for path in tasks_root.rglob("*")
        if path.is_file() and path.suffix.lower() in FORBIDDEN_WEIGHT_SUFFIXES
    ]
    cache_payloads: list[str] = []
    for directory_name in PAYLOAD_CACHE_DIRECTORIES:
        directory = cache_root / directory_name
        if directory.exists():
            cache_payloads.extend(
                str(path)
                for path in directory.rglob("*")
                if path.is_file() and path.name != ".gitkeep"
            )
    return {
        "valid": not database_weights and not task_weights and not cache_payloads,
        "database_weight_files": database_weights,
        "task_weight_files": task_weights,
        "cache_payload_files": cache_payloads,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the complete ai-model-adapter build.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--skill", required=True, type=Path)
    parser.add_argument("--old-source", required=True, type=Path)
    parser.add_argument("--expect-old-source", choices=("present", "absent"), required=True)
    parser.add_argument("--required-campaign", action="append", default=[])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    db_root = args.db.resolve()
    tasks_root = args.tasks.resolve()
    cache_root = args.cache.resolve()
    skill_root = args.skill.resolve()
    old_source = args.old_source.resolve()
    checks: list[dict[str, Any]] = []

    database_code, database_data, database_stderr = run_json_command(
        [sys.executable, str(skill_root / "scripts" / "validate_database.py"), "--db", str(db_root)]
    )
    add_check(
        checks,
        "database_validation",
        database_code == 0 and bool(database_data and database_data.get("valid")),
        database_data or database_stderr,
    )

    skill = audit_skill(skill_root)
    add_check(checks, "skill_validation", skill["valid"], skill)

    campaigns = audit_campaigns(tasks_root, args.required_campaign)
    add_check(checks, "campaign_validation", campaigns["valid"], campaigns)

    structured = structured_audit([db_root, tasks_root, skill_root])
    add_check(
        checks,
        "structured_and_credential_scan",
        not structured["parse_errors"] and not structured["credential_findings"],
        structured,
    )

    resources = audit_resources(db_root)
    add_check(checks, "external_resources_link_only", resources["valid"], resources)

    chunks = audit_knowledge_chunks(db_root)
    add_check(checks, "semantic_knowledge_chunks", chunks["valid"], chunks)

    catalog = audit_catalog(db_root)
    add_check(checks, "catalog_model_consistency", catalog["valid"], catalog)

    sources = audit_sources(db_root, old_source, args.expect_old_source)
    add_check(checks, "source_migration", sources["valid"], sources)

    storage = audit_storage(db_root, tasks_root, cache_root)
    add_check(checks, "storage_policy", storage["valid"], storage)

    documents = sorted((db_root / "models" / "NExT-GPT" / "documents").glob("*.md"))
    add_check(
        checks,
        "beginner_manual",
        len(documents) == 11,
        {"count": len(documents), "files": [path.name for path in documents]},
    )

    failures = [check["name"] for check in checks if not check["passed"]]
    report = {
        "verification_id": "ai-model-adapter-build-v1",
        "generated_at": now_utc(),
        "valid": not failures,
        "phase": f"old-source-{args.expect_old_source}",
        "paths": {
            "database": str(db_root),
            "tasks": str(tasks_root),
            "cache": str(cache_root),
            "skill": str(skill_root),
            "old_source": str(old_source),
        },
        "checks": checks,
        "failures": failures,
    }
    write_json(report, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
