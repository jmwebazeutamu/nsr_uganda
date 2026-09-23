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


def birth_date_proximity(d1: date | None, d2: date | None, *, max_years: int = 2) -> float:
    """Birth-date similarity, on the whole date rather than the year.

    This replaced `year_proximity`, which compared only `d.year` while
    being used as the `date_of_birth` feature. Two different people born
    in the same calendar year therefore scored a *perfect* date match —
    and because tier 3 blocks by village, `village` is 1.0 for every pair
    it ever compares, so 0.30 of the weight was free for anyone sharing a
    village and a birth year.

    That was not theoretical. Rebecca Akello (1993-06-05) and Rebecca
    Okello (1993-09-28) — two people in one household, different NINs,
    different phones — scored 0.967 on the first production run, above
    the 0.95 auto-merge threshold. Had auto-merge been on they would have
    been collapsed into one registry identity overnight.

    The bands:

      same date                 1.0   the same person, or the same record
      within 31 days            0.75  a transcription slip: a swapped
                                      day and month, or a wrong digit
      same year, further apart  0.4   same cohort, and little else
      one year apart            0.2
      >= max_years apart        0.0

    A missing date on either side is 0.0, not a match: the workbench must
    not collapse two identities because neither has a date of birth.
    """
    if d1 is None or d2 is None:
        return 0.0
    if d1 == d2:
        return 1.0
    if abs((d1 - d2).days) <= 31:
        return 0.75
    year_gap = abs(d1.year - d2.year)
    if year_gap == 0:
        return 0.4
    if year_gap >= max_years:
        return 0.0
    return 0.2


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
