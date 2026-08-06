from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import atomic_write_text, require_yaml, utc_now


def parse_markdown_document(text: str) -> tuple[dict, str, int]:
    """Remove YAML frontmatter and return metadata, body, and original line offset."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, 0
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing_index is None:
        raise ValueError("Markdown frontmatter is not closed")
    metadata = require_yaml().safe_load("\n".join(lines[1:closing_index])) or {}
    if not isinstance(metadata, dict):
        raise ValueError("Markdown frontmatter must be a YAML object")
    return metadata, "\n".join(lines[closing_index + 1 :]), closing_index + 1


def split_sections(
    text: str,
    *,
    line_offset: int = 0,
    default_title: str = "document",
) -> list[tuple[str, str, int]]:
    lines = text.splitlines()
    sections, title, body, start = [], default_title, [], 1 + line_offset
    in_code = False
    for index, line in enumerate(lines, start=1 + line_offset):
        if line.strip().startswith("```"):
            in_code = not in_code
        if not in_code and re.match(r"^#{1,6}\s+", line):
            prior_content = "\n".join(body).strip()
            if prior_content:
                sections.append((title, prior_content, start))
            title = re.sub(r"^#+\s+", "", line).strip()
            body = [line]
            start = index
        else:
            body.append(line)
    final_content = "\n".join(body).strip()
    if final_content:
        sections.append((title, final_content, start))
    return sections


def main() -> int:
    parser = argparse.ArgumentParser(description="Split Markdown by semantic headings without breaking code fences.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--variant-id", required=True)
    args = parser.parse_args()
    sources = [args.source] if args.source.is_file() else sorted(args.source.rglob("*.md"))
    chunks = []
    ordinal = 0
    for source in sources:
        source_text = source.read_text(encoding="utf-8")
        metadata, body_text, line_offset = parse_markdown_document(source_text)
        model_id = str(metadata.get("model_id") or args.model_id)
        variant_id = str(metadata.get("variant_id") or args.variant_id)
        source_revision = str(metadata.get("source_revision") or "local-derived")
        checked_at = str(metadata.get("checked_at") or utc_now()[:10])
        for title, content, line_start in split_sections(
            body_text,
            line_offset=line_offset,
            default_title=source.stem,
        ):
            if len(content.strip()) < 20:
                continue
            ordinal += 1
            digest = hashlib.sha1(f"{source}:{variant_id}:{line_start}:{title}".encode("utf-8")).hexdigest()[:12]
            item = {
                "chunk_id": f"{model_id.lower()}-{variant_id}-{digest}",
                "record_type": "knowledge_chunk",
                "model_id": model_id,
                "variant_id": variant_id,
                "ordinal": ordinal,
                "title": title,
                "content_zh": content,
                "source_file": str(source),
                "source_location": f"line:{line_start}",
                "source_revision": source_revision,
                "checked_at": checked_at,
                "confidence": "source-derived",
                "contains_code_block": "```" in content,
                "contains_complete_code_block": "```" in content and content.count("```") % 2 == 0,
                "code_fences_balanced": content.count("```") % 2 == 0,
            }
            if metadata.get("source_file"):
                item["source_document"] = str(metadata["source_file"])
            if metadata.get("source_url"):
                item["source_url"] = str(metadata["source_url"])
            if metadata.get("topic"):
                item["topic"] = str(metadata["topic"])
            chunks.append(item)
    atomic_write_text(args.output, "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in chunks))
    print(json.dumps({"output": str(args.output), "chunks": len(chunks), "source": str(args.source)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
