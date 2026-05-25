"""Markdown → chunks, split by H2 heading.

v1 strategy:
- Walk top-down. The first H1 becomes the page title and is prepended
  to every chunk's heading_path.
- Each H2 (or top-level pre-H2 content) becomes one chunk.
- H3+ headings stay inline within the H2's body.
- Tables, code fences, and lists travel with their section.

Small / large chunk handling is intentionally absent for v1 — the
manuals are mostly evenly-sized H2 sections (~150–400 words). Revisit
once retrieval recall is measured on real queries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

H1_RE = re.compile(r"^# +(.+?)\s*$")
H2_RE = re.compile(r"^## +(.+?)\s*$")


@dataclass(frozen=True)
class Chunk:
    heading_path: str
    body: str

    @property
    def token_count(self) -> int:
        # Cheap heuristic — sentence-transformers tokenises ~1 token per 4 chars.
        return max(1, len(self.body) // 4)


def chunk_markdown(source: str) -> list[Chunk]:
    """Split markdown into H2-rooted chunks.

    The returned list always has at least one entry if `source` has
    any non-whitespace content; pre-H2 prose becomes a chunk titled
    after the H1 (or "Preamble" if no H1 is found).
    """
    lines = source.splitlines()
    page_title = ""
    sections: list[tuple[str, list[str]]] = []
    current_heading = ""
    current_body: list[str] = []

    def flush():
        if not any(line.strip() for line in current_body):
            return
        sections.append((current_heading, current_body[:]))

    for line in lines:
        h1 = H1_RE.match(line)
        if h1 and not page_title:
            page_title = h1.group(1).strip()
            continue
        h2 = H2_RE.match(line)
        if h2:
            flush()
            current_heading = h2.group(1).strip()
            current_body = []
            continue
        current_body.append(line)
    flush()

    chunks: list[Chunk] = []
    for heading, body_lines in sections:
        if heading:
            heading_path = f"{page_title} > {heading}" if page_title else heading
        else:
            heading_path = page_title or "Preamble"
        body = "\n".join(body_lines).strip()
        if not body:
            continue
        chunks.append(Chunk(heading_path=heading_path, body=body))
    return chunks
