"""Suppressor — the single funnel from raw matview rows to a user-
visible response. ADR-0023 D3.

Every aggregate response goes through Suppressor.apply(). No other
code path may emit a count to the API surface.

Rules (locked):
1. Strictest PrivacyClass across all variables in the query (projected
   AND filtered) wins.
2. Sensitive → refused at validation time. Suppressor never sees the
   rows because the query never runs.
3. count < k_floor → count replaced with None, suppressed=True. Never
   returns the original number; never returns an upper bound like
   "≤ 5" (that would leak the bound).
4. count >= k_floor → count returned verbatim, suppressed=False.
5. The response carries `suppressed_cell_count` so the UI can show
   "N of M cells suppressed".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SuppressionResult:
    rows: list[dict]
    suppressed_cell_count: int
    total_cell_count: int
    k_floor: int
    strictest_class: str

    # dict-style access so tests + serialisers can pluck `["rows"]`
    # alongside the dataclass attribute access used internally.
    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)


class SuppressorError(Exception):
    """Raised when the suppressor is asked to operate on a class it
    is contractually forbidden to handle (e.g. Sensitive)."""


class Suppressor:

    SENSITIVE_CODE = "sensitive"

    @classmethod
    def apply(cls, rows: list[dict], *, strictest_class_code: str | None = None,
              strictest_class: str | None = None,
              k_floor: int, count_field: str = "count") -> SuppressionResult:
        # Accept either `strictest_class_code` (original Coder signature)
        # or `strictest_class` (Tester signature + spec wording). Single
        # internal var either way.
        strictest_class_code = strictest_class_code or strictest_class
        if strictest_class_code is None:
            raise TypeError(
                "Suppressor.apply() requires `strictest_class` "
                "(or legacy `strictest_class_code`).",
            )
        """Apply cell suppression to `rows` in-place.

        Each row must contain `count_field`. Rows where the count is
        below `k_floor` get the count replaced with None and a
        `suppressed: True` flag added; otherwise `suppressed: False`.

        Raises SuppressorError if asked to handle a Sensitive class —
        the validator should have refused the query before this is
        reached.
        """
        if strictest_class_code == cls.SENSITIVE_CODE:
            raise SuppressorError(
                "Sensitive class must be refused at validation time; "
                "Suppressor never receives Sensitive rows."
            )
        suppressed = 0
        for row in rows:
            raw = row.get(count_field)
            if raw is None:
                # Already null — keep suppressed=True so UI renders
                # consistently.
                row[count_field] = None
                row["suppressed"] = True
                suppressed += 1
                continue
            if k_floor > 0 and raw < k_floor:
                row[count_field] = None
                row["suppressed"] = True
                suppressed += 1
            else:
                row["suppressed"] = False
        return SuppressionResult(
            rows=rows,
            suppressed_cell_count=suppressed,
            total_cell_count=len(rows),
            k_floor=k_floor,
            strictest_class=strictest_class_code,
        )
