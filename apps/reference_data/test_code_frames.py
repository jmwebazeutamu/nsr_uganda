"""Two spellings of one county code, and the row that proves you cannot
just strip the zero.

`412.02` is "Nyakagyeme" and `412.2` is "Rujumbura County" — both real,
both ACTIVE, different places. Any fix that rewrites a padded county
segment on sight moves households from one to the other. So the
resolver looks for a row that exists, exact spelling first, and only
tries the alternative when the exact code names nothing.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.reference_data.code_frames import (
    code_spellings,
    resolve_geographic_unit,
)
from apps.reference_data.models import GeographicUnit


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        # county segment padded -> unpadded alternative
        ("320.02", ["320.02", "320.2"]),
        ("320.02.11", ["320.02.11", "320.2.11"]),
        ("320.02.11.08", ["320.02.11.08", "320.2.11.08"]),
        # ...and the other way round
        ("320.2", ["320.2", "320.02"]),
        ("414.1.21", ["414.1.21", "414.01.21"]),
        # no county segment at all
        ("320", ["320"]),
        ("R-NORTHERN", ["R-NORTHERN"]),
        ("SR-WEST-NILE-NORTHERN", ["SR-WEST-NILE-NORTHERN"]),
        # a two-digit county that is not zero-padded stays a pair, but
        # the sub-county segment is never touched
        ("228.11.06", ["228.11.06", "228.011.06"]),
        # non-numeric county segment — leave it alone
        ("320.EAST.11", ["320.EAST.11"]),
        ("", []),
    ],
)
def test_code_spellings(code, expected):
    assert code_spellings(code) == expected


def test_the_given_spelling_is_always_tried_first():
    assert code_spellings("412.02")[0] == "412.02"
    assert code_spellings("412.2")[0] == "412.2"


@pytest.mark.django_db
class TestResolve:

    @pytest.fixture
    def district(self):
        return GeographicUnit.objects.create(
            level="district", code="412", name="Rukungiri",
            effective_from=date(2026, 1, 1),
        )

    def _county(self, district, code, name):
        return GeographicUnit.objects.create(
            level="county", code=code, name=name, parent=district,
            effective_from=date(2026, 1, 1),
        )

    def test_exact_code_wins_when_both_spellings_exist(self, district):
        """The case that forbids rewriting. Both are real places."""
        nyakagyeme = self._county(district, "412.02", "Nyakagyeme")
        rujumbura = self._county(district, "412.2", "Rujumbura County")

        assert resolve_geographic_unit("county", "412.02") == nyakagyeme
        assert resolve_geographic_unit("county", "412.2") == rujumbura

    def test_falls_back_to_the_other_spelling(self, district):
        """A Kobo-padded code finding the UBOS row — the whole point."""
        maracha = self._county(district, "320.2", "Maracha East County")
        assert resolve_geographic_unit("county", "320.02") == maracha

    def test_falls_back_the_other_way(self, district):
        padded = self._county(district, "320.02", "Maracha East County")
        assert resolve_geographic_unit("county", "320.2") == padded

    def test_unknown_code_resolves_to_nothing(self, district):
        assert resolve_geographic_unit("county", "999.9") is None

    def test_level_is_respected(self, district):
        self._county(district, "320.2", "Maracha East County")
        assert resolve_geographic_unit("sub_county", "320.02") is None

    def test_latest_version_wins(self, district):
        """The frame is versioned: a renamed unit leaves a superseded
        row behind at the same code. `geounit_one_active_per_code`
        allows only one ACTIVE, so the old row must be superseded
        first — which is what the lifecycle does.
        """
        GeographicUnit.objects.create(
            level="county", code="320.2", name="Old name", parent=district,
            effective_from=date(2025, 1, 1),
            effective_to=date(2025, 12, 31),
            status=GeographicUnit.Status.SUPERSEDED,
        )
        newer = GeographicUnit.objects.create(
            level="county", code="320.2", name="Maracha East County",
            parent=district, effective_from=date(2026, 1, 1),
        )
        assert resolve_geographic_unit("county", "320.02") == newer


@pytest.mark.django_db
def test_backfill_stops_fabricating_a_unit_that_already_exists():
    """The regression that produced the 47.

    `geo_backfill` matched on the literal code, so a staged record
    naming the Kobo spelling found nothing and it created a second row
    for a county already in the frame. It resolves across both
    spellings now.
    """
    from apps.ingestion_hub.geo_backfill import backfill_missing_geo_from_stages

    region = GeographicUnit.objects.create(
        level="region", code="R-NORTHERN", name="Northern",
        effective_from=date(2026, 1, 1),
    )
    sub_region = GeographicUnit.objects.create(
        level="sub_region", code="SR-WEST-NILE", name="West Nile",
        parent=region, effective_from=date(2026, 1, 1),
    )
    district = GeographicUnit.objects.create(
        level="district", code="320", name="Maracha",
        parent=sub_region, effective_from=date(2026, 1, 1),
    )
    GeographicUnit.objects.create(
        level="county", code="320.2", name="Maracha East County",
        parent=district, effective_from=date(2026, 1, 1),
    )

    before = GeographicUnit.objects.filter(level="county").count()

    from apps.ingestion_hub.models import (
        Connector, ConnectorRun, SourceSystem, StageRecord,
    )
    source = SourceSystem.objects.create(name="Kobo", kind="kobo")
    connector = Connector.objects.create(source_system=source, name="kobo-main")
    run = ConnectorRun.objects.create(connector=connector)
    StageRecord.objects.create(
        connector_run=run,
        canonical_payload={
            "geographic": {
                "region": "R-NORTHERN", "sub_region": "SR-WEST-NILE",
                "district": "320",
                # The Kobo spelling of a county already in the frame.
                "county": "320.02",
            },
        },
    )

    backfill_missing_geo_from_stages()

    assert GeographicUnit.objects.filter(level="county").count() == before, (
        "geo_backfill fabricated a second row for a county that already "
        "exists under the UBOS spelling"
    )
