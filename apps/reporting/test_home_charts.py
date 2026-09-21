"""Home-screen chart series (US-S24-HOME-CHARTS).

The home screen serves two readers: the coordinator orienting themselves
during the week, and whoever they print it for. That second reader is
what most of these cases are about — a chart that silently covers one
sub-region while reading as national is wrong in a way its reader cannot
detect, so scope correctness is tested harder than shape.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.data_management.models import Household, Member
from apps.dqa.models import DqaResult, DqaRule
from apps.partners.models import Partner, Programme
from apps.reference_data.models import GeographicUnit
from apps.referral.models import ProgrammeEnrolment
from apps.reporting.dashboard_views import (
    compute_home_charts,
    compute_operator_kpis,
    dqa_failures_by_rule,
    enrolments_by_programme,
    households_by_pmt_band,
    members_by_pmt_band,
)


@pytest.fixture
def geo(db):
    """Two full geographic ladders, so scoping has something to get
    wrong. Household requires the chain down to parish, so a fixture
    that stops at sub_region cannot save a row at all."""
    made = {}
    for code, name in [("HC-SR-A", "Acholi"), ("HC-SR-B", "Ankole")]:
        parent = None
        chain = {}
        levels = [
            ("region", f"R-{code}"), ("sub_region", code),
            ("district", f"D-{code}"), ("county", f"C-{code}"),
            ("sub_county", f"SC-{code}"), ("parish", f"P-{code}"),
        ]
        for level, unit_code in levels:
            parent = GeographicUnit.objects.create(
                level=level, code=unit_code, name=f"{name} {level}",
                parent=parent, effective_from=date(2026, 1, 1),
            )
            chain[level] = parent
        made[code] = chain
    return made


def _household(chain, band, *, members=0):
    hh = Household.objects.create(
        region=chain["region"], sub_region=chain["sub_region"],
        district=chain["district"], county=chain["county"],
        sub_county=chain["sub_county"], parish=chain["parish"],
        sub_region_code=chain["sub_region"].code,
        current_vulnerability_band=band,
    )
    for line in range(1, members + 1):
        Member.objects.create(
            household=hh, line_number=line,
            surname="Test", first_name=f"P{line}",
        )
    return hh


@pytest.fixture
def registry(geo, db):
    """A registry shaped so household count and member count DISAGREE.

    Acholi: 2 extreme poverty (5 people), 2 vulnerable (3 people).
    Ankole: 1 poverty (4 people).

    Note poverty has FEWER households than vulnerable but MORE people in
    them. That is not incidental — it is why both charts exist, and a
    fixture where the two rank the same way would let a bug that derives
    one from the other pass unnoticed.
    """
    a, b = geo["HC-SR-A"], geo["HC-SR-B"]
    return {
        "a1": _household(a, "extreme_poverty", members=3),
        "a2": _household(a, "extreme_poverty", members=2),
        "a3": _household(a, "vulnerable", members=2),
        "a4": _household(a, "vulnerable", members=1),
        "b1": _household(b, "poverty", members=4),
    }


@pytest.fixture
def national(django_user_model, db):
    """A superuser — unscoped, sees everything."""
    return django_user_model.objects.create_superuser(
        username="hc-national", password="p", email="n@example.com",
    )


def _counts(series):
    return {row["key"]: row["count"] for row in series}


# ---------------------------------------------------------------------------
# Bands


@pytest.mark.django_db
class TestHouseholdsByBand:
    def test_counts_by_band(self, national, registry):
        assert _counts(households_by_pmt_band(national)) == {
            "extreme_poverty": 2, "poverty": 1, "vulnerable": 2, "not_poor": 0,
        }

    def test_every_band_is_present_even_at_zero(self, national, registry):
        """Dropping an empty band would silently redraw the axis between
        one week and the next, so "nobody is in extreme poverty" and "we
        stopped measuring it" would look identical."""
        series = households_by_pmt_band(national)
        assert [r["key"] for r in series] == [
            "extreme_poverty", "poverty", "vulnerable", "not_poor",
        ]

    def test_bands_are_in_policy_order_not_count_order(self, national, registry):
        """An ordered scale sorted by size is no longer an ordered scale,
        and the sequential ramp would then encode nothing."""
        keys = [r["key"] for r in households_by_pmt_band(national)]
        assert keys.index("extreme_poverty") < keys.index("not_poor")

    def test_unscored_households_are_shown_not_dropped(self, national, geo):
        _household(geo["HC-SR-A"], "")
        series = households_by_pmt_band(national)
        assert _counts(series).get("") == 1
        assert any(r["label"] == "Not scored" for r in series)

    def test_a_band_outside_the_vocabulary_is_kept(self, national, geo):
        """An unrecognised value is a fact about the data, not something
        to hide — the same reasoning as the CSPro parser's `extra`."""
        _household(geo["HC-SR-A"], "some_new_band")
        assert _counts(households_by_pmt_band(national))["some_new_band"] == 1

    def test_labels_are_human_readable(self, national, registry):
        labels = {r["key"]: r["label"] for r in households_by_pmt_band(national)}
        assert labels["extreme_poverty"] == "Extreme poverty"


