#!/usr/bin/env python3
"""Lint gate enforcing the ADR-0010 / US-S23 global rule:

    "No TextChoices, no choices=[...], no hardcoded option arrays
     in apps/partners/ or design/v0.1/screens/screens-partners.jsx."

Pre-existing instances elsewhere in the tree are NOT flagged — the
gate is scoped to the partners-module surface per the spec. To add
a new banned pattern: append to PATTERNS below.

Pure Python so the gate runs identically on macOS (BSD grep) and
Ubuntu CI (GNU grep). Exits non-zero with a structured report when
any banned pattern lands in a watched path.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PATHS = [
    ROOT / "apps" / "partners",
    ROOT / "design" / "v0.1" / "screens" / "screens-partners.jsx",
    ROOT / "design" / "v0.1" / "screens" / "screens-partner-detail.jsx",
    ROOT / "design" / "v0.1" / "screens" / "screens-programme-new.jsx",
]

# (regex, description). Regexes use Python's re module — \b is a
# word-boundary, \s+ is whitespace.
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bTextChoices\b"),         "TextChoices class declaration"),
    (re.compile(r"choices\s*=\s*\["),        "choices=[...] argument"),
    (re.compile(r"\bconst\s+ORG_TYPES\b"),   "inline ORG_TYPES array"),
    (re.compile(r"\bconst\s+STATUSES\b"),    "inline STATUSES array"),
    (re.compile(r"\bconst\s+STATUS_TONE\b"), "inline STATUS_TONE map"),
    (re.compile(r"\bconst\s+SECTORS\b"),     "inline SECTORS array"),
    (re.compile(r"\bconst\s+REG_STEPS\b"),   "inline REG_STEPS array"),
    (re.compile(r"\bconst\s+SAMPLE_PROGS\b"),"inline SAMPLE_PROGS array"),
    (re.compile(r"\bconst\s+ORG_TYPE_HINT\b"),"inline ORG_TYPE_HINT map"),
    (re.compile(r"\bconst\s+FIELD_GROUPS\b"),"inline FIELD_GROUPS array"),
    (re.compile(r"\bconst\s+GEO_OPTIONS\b"), "inline GEO_OPTIONS array"),
    # US-S25-005 — programme-wizard inline lists (the rule extends
    # to every coded selector on the registration wizard).
    (re.compile(r"\bconst\s+PROG_KINDS\b"),  "inline PROG_KINDS array"),
    (re.compile(r"\bconst\s+PROG_UNITS\b"),  "inline PROG_UNITS array"),
    (re.compile(r"\bconst\s+PROG_CYCLES\b"), "inline PROG_CYCLES array"),
    (re.compile(r"\bconst\s+PMT_BANDS\b"),   "inline PMT_BANDS array"),
    (re.compile(r"\bconst\s+SUB_REGIONS\b"), "inline SUB_REGIONS array"),
    (re.compile(r"\bconst\s+EXIT_REASONS_LIST\b"), "inline EXIT_REASONS_LIST array"),
    (re.compile(r"\bconst\s+PARTNER_OPTIONS\b"),   "inline PARTNER_OPTIONS array"),
]

# This script itself defines the regexes; skip it.
EXCLUDE_NAMES = {"no_hardcoded_choice_lists.py"}


def _iter_files() -> list[Path]:
    out: list[Path] = []
    for path in PATHS:
        if not path.exists():
            continue
        if path.is_file():
            out.append(path)
            continue
        for f in path.rglob("*"):
            if not f.is_file():
                continue
            if "__pycache__" in f.parts:
                continue
            if f.name in EXCLUDE_NAMES:
                continue
            if f.suffix in {".pyc", ".pyo"}:
                continue
            out.append(f)
    return out


def main() -> int:
    violations: list[tuple[str, str, int, str]] = []
    for f in _iter_files():
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat, desc in PATTERNS:
                if pat.search(line):
                    rel = str(f.relative_to(ROOT))
                    violations.append((desc, rel, lineno, line.strip()))

    if violations:
        print(
            "Banned coded-list patterns found. Route through "
            "apps.reference_data.services.resolve_label / useChoiceList "
            "instead. See ADR-0010 + US-S23 global rule.",
            file=sys.stderr,
        )
        for desc, rel, lineno, line in violations:
            print(f"  {rel}:{lineno}  [{desc}]  {line}", file=sys.stderr)
        return 1

    print("OK: no hardcoded coded-list patterns in the partners surface.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
