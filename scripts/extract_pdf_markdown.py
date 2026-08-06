from __future__ import annotations

import argparse
import re
from pathlib import Path

import pdfplumber


def clean_text(text: str) -> str:
    lines = []
    previous_blank = False
    for raw in text.replace("\r\n", "\n").splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        blank = not line
        if blank and previous_blank:
            continue
        lines.append(line)
        previous_blank = blank
    return "\n".join(lines).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a PDF to page-addressable UTF-8 Markdown.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--title", default="PDF 文本派生资料")
    parser.add_argument("--source-sha256", required=True)
    args = parser.parse_args()
    sections = [
        "---",
        f"source_file: {args.source.name}",
        f"source_sha256: {args.source_sha256}",
        "derivation: pdfplumber-page-text-extraction",
        "checked_at: 2026-08-02",
        "---",
        "",
        f"# {args.title}",
        "",
        "> 本文档是检索用派生文本，页码与原 PDF 对应；排版、图表和公式请以原件为准。",
    ]
    with pdfplumber.open(args.source) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = clean_text(page.extract_text(x_tolerance=2, y_tolerance=3) or "")
            sections.extend(["", f"## PDF 第 {page_number} 页", "", text or "[本页未提取到可搜索文本；请查看原 PDF 页面。]"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(sections) + "\n", encoding="utf-8", newline="\n")
    print(f"pages={len(pdf.pages)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
