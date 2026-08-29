"""Consent as an access attribute (G1).

The DRS extract gate previously excluded blocked members only from the
EMBEDDED member list; the household row — location, GPS, PMT band, assets —
was emitted regardless, so an extract without `embed_members` was not
consent-filtered at all.

These tests pin both the narrowness of the rules (un-captured consent must not
block, or the registry empties) and the household-level exclusion that was
missing.
"""

from datetime import date

import pytest

from apps.consent import access as consent_access
from apps.consent.models import ConsentPurpose, ConsentRecord, ConsentState
from apps.data_management.models import Household, Member
from apps.reference_data.models import GeographicUnit


@pytest.fixture
def geo(db):
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"C-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1),
        )
    return nodes


@pytest.fixture
def household_with_head(db, geo):
    hh = Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"],
        county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
        village=geo["v"], urban_rural="2", address_narrative="Plot 9",
    )
    head = Member.objects.create(
        household=hh, line_number=1, surname="Head", first_name="Of",
        sex="1", relationship_to_head="01",
    )
    other = Member.objects.create(
        household=hh, line_number=2, surname="Other", first_name="Member",
        sex="2", relationship_to_head="04",
    )
    hh.head_member = head
    hh.save(update_fields=["head_member"])
    return hh, head, other


@pytest.fixture
def research(db):
    return ConsentPurpose.objects.get(code="RESEARCH")


def _set(member, purpose, state):
    return ConsentRecord.objects.create(
        member=member, purpose=purpose, state=state, captured_via="WEB",
    )


@pytest.mark.django_db
class TestConsentAccessRules:

    @pytest.fixture(autouse=True)
    def _module_on(self, settings):
        # override_settings as a class decorator only works on
        # SimpleTestCase subclasses; pytest-django's settings fixture is
        # the equivalent for plain test classes.
        settings.CONSENT_MODULE_ENABLED = True

    def test_uncaptured_consent_does_not_block(self, household_with_head, research):
        """The registry has no ConsentRecord for households captured before
        consent existed. Blocking on absence would empty it."""
        hh, head, _ = household_with_head
        assert consent_access.blocked_member_ids(["RESEARCH"]) == set()
        assert consent_access.blocked_household_ids(["RESEARCH"]) == set()

    def test_withdrawn_member_is_blocked(self, household_with_head, research):
        hh, head, other = household_with_head
        _set(other, research, ConsentState.WITHDRAWN)
        assert other.id in consent_access.blocked_member_ids(["RESEARCH"])

    def test_refused_is_blocked_too(self, household_with_head, research):
        hh, head, other = household_with_head
        _set(other, research, ConsentState.REFUSED)
        assert other.id in consent_access.blocked_member_ids(["RESEARCH"])

    def test_pending_review_is_not_blocking(self, household_with_head, research):
        hh, head, other = household_with_head
        _set(other, research, ConsentState.PENDING_REVIEW)
        assert consent_access.blocked_member_ids(["RESEARCH"]) == set()

    def test_household_blocked_via_its_head(self, household_with_head, research):
        hh, head, _ = household_with_head
        _set(head, research, ConsentState.WITHDRAWN)
        assert hh.id in consent_access.blocked_household_ids(["RESEARCH"])

    def test_household_not_blocked_when_a_non_head_withdraws(
        self, household_with_head, research,
    ):
        """One adult opting out must not remove the whole household — the head
        speaks for household-level data, per apps.referral.services."""
        hh, head, other = household_with_head
        _set(other, research, ConsentState.WITHDRAWN)
        assert consent_access.blocked_household_ids(["RESEARCH"]) == set()

    def test_no_purposes_means_no_filtering(self, household_with_head, research):
        hh, head, _ = household_with_head
        _set(head, research, ConsentState.WITHDRAWN)
        assert consent_access.blocked_household_ids([]) == set()
        assert consent_access.blocked_member_ids([]) == set()

    def test_other_purpose_does_not_block(self, household_with_head, research):
        hh, head, _ = household_with_head
        _set(head, research, ConsentState.WITHDRAWN)
        # Withdrawing RESEARCH must not affect a REFERRAL-scoped extract.
        assert consent_access.blocked_household_ids(["REFERRAL"]) == set()

    def test_queryset_helpers_exclude(self, household_with_head, research):
        hh, head, other = household_with_head
        _set(head, research, ConsentState.WITHDRAWN)
        hh_qs = consent_access.exclude_blocked_households(
            Household.objects.all(), ["RESEARCH"])
        assert hh.id not in {h.id for h in hh_qs}
        m_qs = consent_access.exclude_blocked_members(
            Member.objects.all(), ["RESEARCH"])
        assert head.id not in {m.id for m in m_qs}
        assert other.id in {m.id for m in m_qs}


@pytest.mark.django_db
class TestInertWhenModuleOff:

    @pytest.fixture(autouse=True)
    def _module_off(self, settings):
        settings.CONSENT_MODULE_ENABLED = False

    def test_flag_off_blocks_nothing(self, household_with_head, research):
        hh, head, _ = household_with_head
        _set(head, research, ConsentState.WITHDRAWN)
        assert consent_access.blocked_member_ids(["RESEARCH"]) == set()
        assert consent_access.blocked_household_ids(["RESEARCH"]) == set()
