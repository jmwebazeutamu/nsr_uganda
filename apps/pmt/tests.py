"""PMT engine + service tests.

(File picked for the sub_region_code invariant test because PMT tests
already construct full Household + Member fixtures and the assertion is
adjacent to data-model concerns. The check itself belongs to
data_management; consider moving when data_management/tests.py exists.)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.data_management.models import Household, Member
from apps.pmt.engine import compute_pmt, derive_band
from apps.pmt.models import Band, ModelStatus, PMTModelVersion, PMTResult
from apps.pmt.services import (
    PMTApprovalError,
    activate_model_version,
    get_active_model_version,
    recompute_for_household,
)
from apps.reference_data.models import GeographicUnit

# --- Fixtures ---------------------------------------------------------------

@pytest.fixture
def geo(db):
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"P-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1),
        )
    return nodes


@pytest.fixture
def household(db, geo):
    return Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"], county=geo["c"],
        sub_county=geo["sc"], parish=geo["p"], village=geo["v"], urban_rural="2",
    )


def _add_members(household, n: int) -> None:
    for i in range(n):
        Member.objects.create(
            household=household, line_number=i + 1,
            surname=f"S{i}", first_name=f"F{i}", sex="1" if i % 2 else "F",
        )


def _active_model(*, intercept=50, weight=-5, author="seeder", approver="reviewer"):
    v = PMTModelVersion.objects.create(
        version=1, intercept=Decimal(str(intercept)), author=author,
        variables=[{"variable": "member_count", "weight": weight, "transform": "identity"}],
        band_cutoffs={
            Band.EXTREME_POVERTY: 0,
            Band.POVERTY: 30,
            Band.VULNERABLE: 60,
            Band.NOT_POOR: 80,
        },
    )
    return activate_model_version(v, approver=approver)


# --- Engine -----------------------------------------------------------------

class TestEngine:
    def test_compute_with_member_count_weight(self, household):
        _add_members(household, 4)
        model = _active_model(intercept=80, weight=-5)
        score, band, snap = compute_pmt(household, model)
        # 80 + (-5 * 4) = 60 -> VULNERABLE (lower bound 60)
        assert score == 60
        assert band == Band.VULNERABLE
        assert snap["member_count"]["weight"] == -5
        assert snap["member_count"]["contribution"] == -20

    def test_derive_band_handles_boundaries(self):
        cutoffs = {b: c for b, c in [
            (Band.EXTREME_POVERTY, 0), (Band.POVERTY, 30),
            (Band.VULNERABLE, 60), (Band.NOT_POOR, 80),
        ]}
        assert derive_band(0, cutoffs) == Band.EXTREME_POVERTY
        assert derive_band(29.99, cutoffs) == Band.EXTREME_POVERTY
        assert derive_band(30, cutoffs) == Band.POVERTY
        assert derive_band(80, cutoffs) == Band.NOT_POOR
        assert derive_band(100, cutoffs) == Band.NOT_POOR


# --- Activation dual approval ----------------------------------------------

class TestActivation:
    def test_activate_happy_path(self, db):
        v = PMTModelVersion.objects.create(version=1, author="a", variables=[])
        activate_model_version(v, approver="b")
        v.refresh_from_db()
        assert v.status == ModelStatus.ACTIVE
        assert v.approved_by == "b"

    def test_author_cannot_approve(self, db):
        v = PMTModelVersion.objects.create(version=1, author="alice", variables=[])
        with pytest.raises(PMTApprovalError, match="differ"):
            activate_model_version(v, approver="alice")

    def test_activate_retires_prior(self, db):
        v1 = PMTModelVersion.objects.create(version=1, author="a", variables=[])
        activate_model_version(v1, approver="b")
        v2 = PMTModelVersion.objects.create(version=2, author="a", variables=[])
        activate_model_version(v2, approver="b")
        v1.refresh_from_db()
        assert v1.status == ModelStatus.RETIRED


# --- Recompute service -----------------------------------------------------

class TestRecompute:
    def test_recompute_creates_result_and_updates_household(self, household):
        _add_members(household, 3)
        _active_model(intercept=70, weight=-5)  # 70 - 15 = 55 -> POVERTY (>=30)
        result = recompute_for_household(household, triggered_by="manual")
        household.refresh_from_db()
        assert result is not None
        assert result.score == 55
        assert result.band == Band.POVERTY
        assert household.current_pmt_score == 55
        assert household.current_vulnerability_band == Band.POVERTY

    def test_recompute_no_op_without_active_model(self, household):
        # No PMTModelVersion ACTIVE
        assert get_active_model_version() is None
        result = recompute_for_household(household)
        assert result is None
        assert PMTResult.objects.count() == 0

    def test_recompute_appends_history_not_overwrite(self, household):
        _add_members(household, 2)
        _active_model(intercept=50, weight=-5)
        recompute_for_household(household, triggered_by="dih_promote")
        recompute_for_household(household, triggered_by="manual")
        assert PMTResult.objects.filter(household=household).count() == 2


# --- UPD signal integration -------------------------------------------------

class TestUpdSignalIntegration:
    def test_pmt_relevant_upd_commit_triggers_recompute(self, household):
        from apps.update_workflow.models import (
            ChangeRequest,
            ChangeStatus,
            ChangeType,
            EntityType,
            SourceChannel,
        )
        from apps.update_workflow.services import (
            commit_change_request,
            submit_change_request,
        )

        _add_members(household, 2)
        _active_model(intercept=50, weight=-5)

        cr = ChangeRequest.objects.create(
            entity_type=EntityType.HOUSEHOLD, entity_id=household.id,
            change_type=ChangeType.CORRECTION, pmt_relevant=True,
            changes={"address_narrative": {"old": "", "new": "Plot 7"}},
            source_channel=SourceChannel.PARISH, requester="alice",
        )
        submit_change_request(cr)
        commit_change_request(cr, approver="bob")
        cr.refresh_from_db()
        assert cr.status == ChangeStatus.COMMITTED
        # The signal should have fired the PMT recompute.
        results = PMTResult.objects.filter(household=household,
                                           triggered_by="upd_commit")
        assert results.count() == 1

    def test_non_pmt_relevant_upd_commit_no_recompute(self, household):
        from apps.update_workflow.models import (
            ChangeRequest,
            ChangeType,
            EntityType,
            SourceChannel,
        )
        from apps.update_workflow.services import (
            commit_change_request,
            submit_change_request,
        )

        _active_model(intercept=50, weight=-5)
        cr = ChangeRequest.objects.create(
            entity_type=EntityType.HOUSEHOLD, entity_id=household.id,
            change_type=ChangeType.CORRECTION, pmt_relevant=False,
            changes={"address_narrative": {"old": "", "new": "Plot 7"}},
            source_channel=SourceChannel.PARISH, requester="alice",
        )
        submit_change_request(cr)
        commit_change_request(cr, approver="bob")
        assert not PMTResult.objects.filter(triggered_by="upd_commit").exists()