@pytest.mark.django_db
class TestMembersByBand:
    def test_members_are_counted_by_their_households_band(self, national, registry):
        assert _counts(members_by_pmt_band(national)) == {
            "extreme_poverty": 5, "poverty": 4, "vulnerable": 3, "not_poor": 0,
        }

    def test_it_is_not_derivable_from_the_household_chart(self, national, registry):
        """Which is the point of having both: household size varies by
        band, so 2 households can hold more people than 1 household in a
        band with twice the count."""
        hh = _counts(households_by_pmt_band(national))
        mem = _counts(members_by_pmt_band(national))
        # Fewer households, more people in them. A members chart derived
        # from the households chart would rank these the same way.
        assert hh["poverty"] < hh["vulnerable"], (hh, mem)
        assert mem["poverty"] > mem["vulnerable"], (hh, mem)

    def test_deleted_members_are_excluded(self, national, registry):
        member = Member.objects.filter(household=registry["a1"]).first()
        member.is_deleted = True
        member.save(update_fields=["is_deleted"])
        assert _counts(members_by_pmt_band(national))["extreme_poverty"] == 4


# ---------------------------------------------------------------------------
# Scope — the printed-chart correctness problem.


@pytest.mark.django_db
class TestDrillDown:
    def test_a_region_narrows_every_series(self, national, registry):
        drilled = compute_home_charts(national, region="HC-SR-A")
        assert _counts(drilled["households_by_pmt_band"])["extreme_poverty"] == 2
        assert _counts(drilled["households_by_pmt_band"])["poverty"] == 0
        assert _counts(drilled["members_by_pmt_band"])["poverty"] == 0

    def test_the_payload_echoes_the_region_it_covers(self, national, registry):
        """The screen prints this. A chart covering Acholi that reads as
        national is wrong in a way its reader cannot detect, so the
        payload has to be able to say which it is."""
        assert compute_home_charts(national, region="HC-SR-A")["region"] == "HC-SR-A"
        assert compute_home_charts(national)["region"] == ""

    def test_an_out_of_scope_region_yields_empty_not_an_error(
        self, django_user_model, registry, geo,
    ):
        from apps.security.models import OperatorScope

        user = django_user_model.objects.create_user(username="hc-scoped", password="p")
        OperatorScope.objects.create(
            user=user, scope_level="sub_region", scope_code="HC-SR-A",
            granted_by="test", active=True,
        )
        charts = compute_home_charts(user, region="HC-SR-B")
        assert _counts(charts["households_by_pmt_band"]) == {
            "extreme_poverty": 0, "poverty": 0, "vulnerable": 0, "not_poor": 0,
        }

    def test_a_scoped_operator_sees_only_their_own_sub_region(
        self, django_user_model, registry,
    ):
        from apps.security.models import OperatorScope

        user = django_user_model.objects.create_user(username="hc-acholi", password="p")
        OperatorScope.objects.create(
            user=user, scope_level="sub_region", scope_code="HC-SR-A",
            granted_by="test", active=True,
        )
        counts = _counts(compute_home_charts(user)["households_by_pmt_band"])
        assert counts["extreme_poverty"] == 2
        assert counts["poverty"] == 0, "Ankole is outside this operator's scope"


# ---------------------------------------------------------------------------
# DQA and enrolments


