"""The §8.3 disclosure floor on public aggregates.

The public site is unauthenticated, so every number these functions
return is readable by anyone. A small cell in a named geography is close
to naming the households in it, which is the re-identification risk the
floor exists to close.
"""

import pytest

from apps.reporting.public_aggregates import (
    ROUND_TO,
    SUPPRESSION_THRESHOLD,
    floor_count,
    floor_percent,
    floor_series,
)


class TestSingleCell:

    @pytest.mark.parametrize("n", [0, 1, 5, 9])
    def test_below_the_threshold_is_suppressed_not_zeroed(self, n):
        assert floor_count(n) is None, f"{n} households was published"

    def test_the_threshold_itself_publishes(self):
        assert floor_count(SUPPRESSION_THRESHOLD) is not None

    @pytest.mark.parametrize("n,expected", [
        (10, 10), (12, 10), (13, 15), (22, 20), (27, 25), (28, 30), (98, 100),
    ])
    def test_counts_below_100_round_to_the_nearest_5(self, n, expected):
        assert floor_count(n) == expected

    @pytest.mark.parametrize("n", [100, 101, 284, 12345])
    def test_counts_at_or_above_100_are_exact(self, n):
        assert floor_count(n) == n

    def test_rounding_never_reveals_a_suppressed_cell(self):
        """Rounding must not map a sub-threshold count onto a published one."""
        for n in range(0, SUPPRESSION_THRESHOLD):
            assert floor_count(n) is None
        assert floor_count(SUPPRESSION_THRESHOLD) % ROUND_TO == 0


class TestPercentages:

    def test_a_percentage_over_a_tiny_numerator_is_suppressed(self):
        assert floor_percent(4, 1000) is None

    def test_percentages_carry_one_decimal(self):
        assert floor_percent(333, 1000) == 33.3

    def test_zero_denominator_does_not_explode(self):
        assert floor_percent(0, 0) is None


class TestComplementarySuppression:
    """A lone suppressed cell is recoverable by subtraction from the total."""

    def test_a_single_small_cell_takes_a_second_cell_with_it(self):
        s = floor_series([("A", 500), ("B", 400), ("C", 120), ("D", 3)])
        suppressed = [c.label for c in s.cells if c.suppressed]
        assert "D" in suppressed
        assert len(suppressed) == 2, (
            "D is recoverable as total - (A+B+C) unless a second cell goes too"
        )
        # the second victim is the smallest survivor, not an arbitrary one
        assert "C" in suppressed

    def test_two_already_small_cells_need_no_extra_victim(self):
        s = floor_series([("A", 500), ("B", 400), ("C", 4), ("D", 3)])
        suppressed = [c.label for c in s.cells if c.suppressed]
        assert sorted(suppressed) == ["C", "D"]

    def test_a_clean_series_suppresses_nothing(self):
        s = floor_series([("A", 500), ("B", 400), ("C", 120)])
        assert not s.any_suppressed
        assert all(not c.suppressed for c in s.cells)

    def test_suppressed_cells_render_as_the_mark_not_a_number(self):
        s = floor_series([("A", 500), ("B", 2)])
        marks = [c.display for c in s.cells if c.suppressed]
        assert marks and all(m == ".." for m in marks)

    def test_no_raw_value_leaks_into_the_published_value(self):
        s = floor_series([("A", 27), ("B", 3)])
        for c in s.cells:
            if c.suppressed:
                assert c.value is None
            else:
                assert c.value != c.raw or c.raw % ROUND_TO == 0
