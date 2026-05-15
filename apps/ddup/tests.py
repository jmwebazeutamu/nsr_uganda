"""DDUP tier 1 + merge transaction tests.

References: SAD §4.3.6 acceptance criteria.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_management.models import Household, Member
from apps.ddup.models import (
    DdupModelVersion,
    MergeAction,
    ModelStatus,
    PairStatus,
)
from apps.ddup.phone import to_e164
from apps.ddup.services import (
    DdupApprovalError,
    MergeError,
    activate_model_version,
    discover_nin_pairs,
    discover_phone_pairs,
    merge_member_pair,
    reject_pair,
    reverse_merge_decision,
)
from apps.reference_data.models import GeographicUnit
from apps.security.hashing import nin_hash
from apps.security.models import AuditEvent

# --- Fixtures ---------------------------------------------------------------

@pytest.fixture
def geo(db):
    """Minimal 7-level ladder for FK satisfaction."""
    nodes = {}
    for level, key, parent_key in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"T-{key.upper()}", name=key.title(),
            parent=nodes.get(parent_key), effective_from=date(2026, 1, 1),
        )
    return nodes


@pytest.fixture
def household(db, geo):
    return Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"], county=geo["c"],
        sub_county=geo["sc"], parish=geo["p"], village=geo["v"],
        urban_rural="rural",
    )


@pytest.fixture
def active_model(db):
    v = DdupModelVersion.objects.create(
        version=1, description="tier1 NIN deterministic",
        config={"tier1": {"member": "nin", "household": "head_nin+village"}},
        author="archer",
    )
    activate_model_version(v, approver="bob")
    v.refresh_from_db()
    return v


def _hash(nin: str) -> bytes:
    # Use the canonical project hash so the DB-side rows match what
    # apps.ingestion_hub.services._discover_stage_candidates would compute.
    return nin_hash(nin)


# --- Model-version dual approval -------------------------------------------

class TestModelVersionApproval:
    def test_activate_happy_path(self, db):
        v = DdupModelVersion.objects.create(version=1, config={}, author="alice")
        activate_model_version(v, approver="bob")
        v.refresh_from_db()
        assert v.status == ModelStatus.ACTIVE
        assert v.approved_by == "bob"

    def test_author_cannot_approve_own(self, db):
        v = DdupModelVersion.objects.create(version=1, config={}, author="alice")
        with pytest.raises(DdupApprovalError, match="differ"):
            activate_model_version(v, approver="alice")

    def test_activating_v2_retires_v1(self, db):
        v1 = DdupModelVersion.objects.create(version=1, config={}, author="alice")
        activate_model_version(v1, approver="bob")
        v2 = DdupModelVersion.objects.create(version=2, config={}, author="alice")
        activate_model_version(v2, approver="bob")
        v1.refresh_from_db()
        v2.refresh_from_db()
        assert v1.status == ModelStatus.RETIRED
        assert v2.status == ModelStatus.ACTIVE


# --- AC-DDUP-NIN discovery --------------------------------------------------

class TestNinDiscovery:
    def test_two_members_with_same_nin_hash_create_pair(self, household, active_model):
        h = _hash("CM1234567890AB")
        m1 = Member.objects.create(household=household, line_number=1, surname="A",
                                   first_name="One", sex="M", nin_hash=h)
        m2 = Member.objects.create(household=household, line_number=2, surname="B",
                                   first_name="Two", sex="F", nin_hash=h)
        created = discover_nin_pairs(actor="system")
        assert len(created) == 1
        pair = created[0]
        assert pair.tier == 1
        assert pair.match_reason == "nin"
        assert {pair.record_a_id, pair.record_b_id} == {m1.id, m2.id}
        assert pair.status == PairStatus.PENDING

    def test_idempotent(self, household, active_model):
        h = _hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="M", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", nin_hash=h)
        first = discover_nin_pairs(actor="system")
        second = discover_nin_pairs(actor="system")
        assert len(first) == 1
        assert second == []

    def test_three_way_creates_three_pairs(self, household, active_model):
        h = _hash("CM1234567890AB")
        for i in range(3):
            Member.objects.create(household=household, line_number=i + 1,
                                  surname=f"S{i}", first_name=f"F{i}", sex="M", nin_hash=h)
        created = discover_nin_pairs(actor="system")
        assert len(created) == 3  # 3-choose-2

    def test_soft_deleted_member_ignored(self, household, active_model):
        h = _hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="M", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="B",
                              first_name="Two", sex="F", nin_hash=h, is_deleted=True)
        created = discover_nin_pairs(actor="system")
        assert created == []

    def test_no_nin_hash_excluded(self, household, active_model):
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="M", nin_hash=None)
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", nin_hash=None)
        assert discover_nin_pairs(actor="system") == []


# --- AC-DDUP-MERGE-COMMIT ---------------------------------------------------

class TestMergeCommit:
    def _build_pair(self, household):
        h = _hash("CM1234567890AB")
        a = Member.objects.create(household=household, line_number=1, surname="OLDsurname",
                                  first_name="James", sex="M", nin_hash=h, nin_last4="00AB",
                                  telephone_1="+256700000001")
        b = Member.objects.create(household=household, line_number=2, surname="Okot",
                                  first_name="James", sex="M", nin_hash=h, nin_last4="00AB",
                                  telephone_1="+256700000002")
        return discover_nin_pairs(actor="system")[0], a, b

    def test_merge_keeps_survivor_and_soft_deletes_loser(self, household, active_model):
        pair, a, b = self._build_pair(household)
        survivor_id = b.id  # pick b as the cleaner record
        merge_member_pair(pair, surviving_id=survivor_id,
                          chosen_field_values={"surname": "Okot", "telephone_1": "+256700000002"},
                          actor="op-1", note="single NIN match")

        survivor = Member.objects.get(id=survivor_id)
        loser = Member.objects.get(id=a.id if survivor_id == b.id else b.id)
        pair.refresh_from_db()

        assert survivor.is_deleted is False
        assert survivor.surname == "Okot"
        assert loser.is_deleted is True
        assert loser.deleted_at is not None
        assert loser.merged_into_id == survivor.id
        assert pair.status == PairStatus.MERGED

    def test_household_head_member_re_points_to_survivor(self, household, active_model):
        pair, a, b = self._build_pair(household)
        household.head_member = a
        household.save()
        merge_member_pair(pair, surviving_id=b.id, chosen_field_values={},
                          actor="op-1", note="")
        household.refresh_from_db()
        assert household.head_member_id == b.id

    def test_merge_writes_audit_event(self, household, active_model):
        pair, a, b = self._build_pair(household)
        prior = AuditEvent.objects.count()
        merge_member_pair(pair, surviving_id=b.id, chosen_field_values={},
                          actor="op-1", note="audit-test")
        new_events = AuditEvent.objects.order_by("occurred_at")[prior:]
        merge_events = [e for e in new_events if e.action == "merge"]
        assert len(merge_events) == 1
        assert merge_events[0].actor_id == "op-1"
        assert merge_events[0].entity_id == b.id

    def test_merge_decision_records_reverse_window(self, household, active_model):
        pair, a, b = self._build_pair(household)
        decision = merge_member_pair(pair, surviving_id=b.id, chosen_field_values={},
                                     actor="op-1", note="")
        assert decision.action == MergeAction.MERGE
        assert decision.reverse_window_until is not None

    def test_cannot_merge_a_non_pending_pair(self, household, active_model):
        pair, a, b = self._build_pair(household)
        merge_member_pair(pair, surviving_id=b.id, chosen_field_values={}, actor="op-1")
        with pytest.raises(MergeError, match="PENDING"):
            merge_member_pair(pair, surviving_id=b.id, chosen_field_values={}, actor="op-1")

    def test_surviving_id_must_be_in_pair(self, household, active_model):
        pair, a, b = self._build_pair(household)
        with pytest.raises(MergeError, match="surviving_id"):
            merge_member_pair(pair, surviving_id="01OUTSIDETHEPAIR0000000000",
                              chosen_field_values={}, actor="op-1")


# --- AC-DDUP-REJECT-LEARN ---------------------------------------------------

class TestReject:
    def test_reject_records_reason_and_prevents_requeue(self, household, active_model):
        h = _hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="M", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", nin_hash=h)
        pair = discover_nin_pairs(actor="system")[0]
        reject_pair(pair, actor="op-1", reason="legitimate-name-sharing")
        pair.refresh_from_db()
        assert pair.status == PairStatus.REJECTED

        # Re-discovery does not create a new pair for the same two members.
        again = discover_nin_pairs(actor="system")
        assert again == []

    def test_reject_requires_reason(self, household, active_model):
        h = _hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="M", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", nin_hash=h)
        pair = discover_nin_pairs(actor="system")[0]
        with pytest.raises(MergeError, match="reason"):
            reject_pair(pair, actor="op-1", reason="")


# --- Tier 2 phone normalisation + discovery (US-S2-007) --------------------

class TestPhoneNormalisation:
    @pytest.mark.parametrize("raw,expected", [
        ("+256700000001", "+256700000001"),
        ("0700000001",    "+256700000001"),
        ("256700000001",  "+256700000001"),
        ("+256 700 000 001", "+256700000001"),
        ("0700-000-001",  "+256700000001"),
    ])
    def test_accepts_valid_forms(self, raw, expected):
        assert to_e164(raw) == expected

    @pytest.mark.parametrize("raw", [
        "", None,
        "+1 555 555 5555",        # non-UG
        "0500000001",             # 5 isn't an accepted Ugandan prefix
        "07000000",               # too short
        "07000000012",            # too long
        "abc",                    # non-numeric
    ])
    def test_rejects_invalid(self, raw):
        assert to_e164(raw) is None


class TestPhoneDiscovery:
    def test_two_members_with_same_phone_create_tier2_pair(self, household, active_model):
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="M", telephone_1="+256700000001")
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", telephone_1="0700000001")  # equivalent normalised
        created = discover_phone_pairs(actor="system")
        assert len(created) == 1
        assert created[0].tier == 2
        assert created[0].match_reason == "phone"

    def test_unparseable_phone_excluded(self, household, active_model):
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="M", telephone_1="abc")
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", telephone_1="abc")
        assert discover_phone_pairs(actor="system") == []

    def test_idempotent(self, household, active_model):
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="M", telephone_1="+256700000001")
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", telephone_1="+256700000001")
        first = discover_phone_pairs(actor="system")
        second = discover_phone_pairs(actor="system")
        assert len(first) == 1 and second == []

    def test_tier1_pair_not_redisco_as_tier2(self, household, active_model):
        # Same NIN AND same phone → tier 1 wins; the (a,b) uniqueness
        # constraint blocks a second tier-2 row for the same pair.
        h = _hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A", first_name="One",
                              sex="M", nin_hash=h, telephone_1="+256700000001")
        Member.objects.create(household=household, line_number=2, surname="B", first_name="Two",
                              sex="F", nin_hash=h, telephone_1="+256700000001")
        tier1 = discover_nin_pairs(actor="system")
        tier2 = discover_phone_pairs(actor="system")
        assert len(tier1) == 1 and tier1[0].tier == 1
        assert tier2 == []  # already represented as a tier-1 pair


# --- SAD §4.3.2 — 30-day un-merge window ----------------------------------

class TestReverseMerge:
    """Within the 30-day reverse window, a MERGE decision can be undone:
    loser restored, surviving's fields rolled back, household head
    pointers restored. Outside the window — locked."""

    def _make_merge(self, household, active_model, *, with_overrides=False):
        from apps.security.hashing import nin_hash as _nin_hash
        h = _nin_hash("CM1234567890AB")
        a = Member.objects.create(
            household=household, line_number=1, surname="OriginalSurname",
            first_name="James", sex="M", nin_hash=h, nin_last4="00AB",
        )
        b = Member.objects.create(
            household=household, line_number=2, surname="Okot",
            first_name="James", sex="M", nin_hash=h, nin_last4="00AB",
        )
        pair = discover_nin_pairs(actor="system")[0]
        # b is the survivor; capture the surviving's pre-merge surname
        # so the test can verify reverse restores it.
        chosen = {"surname": "ChosenSurname"} if with_overrides else {}
        decision = merge_member_pair(
            pair, surviving_id=b.id, chosen_field_values=chosen,
            actor="op-1", note="initial merge",
        )
        return pair, decision, a, b

    def test_reverse_restores_loser(self, household, active_model):
        pair, decision, a, b = self._make_merge(household, active_model)
        reverse_merge_decision(
            decision, actor="reviewer-1", reason="enumerator misidentified pair",
        )
        a.refresh_from_db()
        b.refresh_from_db()
        pair.refresh_from_db()
        assert a.is_deleted is False
        assert a.deleted_at is None
        assert a.merged_into_id is None
        # b is still active (survivor was b).
        assert b.is_deleted is False
        # Pair flipped back to PENDING for re-decision.
        assert pair.status == PairStatus.PENDING

    def test_reverse_restores_surviving_overrides(self, household, active_model):
        pair, decision, a, b = self._make_merge(
            household, active_model, with_overrides=True,
        )
        b.refresh_from_db()
        assert b.surname == "ChosenSurname"
        reverse_merge_decision(
            decision, actor="reviewer-1", reason="wrong field choice",
        )
        b.refresh_from_db()
        # The surviving member's surname is restored to its pre-merge value.
        assert b.surname == "Okot"

    def test_reverse_restores_household_head_pointer(
        self, household, active_model,
    ):
        # Set household head BEFORE merge so merge re-points it.
        from apps.security.hashing import nin_hash as _nin_hash
        h = _nin_hash("CM1234567890AB")
        a = Member.objects.create(
            household=household, line_number=1, surname="X", first_name="A",
            sex="M", nin_hash=h, nin_last4="00AB",
        )
        b = Member.objects.create(
            household=household, line_number=2, surname="X", first_name="B",
            sex="M", nin_hash=h, nin_last4="00AB",
        )
        household.head_member = a
        household.save()
        pair = discover_nin_pairs(actor="system")[0]
        decision = merge_member_pair(
            pair, surviving_id=b.id, chosen_field_values={},
            actor="op-1", note="",
        )
        household.refresh_from_db()
        assert household.head_member_id == b.id  # re-pointed

        reverse_merge_decision(
            decision, actor="reviewer-1", reason="head identity wrong",
        )
        household.refresh_from_db()
        assert household.head_member_id == a.id  # restored

    def test_reverse_records_actor_reason_timestamp(
        self, household, active_model,
    ):
        _, decision, _, _ = self._make_merge(household, active_model)
        reverse_merge_decision(
            decision, actor="reviewer-1", reason="ambiguous identity",
        )
        decision.refresh_from_db()
        assert decision.reversed_at is not None
        assert decision.reversed_by == "reviewer-1"
        assert "ambiguous" in decision.reversed_reason

    def test_reverse_emits_unmerge_audit_event(self, household, active_model):
        pair, decision, _, _ = self._make_merge(household, active_model)
        reverse_merge_decision(decision, actor="rv", reason="r")
        ev = AuditEvent.objects.filter(
            action="unmerge", entity_type="match_pair", entity_id=pair.id,
        ).first()
        assert ev is not None
        assert ev.actor_id == "rv"

    def test_cannot_reverse_outside_window(self, household, active_model):
        from datetime import timedelta

        from django.utils import timezone
        _, decision, _, _ = self._make_merge(household, active_model)
        # Push reverse_window_until into the past.
        decision.reverse_window_until = timezone.now() - timedelta(seconds=1)
        decision.save(update_fields=["reverse_window_until"])
        with pytest.raises(MergeError, match="window closed"):
            reverse_merge_decision(decision, actor="late", reason="too late")

    def test_cannot_reverse_already_reversed(self, household, active_model):
        _, decision, _, _ = self._make_merge(household, active_model)
        reverse_merge_decision(decision, actor="rv", reason="first")
        with pytest.raises(MergeError, match="already reversed"):
            reverse_merge_decision(decision, actor="rv", reason="second")

    def test_reverse_requires_reason(self, household, active_model):
        _, decision, _, _ = self._make_merge(household, active_model)
        with pytest.raises(MergeError, match="non-empty reason"):
            reverse_merge_decision(decision, actor="rv", reason="")

    def test_cannot_reverse_a_reject_decision(self, household, active_model):
        from apps.ddup.services import reject_pair
        from apps.security.hashing import nin_hash as _nin_hash
        h = _nin_hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="X",
                              first_name="A", sex="M", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="X",
                              first_name="B", sex="M", nin_hash=h)
        pair = discover_nin_pairs(actor="system")[0]
        decision = reject_pair(pair, actor="op", reason="not duplicates")
        with pytest.raises(MergeError, match="only MERGE"):
            reverse_merge_decision(decision, actor="rv", reason="r")


# --- US-S6-001 — reverse-merge surface (API + admin) -----------------------

class TestReverseMergeApi:
    """Per US-S6-001: POST /api/v1/ddup/merge-decisions/{id}/reverse/
    triggers the same reverse_merge_decision() service that S5-003
    shipped. Guards (window, double-reverse, reason) surface as 400."""

    def _make_merge(self, household, active_model):
        from apps.ddup.services import merge_member_pair
        from apps.security.hashing import nin_hash as _nin_hash
        h = _nin_hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A",
                              first_name="X", sex="M", nin_hash=h, nin_last4="00AB")
        b = Member.objects.create(household=household, line_number=2, surname="B",
                                  first_name="Y", sex="M", nin_hash=h, nin_last4="00AB")
        pair = discover_nin_pairs(actor="system")[0]
        return merge_member_pair(pair, surviving_id=b.id,
                                 chosen_field_values={}, actor="op-1", note="")

    def test_reverse_via_api(self, household, active_model, django_user_model):
        from rest_framework.test import APIClient
        decision = self._make_merge(household, active_model)
        u = django_user_model.objects.create_user(
            username="reviewer", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.post(
            f"/api/v1/ddup/merge-decisions/{decision.id}/reverse/",
            data={"actor": "reviewer-2", "reason": "id mismatch"},
            format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["reversed_at"] is not None
        assert r.data["reversed_by"] == "reviewer-2"
        assert "mismatch" in r.data["reversed_reason"]

    def test_reverse_api_400_outside_window(
        self, household, active_model, django_user_model,
    ):
        from datetime import timedelta

        from django.utils import timezone
        from rest_framework.test import APIClient
        decision = self._make_merge(household, active_model)
        decision.reverse_window_until = timezone.now() - timedelta(seconds=1)
        decision.save(update_fields=["reverse_window_until"])
        u = django_user_model.objects.create_user(
            username="late", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.post(
            f"/api/v1/ddup/merge-decisions/{decision.id}/reverse/",
            data={"actor": "late", "reason": "too late"},
            format="json",
        )
        assert r.status_code == 400
        assert "window closed" in r.data["detail"]

    def test_reverse_api_requires_reason(
        self, household, active_model, django_user_model,
    ):
        from rest_framework.test import APIClient
        decision = self._make_merge(household, active_model)
        u = django_user_model.objects.create_user(
            username="lazy", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        # Empty reason -> DRF serializer rejects (CharField required-non-blank).
        r = c.post(
            f"/api/v1/ddup/merge-decisions/{decision.id}/reverse/",
            data={"actor": "lazy", "reason": ""},
            format="json",
        )
        assert r.status_code == 400


class TestReverseMergeAdmin:
    """The admin bulk action wraps the same service so audit chain and
    guards are identical to the API surface."""

    @pytest.fixture
    def admin_client(self, db, django_user_model):
        from django.test import Client
        u = django_user_model.objects.create_user(
            username="reviewer-admin", password="p",
            is_staff=True, is_superuser=True,
        )
        c = Client()
        c.force_login(u)
        return c

    def test_bulk_reverse_flips_pair_back_to_pending(
        self, admin_client, household, active_model,
    ):
        from apps.ddup.services import merge_member_pair
        from apps.security.hashing import nin_hash as _nin_hash
        h = _nin_hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A",
                              first_name="X", sex="M", nin_hash=h, nin_last4="00AB")
        b = Member.objects.create(household=household, line_number=2, surname="B",
                                  first_name="Y", sex="M", nin_hash=h, nin_last4="00AB")
        pair = discover_nin_pairs(actor="system")[0]
        decision = merge_member_pair(pair, surviving_id=b.id,
                                     chosen_field_values={}, actor="op-1", note="")
        r = admin_client.post("/admin/ddup/mergedecision/", data={
            "action": "admin_reverse_merge",
            "_selected_action": [decision.id],
        })
        assert r.status_code in (200, 302)
        decision.refresh_from_db()
        pair.refresh_from_db()
        assert decision.reversed_at is not None
        assert pair.status == PairStatus.PENDING

    def test_bulk_reverse_skips_non_merge_actions(
        self, admin_client, household, active_model,
    ):
        from apps.ddup.services import reject_pair
        from apps.security.hashing import nin_hash as _nin_hash
        h = _nin_hash("CM1234567890AB")
        Member.objects.create(household=household, line_number=1, surname="A",
                              first_name="X", sex="M", nin_hash=h)
        Member.objects.create(household=household, line_number=2, surname="B",
                              first_name="Y", sex="M", nin_hash=h)
        pair = discover_nin_pairs(actor="system")[0]
        decision = reject_pair(pair, actor="op", reason="not duplicates")
        admin_client.post("/admin/ddup/mergedecision/", data={
            "action": "admin_reverse_merge",
            "_selected_action": [decision.id],
        })
        decision.refresh_from_db()
        # REJECT decision unchanged — admin action skipped it.
        assert decision.reversed_at is None


# --- US-S7-003 — tier 3 probabilistic discovery ---------------------------


class TestSimilarityPrimitives:
    """Self-contained similarity functions in apps.ddup.similarity.
    These are the building blocks composite_score combines into a
    weighted match score."""

    def test_jaro_winkler_exact_match(self):
        from apps.ddup.similarity import jaro_winkler
        assert jaro_winkler("OKELLO", "OKELLO") == 1.0

    def test_jaro_winkler_close_variants(self):
        """OCHELLO vs OKELLO should score high — same length, single
        substitution, common prefix."""
        from apps.ddup.similarity import jaro_winkler
        assert jaro_winkler("OCHELLO", "OKELLO") > 0.85

    def test_jaro_winkler_empty_strings(self):
        from apps.ddup.similarity import jaro_winkler
        assert jaro_winkler("", "") == 1.0
        assert jaro_winkler("X", "") == 0.0
        assert jaro_winkler("", "Y") == 0.0

    def test_year_proximity_same_year(self):
        from datetime import date

        from apps.ddup.similarity import year_proximity
        assert year_proximity(date(1980, 1, 1), date(1980, 12, 31)) == 1.0

    def test_year_proximity_one_year_apart(self):
        from datetime import date

        from apps.ddup.similarity import year_proximity
        # max_years=2 -> 1 year apart = 0.5
        assert year_proximity(date(1980, 1, 1), date(1981, 1, 1)) == 0.5

    def test_year_proximity_missing_dob_yields_zero(self):
        from datetime import date

        from apps.ddup.similarity import year_proximity
        assert year_proximity(None, date(1980, 1, 1)) == 0.0
        assert year_proximity(date(1980, 1, 1), None) == 0.0

    def test_exact_treats_empty_as_missing(self):
        from apps.ddup.similarity import exact
        # Two empties should NOT be a match — would collapse blank villages.
        assert exact("", "") == 0.0
        assert exact(None, None) == 0.0
        assert exact("V1", "V1") == 1.0
        assert exact("V1", "V2") == 0.0

    def test_composite_score_weighted_average(self):
        from apps.ddup.similarity import composite_score
        # 0.5 weight at 1.0 + 0.5 weight at 0.0 = 0.5
        assert composite_score([(0.5, 1.0), (0.5, 0.0)]) == 0.5
        # Empty -> 0.0 not divide-by-zero
        assert composite_score([]) == 0.0
        # All-zero weights -> 0.0 defensively
        assert composite_score([(0, 0.5), (0, 1.0)]) == 0.0


class TestProbabilisticDiscovery:
    """Tier 3: composite-score matching within village blocks.
    Different households (so neither NIN nor phone tier 1/2 fires)
    but same village + very similar names + same DOB year + same sex
    should cross the 0.85 default threshold."""

    @pytest.fixture
    def two_households_same_village(self, db, geo):
        # Two households sharing the same village node from `geo`.
        h1 = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
            village=geo["v"], urban_rural="rural",
        )
        h2 = Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
            village=geo["v"], urban_rural="rural",
        )
        return h1, h2

    @pytest.fixture
    def other_village_household(self, db, geo):
        # A second village, same parish — for the blocking test.
        v2 = GeographicUnit.objects.create(
            level="village", code="T-V2", name="other-village",
            parent=geo["p"], effective_from=date(2026, 1, 1),
        )
        return Household.objects.create(
            region=geo["r"], sub_region=geo["sr"], district=geo["d"],
            county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
            village=v2, urban_rural="rural",
        )

    def test_high_similarity_pair_within_village(
        self, two_households_same_village, active_model,
    ):
        from apps.ddup.services import discover_probabilistic_pairs
        h1, h2 = two_households_same_village
        m1 = Member.objects.create(
            household=h1, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="M", date_of_birth=date(1980, 1, 1),
        )
        m2 = Member.objects.create(
            household=h2, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="M", date_of_birth=date(1980, 6, 15),
        )
        created = discover_probabilistic_pairs(actor="system")
        assert len(created) == 1
        pair = created[0]
        assert pair.tier == 3
        assert pair.match_reason == "probabilistic"
        # Composite is recorded and at/above threshold.
        assert pair.composite_score is not None
        assert float(pair.composite_score) >= 0.85
        # Per-field breakdown stored for reviewer transparency.
        assert pair.per_field_scores["surname"] == 1.0
        assert pair.per_field_scores["village"] == 1.0
        # Both members in scope.
        assert {pair.record_a_id, pair.record_b_id} == {m1.id, m2.id}

    def test_low_similarity_pair_skipped(
        self, two_households_same_village, active_model,
    ):
        from apps.ddup.services import discover_probabilistic_pairs
        h1, h2 = two_households_same_village
        Member.objects.create(
            household=h1, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="M", date_of_birth=date(1980, 1, 1),
        )
        Member.objects.create(
            household=h2, line_number=1, surname="NAKATO",
            first_name="ALICE", sex="F", date_of_birth=date(1995, 1, 1),
        )
        assert discover_probabilistic_pairs(actor="system") == []

    def test_village_blocking_prevents_cross_village_pair(
        self, two_households_same_village, other_village_household,
        active_model,
    ):
        """Two identical-looking members in different villages should
        NOT pair via tier 3 — the blocking is by village_id."""
        from apps.ddup.services import discover_probabilistic_pairs
        h1, _ = two_households_same_village
        h_other = other_village_household
        Member.objects.create(
            household=h1, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="M", date_of_birth=date(1980, 1, 1),
        )
        Member.objects.create(
            household=h_other, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="M", date_of_birth=date(1980, 1, 1),
        )
        # Each village now has 1 member — no within-village comparison
        # possible.
        assert discover_probabilistic_pairs(actor="system") == []

    def test_tier1_pair_not_redisco_as_tier3(
        self, two_households_same_village, active_model,
    ):
        """Same NIN -> tier 1 wins; the (a,b) uniqueness constraint
        blocks a tier-3 row for the same pair."""
        from apps.ddup.services import (
            discover_nin_pairs,
            discover_probabilistic_pairs,
        )
        h1, h2 = two_households_same_village
        h = _hash("CM1234567890AB")
        Member.objects.create(
            household=h1, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="M", date_of_birth=date(1980, 1, 1),
            nin_hash=h,
        )
        Member.objects.create(
            household=h2, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="M", date_of_birth=date(1980, 1, 1),
            nin_hash=h,
        )
        tier1 = discover_nin_pairs(actor="system")
        tier3 = discover_probabilistic_pairs(actor="system")
        assert len(tier1) == 1 and tier1[0].tier == 1
        assert tier3 == []  # already represented as tier 1

    def test_idempotent(self, two_households_same_village, active_model):
        from apps.ddup.services import discover_probabilistic_pairs
        h1, h2 = two_households_same_village
        for hh in (h1, h2):
            Member.objects.create(
                household=hh, line_number=1, surname="OKELLO",
                first_name="JAMES", sex="M", date_of_birth=date(1980, 1, 1),
            )
        first = discover_probabilistic_pairs(actor="system")
        second = discover_probabilistic_pairs(actor="system")
        assert len(first) == 1
        assert second == []

    def test_threshold_overridable_via_model_config(
        self, two_households_same_village, db,
    ):
        """A more permissive threshold should pull in pairs that the
        default 0.85 misses."""
        from apps.ddup.services import (
            activate_model_version,
            discover_probabilistic_pairs,
        )
        permissive = DdupModelVersion.objects.create(
            version=2, author="archer",
            config={"tier3": {"threshold": 0.5}},
        )
        activate_model_version(permissive, approver="bob")
        h1, h2 = two_households_same_village
        # Names diverge enough to score < 0.85 but probably > 0.5.
        Member.objects.create(
            household=h1, line_number=1, surname="OKELLO",
            first_name="JAMES", sex="M", date_of_birth=date(1980, 1, 1),
        )
        Member.objects.create(
            household=h2, line_number=1, surname="OKELO",
            first_name="JAMS", sex="M", date_of_birth=date(1985, 1, 1),
        )
        created = discover_probabilistic_pairs(actor="system")
        assert len(created) == 1
