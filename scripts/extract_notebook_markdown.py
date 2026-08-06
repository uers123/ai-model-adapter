from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def rewrite_relative_links(markdown: str, base_url: str | None) -> str:
    if not base_url:
        return markdown

    def replace(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        clean = target.strip()
        if clean.startswith(("http://", "https://", "#", "mailto:", "assets/")):
            return match.group(0)
        normalized = clean.removeprefix("./").replace("\\", "/")
        return f"[{label}]({base_url.rstrip('/')}/{normalized})"

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace, markdown)


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive Markdown from a Jupyter Notebook without altering code.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--base-url")
    args = parser.parse_args()
    notebook = json.loads(args.source.read_text(encoding="utf-8"))
    sections = [
        "---",
        f"source_file: {args.source.name}",
        f"source_sha256: {args.source_sha256}",
        "derivation: notebook-cell-preserving-markdown",
        "checked_at: 2026-08-02",
        "---",
        "",
        "# Notebook 派生资料",
        "",
        "> 保持单元顺序和代码原文；Markdown 单元作为中文资料保留，代码单元不翻译。",
    ]
    for index, cell in enumerate(notebook.get("cells", []), start=1):
        cell_type = cell.get("cell_type", "unknown")
        source = "".join(cell.get("source", []))
        sections.extend(["", f"## 单元 {index}: `{cell_type}`", ""])
        if cell_type == "code":
            sections.extend(["```python", source.rstrip(), "```"])
        else:
            sections.append(rewrite_relative_links(source.rstrip(), args.base_url))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(sections) + "\n", encoding="utf-8", newline="\n")
    print(f"cells={len(notebook.get('cells', []))} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
