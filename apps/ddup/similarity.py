"""Field-level similarity functions for DDUP tier 3 (probabilistic).

Self-contained — no fuzzy-match library dependency. Adding one would
need an ADR per the project's coding-standards rule; the standard
Jaro-Winkler algorithm is short enough to write in-tree, and the
per-field functions here are the ONLY similarity primitives the tier
3 discovery uses.

All functions return a normalised similarity in [0.0, 1.0]:
    1.0 = exact match
    0.0 = entirely dissimilar
The composite score is a weighted average of these per-field values.

References:
- Jaro, M. (1989). "Advances in Record-Linkage Methodology as Applied
  to Matching the 1985 Census of Tampa, Florida."
- Winkler, W.E. (1990). "String Comparator Metrics and Enhanced
  Decision Rules for the Fellegi-Sunter Model of Record Linkage."
"""

from __future__ import annotations

from datetime import date


def jaro(a: str, b: str) -> float:
    """Jaro similarity. O(|a|*|b|) but the strings are short (names)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    a_len, b_len = len(a), len(b)
    window = max(a_len, b_len) // 2 - 1
    if window < 0:
        window = 0

    a_flags = [False] * a_len
    b_flags = [False] * b_len
    matches = 0
    for i, ch_a in enumerate(a):
        lo = max(0, i - window)
        hi = min(b_len, i + window + 1)
        for j in range(lo, hi):
            if not b_flags[j] and ch_a == b[j]:
                a_flags[i] = True
                b_flags[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    transpositions = 0
    j = 0
    for i in range(a_len):
        if a_flags[i]:
            while not b_flags[j]:
                j += 1
            if a[i] != b[j]:
                transpositions += 1
            j += 1
    transpositions //= 2

    return (
        matches / a_len
        + matches / b_len
        + (matches - transpositions) / matches
    ) / 3.0


def jaro_winkler(a: str, b: str, *, prefix_scale: float = 0.1) -> float:
    """Jaro with the Winkler prefix boost (capped at 4 chars). Names
    benefit from this because they tend to agree on the first few
    characters even when transliteration varies the tail."""
    j = jaro(a, b)
    if j == 0.0:
        return 0.0
    common_prefix = 0
    for ca, cb in zip(a, b, strict=False):
        if ca != cb:
            break
        common_prefix += 1
        if common_prefix == 4:
            break
    return j + common_prefix * prefix_scale * (1.0 - j)


def year_proximity(d1: date | None, d2: date | None, *, max_years: int = 2) -> float:
    """Birth-year similarity. 1.0 same year, linearly down to 0 at
    >= max_years apart. None on either side yields 0.0 — the dedup
    workbench should NOT collapse identities just because both are
    missing a DOB."""
    if d1 is None or d2 is None:
        return 0.0
    diff = abs(d1.year - d2.year)
    if diff >= max_years:
        return 0.0
    return 1.0 - diff / max_years


def exact(a, b) -> float:
    """Plain equality similarity. Handles None vs '' the same way:
    treat empty-equivalent values as missing -> 0.0 to avoid spurious
    matches on a sea of blank villages."""
    if a in (None, "") or b in (None, ""):
        return 0.0
    return 1.0 if a == b else 0.0


def composite_score(pairs: list[tuple[float, float]]) -> float:
    """Weighted average of (weight, similarity) pairs, normalised to
    the total weight. Returns 0.0 when weights sum to 0 (defensive)."""
    if not pairs:
        return 0.0
    total_weight = sum(w for w, _ in pairs)
    if total_weight == 0:
        return 0.0
    weighted = sum(w * s for w, s in pairs)
    return weighted / total_weight
