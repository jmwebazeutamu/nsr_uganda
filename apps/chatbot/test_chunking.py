"""CHB-003 — markdown chunker."""

from __future__ import annotations

from apps.chatbot.chunking import chunk_markdown


def test_h1_becomes_page_title_for_every_chunk():
    source = """# Walk-in submissions

Walk-ins are captured by Parish Chiefs in person.

## Fast-track lane

A Parish Chief may auto-promote a household via the DIH fast-track.

## Quality-failed archive

Failed records sit in the archive for 30 days before purge.
"""
    chunks = chunk_markdown(source)
    assert len(chunks) == 3
    assert chunks[0].heading_path == "Walk-in submissions"
    assert chunks[1].heading_path == "Walk-in submissions > Fast-track lane"
    assert chunks[2].heading_path == "Walk-in submissions > Quality-failed archive"


def test_preamble_chunk_skipped_when_only_whitespace():
    source = """# Title

## Real section

Content here.
"""
    chunks = chunk_markdown(source)
    # Empty preamble (whitespace-only between H1 and H2) does not chunk.
    assert len(chunks) == 1
    assert chunks[0].heading_path == "Title > Real section"


def test_no_h1_falls_back_to_preamble_label():
    source = """## Lone section

Body."""
    chunks = chunk_markdown(source)
    assert chunks[0].heading_path == "Lone section"


def test_h3_stays_inline_with_h2_body():
    source = """# Title

## Big section

Intro paragraph.

### Sub-section

Sub-content under H3 stays in the parent chunk.
"""
    chunks = chunk_markdown(source)
    assert len(chunks) == 1
    assert "### Sub-section" in chunks[0].body
    assert "Sub-content" in chunks[0].body


def test_token_count_rough_estimate():
    source = "# Title\n\n## Section\n\n" + ("word " * 100)
    chunks = chunk_markdown(source)
    assert chunks[0].token_count > 50  # ~500 chars / 4 = ~125