@pytest.mark.django_db
class TestDqaFailuresByRule:
    @pytest.fixture
    def failures(self, registry, db):
        rule = DqaRule.objects.create(
            rule_id="AC-TEST-RULE", version=1, severity="block",
            description="x", expression={}, status="active",
        )
        other = DqaRule.objects.create(
            rule_id="AC-OTHER-RULE", version=1, severity="flag",
            description="y", expression={}, status="active",
        )
        for _ in range(3):
            DqaResult.objects.create(
                rule=rule, record_type="household",
                record_id=registry["a1"].id, passed=False, severity="block",
            )
        DqaResult.objects.create(
            rule=other, record_type="member",
            record_id=f"{registry['a1'].id}:1", passed=False, severity="flag",
        )
        return rule, other

    def test_ranks_rules_by_finding_count(self, national, failures):
        rows = dqa_failures_by_rule(national)
        assert rows[0]["key"] == "AC-TEST-RULE"
        assert rows[0]["count"] == 3

    def test_member_findings_are_scoped_through_the_record_id_prefix(
        self, django_user_model, failures, registry,
    ):
        """DqaResult carries no FK to scope through — record_id is
        '<household>' or '<household>:<line>'. Both must resolve."""
        from apps.security.models import OperatorScope

        user = django_user_model.objects.create_user(username="hc-dqa", password="p")
        OperatorScope.objects.create(
            user=user, scope_level="sub_region", scope_code="HC-SR-A",
            granted_by="test", active=True,
        )
        keys = {r["key"] for r in dqa_failures_by_rule(user)}
        assert keys == {"AC-TEST-RULE", "AC-OTHER-RULE"}

    def test_findings_outside_scope_are_excluded(
        self, django_user_model, failures, registry,
    ):
        from apps.security.models import OperatorScope

        user = django_user_model.objects.create_user(username="hc-ankole", password="p")
        OperatorScope.objects.create(
            user=user, scope_level="sub_region", scope_code="HC-SR-B",
            granted_by="test", active=True,
        )
        assert dqa_failures_by_rule(user) == []

    def test_passes_are_never_counted(self, national, failures, registry):
        rule, _ = failures
        DqaResult.objects.create(
            rule=rule, record_type="household",
            record_id=registry["a1"].id, passed=True, severity="block",
        )
        assert dqa_failures_by_rule(national)[0]["count"] == 3

    def test_old_findings_fall_out_of_the_window(self, national, failures):
        DqaResult.objects.update(executed_at=timezone.now() - timedelta(days=90))
        assert dqa_failures_by_rule(national, days=30) == []


@pytest.mark.django_db
class TestEnrolmentsByProgramme:
    @pytest.fixture
    def programmes(self, registry, db):
        partner = Partner.objects.create(name="MGLSD", code="MGLSD", status="active")
        prog = Programme.objects.create(
            partner=partner, code="NUSAF", name="NUSAF IV", status="active",
        )
        for key in ("a1", "a2"):
            ProgrammeEnrolment.objects.create(
                programme=prog, household=registry[key], status="active",
                effective_date=date(2026, 1, 1),
            )
        return prog

    def test_counts_active_enrolments_per_programme(self, national, programmes):
        rows = enrolments_by_programme(national)
        assert rows == [{"key": "NUSAF", "label": "NUSAF IV", "count": 2}]

    def test_inactive_enrolments_are_excluded(self, national, programmes, registry):
        ProgrammeEnrolment.objects.create(
            programme=programmes, household=registry["a3"], status="exited",
            effective_date=date(2026, 1, 1),
        )
        assert enrolments_by_programme(national)[0]["count"] == 2

    def test_it_follows_the_drill_down(self, national, programmes, registry):
        assert enrolments_by_programme(national, region="HC-SR-B") == []


# ---------------------------------------------------------------------------
# The endpoint and the KPI additions.


@pytest.mark.django_db
class TestHomeChartsEndpoint:
    URL = "/api/v1/rpt/dashboards/home-charts/"

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_returns_every_series_in_one_round_trip(self, national, registry):
        r = self._client(national).get(self.URL)
        assert r.status_code == 200
        assert set(r.data) == {
            "region", "households_by_pmt_band", "members_by_pmt_band",
            "dih_backlog_by_reason", "dqa_failures_by_rule",
            "enrolments_by_programme",
        }

    def test_the_region_parameter_narrows_it(self, national, registry):
        r = self._client(national).get(self.URL, {"region": "HC-SR-A"})
        assert r.data["region"] == "HC-SR-A"
        assert _counts(r.data["households_by_pmt_band"])["poverty"] == 0

    def test_anonymous_is_refused(self):
        assert APIClient().get(self.URL).status_code in (401, 403)

    def test_one_audit_event_for_the_whole_band(self, national, registry):
        """Five separate dashboard endpoints would be five
        `dashboard_read` events for a single page view."""
        from apps.security.models import AuditEvent

        before = AuditEvent.objects.filter(entity_id="home_charts").count()
        self._client(national).get(self.URL)
        assert AuditEvent.objects.filter(entity_id="home_charts").count() == before + 1


@pytest.mark.django_db
class TestKpiCounts:
    def test_partner_and_programme_counts_are_added(self, national, db):
        partner = Partner.objects.create(name="P", code="P1", status="active")
        Programme.objects.create(
            partner=partner, code="X", name="X", status="active",
        )
        Programme.objects.create(
            partner=partner, code="Y", name="Y", status="closed",
        )
        kpis = compute_operator_kpis(national)
        assert kpis["partners_total"] == 1
        assert kpis["programmes_active"] == 1, "closed programmes are not active"

    def test_they_stay_national_under_a_drill_down(self, national, geo, db):
        """A partner organisation is not in a sub-region — the DRS counts
        beside them already set this precedent."""
        partner = Partner.objects.create(name="P", code="P1", status="active")
        Programme.objects.create(partner=partner, code="X", name="X", status="active")
        drilled = compute_operator_kpis(national, region="HC-SR-A")
        assert drilled["partners_total"] == 1
        assert drilled["programmes_active"] == 1
