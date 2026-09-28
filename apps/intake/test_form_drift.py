"""The deployed form and the registry that defines it must agree.

The questionnaire spent a year emitting a retired code frame with
nothing noticing, because nothing compared the two. The facts needed
were already in the database — every submission records the Kobo asset
it came from, and `FormVersion.kobo_asset_uid` records the asset the
registry believes it publishes to — and nothing read them together.

The sharpest case is the one that would have wasted a redeploy: on the
dev registry all 426 submissions arrive from two assets, and the active
FormVersion records a third that has received nothing.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.ingestion_hub.models import (
    Connector,
    DataProvisionAgreement,
    RawLanding,
    SourceSystem,
    SourceSystemKind,
)
from apps.intake.management.commands.report_form_drift import (
    collect,
    orphan_form_versions,
)
from apps.intake.models import FormVersion

pytestmark = pytest.mark.django_db


@pytest.fixture
def run(db):
    source = SourceSystem.objects.create(
        code="KOBO-DRIFT", name="Kobo drift", kind=SourceSystemKind.KOBO,
    )
    DataProvisionAgreement.objects.create(
        source_system=source, reference="DPA-DRIFT",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
    )
    from apps.ingestion_hub.services import start_connector_run
    return start_connector_run(
        Connector.objects.create(source_system=source, name="kobo-drift"),
    )


def _land(run, asset, n=1, version=""):
    for i in range(n):
        payload = {"_xform_id_string": asset, "_uuid": f"{asset}-{i}"}
        if version:
            payload["__version__"] = version
        RawLanding.objects.create(
            connector_run=run, payload=payload,
            source_reference=f"{asset}-{i}",
        )


def test_assets_are_reported_with_their_submission_counts(run):
    _land(run, "aLIVE", n=3)
    _land(run, "aOTHER", n=1)
    rows = {r["asset_uid"]: r for r in collect()}
    assert rows["aLIVE"]["submissions"] == 3
    assert rows["aOTHER"]["submissions"] == 1


def test_an_asset_the_registry_does_not_track_is_marked(run):
    """Every submission on the dev registry arrives from an untracked
    asset. That is the fact a redeploy would have been built on."""
    _land(run, "aLIVE", n=2)
    rows = {r["asset_uid"]: r for r in collect()}
    assert rows["aLIVE"]["tracked_by"] == ""


def test_a_tracked_asset_names_its_form_version(run):
    """The check has to be able to pass, or it reports nothing."""
    FormVersion.objects.create(
        version=94_001, name="Tracked", status="active", author="fixture",
        effective_from=date(2026, 1, 1), kobo_asset_uid="aLIVE",
    )
    _land(run, "aLIVE", n=2)
    rows = {r["asset_uid"]: r for r in collect()}
    assert rows["aLIVE"]["tracked_by"] == "v94001"


def test_an_active_form_publishing_where_nothing_arrives_is_reported(run):
    """The finding that stopped a redeploy: the active FormVersion
    records an asset with no submissions, so republishing it would have
    updated a form nobody uses and reported success."""
    FormVersion.objects.create(
        version=94_002, name="Orphan", status="active", author="fixture",
        effective_from=date(2026, 1, 1), is_active=True,
        kobo_asset_uid="aNOBODY",
    )
    _land(run, "aLIVE", n=2)
    assert [fv.kobo_asset_uid for fv in orphan_form_versions()] == ["aNOBODY"]


def test_a_form_publishing_where_submissions_arrive_is_not_reported(run):
    FormVersion.objects.create(
        version=94_003, name="Live", status="active", author="fixture",
        effective_from=date(2026, 1, 1), is_active=True,
        kobo_asset_uid="aLIVE",
    )
    _land(run, "aLIVE", n=2)
    assert orphan_form_versions() == []


def test_an_inactive_form_is_not_reported_as_orphaned(run):
    """A retired version is expected to receive nothing."""
    FormVersion.objects.create(
        version=94_004, name="Retired", status="active", author="fixture",
        effective_from=date(2026, 1, 1), is_active=False,
        kobo_asset_uid="aOLD",
    )
    _land(run, "aLIVE", n=1)
    assert orphan_form_versions() == []


def test_the_form_versions_seen_on_an_asset_are_reported(run):
    """Two Kobo versions on one asset means the form was revised, which
    is what a stale deployment looks like from the inside."""
    _land(run, "aLIVE", n=1, version="vONE")
    _land(run, "aLIVE", n=1, version="vTWO")
    rows = {r["asset_uid"]: r for r in collect()}
    assert rows["aLIVE"]["form_versions_seen"] == "vONE,vTWO"
