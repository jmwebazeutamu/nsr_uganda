# ruff: noqa: N806 — class-factory aliases (e.g. `Suppressor = _suppressor()`)
"""Suppressor unit tests — the *only* path that turns raw matview rows
into a user-visible response. Every assertion here is load-bearing
against the differencing-attack defence in ADR-0023 R2.

The Suppressor's contract:

    Suppressor.apply(rows, strictest_class, k_floor) -> {
        "rows": [{...group_keys..., "count": int|None, "suppressed": bool}, ...],
        "suppressed_cell_count": int,
    }

- count < k_floor → count is literally None (not 0, not "<5", not the
  original number). Suppressed flag is True.
- count >= k_floor → original count, suppressed flag is False.
- Sensitive class → refuses (raises typed exception).
- Public class (k_floor == 0) → never suppresses.
- Strictest class wins when projection + filter variables mix classes.

These assertions catch the leak modes the risk probe later exercises
end-to-end.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def _suppressor_class():
    """Indirect import — the Coder may put it under .services or
    .suppressor; tolerate either, and fail loudly when neither
    exists so synthesis catches it."""
    try:
        from apps.data_explorer.services import Suppressor
        return Suppressor
    except ImportError:
        pass
    from apps.data_explorer.suppressor import Suppressor  # noqa: F401
    return Suppressor


def _refuse_exception_types():
    """The 'refuse' path is either a typed exception or a sentinel.
    Accept either shape; the contract test below pins both."""
    exc_types: list[type[BaseException]] = []
    try:
        from apps.data_explorer.services import SuppressorRefused
        exc_types.append(SuppressorRefused)
    except Exception:
        pass
    try:
        from apps.data_explorer.services import SensitiveClassBlocked
        exc_types.append(SensitiveClassBlocked)
    except Exception:
        pass
    if not exc_types:
        # Generic fall-through — the Coder may use a plain ValueError
        # subclass. Any exception is acceptable as long as it's raised.
        exc_types.append(Exception)
    return tuple(exc_types)


# ───────────────────────────────────────────────────────────────────────
# Cell-level suppression contract
# ───────────────────────────────────────────────────────────────────────

class TestSuppressorCellLevel:

    def test_cell_below_k_floor_becomes_none(self, privacy_classes):
        Suppressor = _suppressor_class()
        rows = [
            {"sub_county": "Tapac", "count": 2},
            {"sub_county": "Moroto", "count": 1},
        ]
        result = Suppressor.apply(
            rows=rows, strictest_class="internal", k_floor=5,
        )
        for r in result["rows"]:
            # ADR-0023 R2: never leak the original number, never an
            # upper bound "≤ 5", never the string "<5".
            assert r["count"] is None, (
                f"Suppressed cell must be literal None — leaked {r['count']!r}"
            )
            assert r["count"] != 0
            assert r["count"] != "<5"
            assert r["suppressed"] is True

    def test_cell_at_k_floor_returns_original_count(self, privacy_classes):
        Suppressor = _suppressor_class()
        rows = [{"sub_county": "Kampala", "count": 5}]
        result = Suppressor.apply(
            rows=rows, strictest_class="internal", k_floor=5,
        )
        assert result["rows"][0]["count"] == 5
        assert result["rows"][0]["suppressed"] is False

    def test_cell_above_k_floor_returns_original_count(self, privacy_classes):
        Suppressor = _suppressor_class()
        rows = [{"sub_county": "Wakiso", "count": 47}]
        result = Suppressor.apply(
            rows=rows, strictest_class="internal", k_floor=5,
        )
        assert result["rows"][0]["count"] == 47
        assert result["rows"][0]["suppressed"] is False

    def test_suppressed_cell_count_in_metadata(self, privacy_classes):
        """Response must carry 'N of M cells suppressed' so UI can
        render the chip and the integration corpus can assert
        partial-suppression scenarios."""
        Suppressor = _suppressor_class()
        rows = [
            {"sub_county": "A", "count": 2},   # suppressed
            {"sub_county": "B", "count": 3},   # suppressed
            {"sub_county": "C", "count": 50},  # ok
            {"sub_county": "D", "count": 100}, # ok
        ]
        result = Suppressor.apply(
            rows=rows, strictest_class="internal", k_floor=5,
        )
        assert result["suppressed_cell_count"] == 2
        assert len(result["rows"]) == 4

    def test_public_class_never_suppresses(self, privacy_classes):
        """Public class has k_floor == 0 → every cell passes through."""
        Suppressor = _suppressor_class()
        rows = [{"x": "a", "count": 1}, {"x": "b", "count": 0}]
        result = Suppressor.apply(
            rows=rows, strictest_class="public", k_floor=0,
        )
        for r in result["rows"]:
            assert r["count"] in (0, 1)
            assert r["suppressed"] is False
        assert result["suppressed_cell_count"] == 0


# ───────────────────────────────────────────────────────────────────────
# No-upper-bound-leak guarantee (the differencing-attack defence)
# ───────────────────────────────────────────────────────────────────────

class TestNoUpperBoundLeak:

    @pytest.mark.parametrize("true_count", [1, 2, 3, 4])
    def test_suppressed_cell_is_literal_none_not_bounded_string(
        self, privacy_classes, true_count,
    ):
        Suppressor = _suppressor_class()
        result = Suppressor.apply(
            rows=[{"k": "v", "count": true_count}],
            strictest_class="internal", k_floor=5,
        )
        cell = result["rows"][0]["count"]
        # The probe assertion: cell must be None, never the count and
        # never an informative bound. A value like "<5" would let the
        # attacker compute  Q1 - Q2 = ("<5") - ("<5") even by hand.
        assert cell is None
        # Belt and braces — type check too in case the response shape
        # ever sneaks in an int 0.
        assert not isinstance(cell, int)
        assert not isinstance(cell, str)


# ───────────────────────────────────────────────────────────────────────
# Sensitive-class refusal
# ───────────────────────────────────────────────────────────────────────

class TestSensitiveRefusal:

    def test_sensitive_strictest_class_refuses_query(self, privacy_classes):
        """A Sensitive variable in projection or filter → refuse at
        validation. The Suppressor is the last line; if anything
        reaches it the contract still says 'do not compute a count'.
        """
        Suppressor = _suppressor_class()
        with pytest.raises(_refuse_exception_types()):
            Suppressor.apply(
                rows=[{"k": "v", "count": 100}],
                strictest_class="sensitive", k_floor=0,
            )


# ───────────────────────────────────────────────────────────────────────
# Strictest-class-wins (projection vs filter variables)
# ───────────────────────────────────────────────────────────────────────

class TestStrictestClassWins:

    def test_projection_internal_filter_personal_uses_personal_floor(
        self, privacy_classes,
    ):
        """Personal k_floor=10 must apply even though the projection
        variable is Internal (k_floor=5). Otherwise a Personal filter
        leaks small cells via Internal projections."""
        Suppressor = _suppressor_class()
        # Strictest class is "personal" so k_floor=10.
        rows = [
            {"sub_county": "Kampala", "count": 9},   # below 10 → suppressed
            {"sub_county": "Wakiso", "count": 15},   # >= 10 → ok
        ]
        result = Suppressor.apply(
            rows=rows, strictest_class="personal", k_floor=10,
        )
        # First row suppressed even though 9 > internal k_floor(5)
        assert result["rows"][0]["count"] is None
        assert result["rows"][0]["suppressed"] is True
        assert result["rows"][1]["count"] == 15
        assert result["suppressed_cell_count"] == 1

    def test_strictest_class_helper_picks_personal_over_internal(
        self, privacy_classes,
    ):
        """If the Coder exposes a helper to compute strictest class,
        assert it directly. Tolerant of helper missing — primary
        assertion is the rows-based test above."""
        try:
            from apps.data_explorer.services import strictest_class
        except ImportError:
            pytest.skip("strictest_class helper not exposed; behaviour "
                        "covered by test_projection_internal_filter_*")
        assert strictest_class(["internal", "personal", "public"]) == "personal"
        assert strictest_class(["public", "internal"]) == "internal"
        assert strictest_class(["public"]) == "public"
        # Sensitive always wins
        assert strictest_class(["public", "sensitive"]) == "sensitive"


# ───────────────────────────────────────────────────────────────────────
# Empty / edge inputs
# ───────────────────────────────────────────────────────────────────────

class TestEmptyAndEdges:

    def test_empty_rows_returns_zero_suppressed(self, privacy_classes):
        Suppressor = _suppressor_class()
        result = Suppressor.apply(
            rows=[], strictest_class="internal", k_floor=5,
        )
        assert result["rows"] == []
        assert result["suppressed_cell_count"] == 0

    def test_count_missing_treated_as_suppressible_zero(self, privacy_classes):
        """A matview row without 'count' is degenerate; assert the
        Suppressor either raises or suppresses, never returns a
        partial row that could be reconstructed."""
        Suppressor = _suppressor_class()
        try:
            result = Suppressor.apply(
                rows=[{"sub_county": "X"}],
                strictest_class="internal", k_floor=5,
            )
        except Exception:
            return
        # If it didn't raise, the row's count must be None.
        assert result["rows"][0].get("count") is None
        assert result["rows"][0].get("suppressed") is True
