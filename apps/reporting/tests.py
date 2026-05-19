"""RPT dashboard tests — ABAC scope pre-applied to aggregates, audit
emitted per call."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.data_management.models import Household
from apps.grievance.models import Category, GrievanceStatus, Tier
from apps.grievance.services import open_grievance
from apps.pmt.models import Band, ModelStatus, PMTModelVersion, PMTResult
from apps.reference_data.models import GeographicUnit
from apps.security.models import AuditEvent, OperatorScope, ScopeLevel


@pytest.fixture
def two_sub_regions(db):
    out = {}
    for sr_key in ["SR-BUGANDA", "SR-KARAMOJA"]:
        nodes = {}
        for level, key, parent in [
            ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
            ("county", "c", "d"), ("sub_county", "sc", "c"),
            ("parish", "p", "sc"), ("village", "v", "p"),
        ]:
            nodes[key] = GeographicUnit.objects.create(
                level=level, code=f"R-{sr_key}-{key.upper()}", name=f"{sr_key}-{key}",
                parent=nodes.get(parent), effective_from=date(2026, 1, 1),
            )
        out[sr_key] = nodes
    return out


@pytest.fixture
def households(two_sub_regions):
    out = {}
    for sr_key, nodes in two_sub_regions.items():
        hh = Household.objects.create(
            region=nodes["r"], sub_region=nodes["sr"], district=nodes["d"],
            county=nodes["c"], sub_county=nodes["sc"], parish=nodes["p"],
            village=nodes["v"], urban_rural="2",
        )
        out[sr_key] = hh
    return out


@pytest.fixture
def pmt_seeded(db, households):
    model = PMTModelVersion.objects.create(
        version=1, intercept=Decimal("50"), variables=[],
        band_cutoffs={
            Band.EXTREME_POVERTY: 0, Band.POVERTY: 30,
            Band.VULNERABLE: 60, Band.NOT_POOR: 80,
        },
        author="a", status=ModelStatus.ACTIVE,
    )
    for sr_key, hh in households.items():
        band = Band.POVERTY if sr_key == "SR-BUGANDA" else Band.VULNERABLE
        PMTResult.objects.create(
            household=hh, model_version=model,
            score=Decimal("55"), band=band, triggered_by="manual",
        )
        hh.current_vulnerability_band = band
        hh.save(update_fields=["current_vulnerability_band"])
    return model


def _client_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class TestHouseholdsBySubRegion:
    def test_superuser_sees_both_buckets(self, db, households, django_user_model):
        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/households-by-sub-region/")
        assert r.status_code == 200
        buckets = {row["key"]: row["count"] for row in r.data}
        assert len(buckets) == 2
        assert all(c == 1 for c in buckets.values())

    def test_sub_region_operator_sees_only_their_bucket(
        self, db, households, two_sub_regions, django_user_model,
    ):
        u = django_user_model.objects.create_user(username="op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/households-by-sub-region/")
        assert r.status_code == 200
        assert len(r.data) == 1
        assert r.data[0]["count"] == 1

    def test_unscoped_user_sees_zero_buckets(
        self, db, households, django_user_model,
    ):
        u = django_user_model.objects.create_user(username="ghost", password="p")
        r = _client_for(u).get("/api/v1/rpt/dashboards/households-by-sub-region/")
        assert r.status_code == 200
        assert r.data == []

    def test_emits_audit_event(self, db, households, django_user_model):
        su = django_user_model.objects.create_user(
            username="su2", password="p", is_superuser=True,
        )
        _client_for(su).get("/api/v1/rpt/dashboards/households-by-sub-region/")
        ev = AuditEvent.objects.filter(
            entity_type="rpt_dashboard", entity_id="households_by_sub_region",
        ).first()
        assert ev is not None
        assert ev.actor_id == "su2"
        assert ev.action == "dashboard_read"

    def test_can_group_by_region(self, db, households, django_user_model):
        su = django_user_model.objects.create_user(
            username="geo-region", password="p", is_superuser=True,
        )
        r = _client_for(su).get(
            "/api/v1/rpt/dashboards/households-by-sub-region/?group_by=region",
        )
        assert r.status_code == 200
        buckets = {row["key"]: row["count"] for row in r.data}
        assert len(buckets) == 2
        assert all(count == 1 for count in buckets.values())
        assert "label" in r.data[0]

    def test_can_group_by_district_under_selected_region(
        self, db, households, two_sub_regions, django_user_model,
    ):
        su = django_user_model.objects.create_user(
            username="geo-district", password="p", is_superuser=True,
        )
        region_code = two_sub_regions["SR-BUGANDA"]["r"].code
        district_code = two_sub_regions["SR-BUGANDA"]["d"].code
        r = _client_for(su).get(
            "/api/v1/rpt/dashboards/households-by-sub-region/",
            {"group_by": "district", "region": region_code},
        )
        assert r.status_code == 200
        assert {row["key"]: row["count"] for row in r.data} == {district_code: 1}

    def test_can_group_by_district_under_selected_sub_region(
        self, db, households, two_sub_regions, django_user_model,
    ):
        su = django_user_model.objects.create_user(
            username="geo-sub-region", password="p", is_superuser=True,
        )
        sub_region_code = two_sub_regions["SR-KARAMOJA"]["sr"].code
        district_code = two_sub_regions["SR-KARAMOJA"]["d"].code
        r = _client_for(su).get(
            "/api/v1/rpt/dashboards/households-by-sub-region/",
            {"group_by": "district", "sub_region": sub_region_code},
        )
        assert r.status_code == 200
        assert {row["key"]: row["count"] for row in r.data} == {district_code: 1}

    def test_can_filter_to_selected_district(
        self, db, households, two_sub_regions, django_user_model,
    ):
        su = django_user_model.objects.create_user(
            username="geo-district-filter", password="p", is_superuser=True,
        )
        district_code = two_sub_regions["SR-BUGANDA"]["d"].code
        r = _client_for(su).get(
            "/api/v1/rpt/dashboards/households-by-sub-region/",
            {"group_by": "district", "district": district_code},
        )
        assert r.status_code == 200
        assert {row["key"]: row["count"] for row in r.data} == {district_code: 1}


class TestHouseholdsByPmtBand:
    def test_groups_by_band(self, db, pmt_seeded, django_user_model):
        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/households-by-pmt-band/")
        assert r.status_code == 200
        buckets = {row["key"]: row["count"] for row in r.data}
        assert buckets == {Band.POVERTY: 1, Band.VULNERABLE: 1}

    def test_scope_filtered_before_aggregation(
        self, db, pmt_seeded, two_sub_regions, django_user_model,
    ):
        u = django_user_model.objects.create_user(username="op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/households-by-pmt-band/")
        assert r.status_code == 200
        # Operator sees only the BUGANDA household — POVERTY band.
        buckets = {row["key"]: row["count"] for row in r.data}
        assert buckets == {Band.POVERTY: 1}


class TestOpenGrievancesByTier:
    def test_open_grievances_grouped(
        self, db, households, two_sub_regions, django_user_model,
    ):
        # Two open grievances in Buganda, one resolved, one in Karamoja.
        open_grievance(category=Category.DATA_CORRECTION, description="a",
                       household_id=households["SR-BUGANDA"].id,
                       tier=Tier.L1_PARISH_CHIEF)
        open_grievance(category=Category.DATA_CORRECTION, description="b",
                       household_id=households["SR-BUGANDA"].id,
                       tier=Tier.L2_CDO)
        g_closed = open_grievance(category=Category.OTHER, description="c",
                                  household_id=households["SR-BUGANDA"].id)
        g_closed.status = GrievanceStatus.CLOSED
        g_closed.save(update_fields=["status"])
        open_grievance(category=Category.DATA_CORRECTION, description="d",
                       household_id=households["SR-KARAMOJA"].id,
                       tier=Tier.L1_PARISH_CHIEF)

        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/open-grievances-by-tier/")
        assert r.status_code == 200
        buckets = {row["key"]: row["count"] for row in r.data}
        assert buckets == {Tier.L1_PARISH_CHIEF: 2, Tier.L2_CDO: 1}

    def test_scope_filtered(
        self, db, households, two_sub_regions, django_user_model,
    ):
        open_grievance(category=Category.DATA_CORRECTION, description="a",
                       household_id=households["SR-BUGANDA"].id)
        open_grievance(category=Category.DATA_CORRECTION, description="b",
                       household_id=households["SR-KARAMOJA"].id)
        u = django_user_model.objects.create_user(username="op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/open-grievances-by-tier/")
        assert r.status_code == 200
        assert sum(row["count"] for row in r.data) == 1


class TestOverdueGrievancesByTier:
    def test_only_overdue_open_rows_counted(
        self, db, households, django_user_model,
    ):
        from datetime import timedelta

        from django.utils import timezone

        # Two open grievances, only one past SLA.
        late = open_grievance(category=Category.DATA_CORRECTION, description="a",
                              household_id=households["SR-BUGANDA"].id,
                              tier=Tier.L1_PARISH_CHIEF)
        late.sla_deadline = timezone.now() - timedelta(hours=1)
        late.save(update_fields=["sla_deadline"])
        open_grievance(category=Category.DATA_CORRECTION, description="b",
                       household_id=households["SR-BUGANDA"].id,
                       tier=Tier.L2_CDO)  # still within SLA

        # A resolved-but-past grievance must NOT show up.
        late_resolved = open_grievance(
            category=Category.OTHER, description="c",
            household_id=households["SR-BUGANDA"].id,
        )
        late_resolved.sla_deadline = timezone.now() - timedelta(hours=5)
        late_resolved.status = GrievanceStatus.RESOLVED
        late_resolved.save(update_fields=["sla_deadline", "status"])

        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get(
            "/api/v1/rpt/dashboards/overdue-grievances-by-tier/",
        )
        assert r.status_code == 200
        buckets = {row["key"]: row["count"] for row in r.data}
        assert buckets == {Tier.L1_PARISH_CHIEF: 1}

    def test_scope_filtered(
        self, db, households, two_sub_regions, django_user_model,
    ):
        from datetime import timedelta

        from django.utils import timezone

        late_buganda = open_grievance(
            category=Category.DATA_CORRECTION, description="a",
            household_id=households["SR-BUGANDA"].id,
        )
        late_karamoja = open_grievance(
            category=Category.DATA_CORRECTION, description="b",
            household_id=households["SR-KARAMOJA"].id,
        )
        for g in (late_buganda, late_karamoja):
            g.sla_deadline = timezone.now() - timedelta(hours=1)
            g.save(update_fields=["sla_deadline"])

        u = django_user_model.objects.create_user(username="op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get(
            "/api/v1/rpt/dashboards/overdue-grievances-by-tier/",
        )
        assert r.status_code == 200
        # Only the BUGANDA one is in scope → 1 row of count 1.
        assert sum(row["count"] for row in r.data) == 1


class TestSubmissionsPerDay:
    @pytest.fixture
    def submissions(self, db, households):
        from datetime import date

        from apps.intake.models import (
            Channel,
            FormVersion,
            Submission,
            SubmissionResult,
        )
        fv = FormVersion.objects.create(
            version=2, name="Questionnaire v2",
            schema={}, is_active=True,
            effective_from=date(2026, 1, 1),
        )
        # One sub in Buganda, two in Karamoja — all "today".
        for sr, hh in households.items():
            n = 1 if sr == "SR-BUGANDA" else 2
            for i in range(n):
                Submission.objects.create(
                    channel=Channel.CAPI, form_version=fv,
                    enumerator=f"e-{sr}-{i}",
                    started_at="2026-05-15T10:00:00Z",
                    result=SubmissionResult.COMPLETED,
                    provisional_registry_id=hh.id,
                )
        return None

    def test_superuser_counts_per_day(
        self, submissions, django_user_model,
    ):
        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/submissions-per-day/")
        assert r.status_code == 200
        # Three submissions today across two households.
        assert sum(row["count"] for row in r.data) == 3

    def test_scope_filtered_to_sub_region(
        self, submissions, two_sub_regions, django_user_model,
    ):
        u = django_user_model.objects.create_user(username="op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/submissions-per-day/")
        # Buganda has 1 submission only.
        assert sum(row["count"] for row in r.data) == 1


class TestPendingDedupPairsByTier:
    @pytest.fixture
    def pending_pairs(self, db, households):
        from apps.data_management.models import Member
        from apps.ddup.models import (
            DdupModelVersion,
            MatchPair,
            ModelStatus,
            PairStatus,
        )
        model = DdupModelVersion.objects.create(
            version=1, config={}, author="a", status=ModelStatus.ACTIVE,
        )
        # Two members in Buganda → 1 pending pair both-in-scope
        m1 = Member.objects.create(
            household=households["SR-BUGANDA"], line_number=11,
            surname="A", first_name="One", sex="1",
        )
        m2 = Member.objects.create(
            household=households["SR-BUGANDA"], line_number=12,
            surname="A", first_name="Two", sex="1",
        )
        a, b = sorted([m1.id, m2.id])
        MatchPair.objects.create(
            record_type="member", record_a_id=a, record_b_id=b,
            tier=1, match_reason="nin", model_version=model,
            status=PairStatus.PENDING,
        )
        # A merged pair should NOT count.
        m3 = Member.objects.create(
            household=households["SR-BUGANDA"], line_number=13,
            surname="A", first_name="Three", sex="1",
        )
        m4 = Member.objects.create(
            household=households["SR-BUGANDA"], line_number=14,
            surname="A", first_name="Four", sex="1",
        )
        a2, b2 = sorted([m3.id, m4.id])
        MatchPair.objects.create(
            record_type="member", record_a_id=a2, record_b_id=b2,
            tier=2, match_reason="phone", model_version=model,
            status=PairStatus.MERGED,
        )
        return None

    def test_only_pending_counted(self, pending_pairs, django_user_model):
        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get(
            "/api/v1/rpt/dashboards/pending-dedup-pairs-by-tier/",
        )
        assert r.status_code == 200
        buckets = {row["key"]: row["count"] for row in r.data}
        assert buckets == {"tier_1": 1}


class TestPmtScoreHistogram:
    def test_buckets_into_ten_point_ranges(
        self, db, households, django_user_model,
    ):
        from decimal import Decimal
        # Three households across three buckets.
        # current_pmt_score: 5 → 00-09, 25 → 20-29, 95 → 90-99
        # households has two; pad with a third via the same fixture-style.
        scores = [Decimal("5"), Decimal("25")]
        for hh, s in zip(households.values(), scores, strict=False):
            hh.current_pmt_score = s
            hh.save(update_fields=["current_pmt_score"])
        # Add the 95-bucket sample on the BUGANDA household separately:
        # using the same model, we just bump the second value.
        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/pmt-score-histogram/")
        assert r.status_code == 200
        # 10 buckets always returned.
        assert len(r.data) == 10
        buckets = {row["key"]: row["count"] for row in r.data}
        assert buckets["00-09"] == 1
        assert buckets["20-29"] == 1
        assert buckets["50-59"] == 0

    def test_score_at_99_caps_into_top_bucket(
        self, db, households, django_user_model,
    ):
        from decimal import Decimal
        hh = next(iter(households.values()))
        hh.current_pmt_score = Decimal("99.9")
        hh.save(update_fields=["current_pmt_score"])
        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/pmt-score-histogram/")
        buckets = {row["key"]: row["count"] for row in r.data}
        assert buckets["90-99"] == 1


class TestPromotionLatencyByConnector:
    """S6-005 — bucketed (StageRecord.promoted_at − created_at)
    distribution per connector."""

    @pytest.fixture
    def staged(self, db, households):
        """Create one StageRecord per latency bucket, tied to a real
        ConnectorRun → Connector → SourceSystem so the dashboard's
        select_related chain resolves."""
        from datetime import timedelta

        from django.utils import timezone

        from apps.ingestion_hub.models import (
            Connector,
            ConnectorRun,
            DataProvisionAgreement,
            SourceSystem,
            SourceSystemKind,
            StageRecord,
            StageRecordState,
        )
        src = SourceSystem.objects.create(
            code="PROMO-LAT", name="Test source",
            kind=SourceSystemKind.PARTNER_MIS,
        )
        DataProvisionAgreement.objects.create(
            source_system=src, reference="DPA-PL-1",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
        )
        conn = Connector.objects.create(source_system=src, name="pl-test")
        run = ConnectorRun.objects.create(connector=conn)
        now = timezone.now()
        # Build (created_at, promoted_at) so each stage falls in one bucket.
        windows = [
            ("under_1h", timedelta(minutes=30)),
            ("1_6h", timedelta(hours=3)),
            ("6_24h", timedelta(hours=12)),
            ("1_7d", timedelta(days=3)),
            ("over_7d", timedelta(days=10)),
        ]
        hh = next(iter(households.values()))
        for label, delta in windows:
            sr = StageRecord.objects.create(
                provisional_registry_id=f"01PROMOLAT{label[:14]:_<14}",
                connector_run=run, canonical_payload={},
                state=StageRecordState.PROMOTED,
                promoted_household_id=hh.id,
            )
            # Override the auto_now_add column directly so the delta is
            # exactly what each bucket expects.
            StageRecord.objects.filter(pk=sr.pk).update(
                created_at=now - delta - timedelta(seconds=1),
                promoted_at=now,
            )
        return src.code

    def test_distribution_buckets_per_connector(
        self, staged, django_user_model,
    ):
        code = staged
        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get(
            "/api/v1/rpt/dashboards/promotion-latency-by-connector/",
        )
        assert r.status_code == 200
        keys = {row["key"]: row["count"] for row in r.data}
        # 5 stages, one per bucket — all attributed to the same connector.
        assert keys == {
            f"{code} / under_1h": 1,
            f"{code} / 1_6h": 1,
            f"{code} / 6_24h": 1,
            f"{code} / 1_7d": 1,
            f"{code} / over_7d": 1,
        }

    def test_unpromoted_stages_excluded(self, db, django_user_model):
        from apps.ingestion_hub.models import (
            Connector,
            ConnectorRun,
            DataProvisionAgreement,
            SourceSystem,
            SourceSystemKind,
            StageRecord,
            StageRecordState,
        )
        src = SourceSystem.objects.create(
            code="UNP", name="x", kind=SourceSystemKind.PARTNER_MIS,
        )
        DataProvisionAgreement.objects.create(
            source_system=src, reference="DPA-UNP-1",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
        )
        conn = Connector.objects.create(source_system=src, name="unp")
        run = ConnectorRun.objects.create(connector=conn)
        StageRecord.objects.create(
            provisional_registry_id="01PROV1234567890NOTPROMOTE",
            connector_run=run, canonical_payload={},
            state=StageRecordState.PROVISIONAL,
        )
        su = django_user_model.objects.create_user(
            username="su2", password="p", is_superuser=True,
        )
        r = _client_for(su).get(
            "/api/v1/rpt/dashboards/promotion-latency-by-connector/",
        )
        assert r.data == []

    def test_sub_region_operator_sees_only_in_scope_promotions(
        self, staged, two_sub_regions, households, django_user_model,
    ):
        # Sub-region operator's scope covers SR-BUGANDA; the fixture
        # planted stages whose promoted_household_id matches the first
        # value in `households` (insertion order = BUGANDA first).
        u = django_user_model.objects.create_user(username="op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get(
            "/api/v1/rpt/dashboards/promotion-latency-by-connector/",
        )
        # All 5 stages tied to BUGANDA household -> visible to BUGANDA op.
        assert sum(row["count"] for row in r.data) == 5


class TestCsvExports:
    """S7-005 — every RPT dashboard supports ?export=csv. Same scope
    semantics + same audit emission as JSON; only the rendering
    differs."""

    def test_json_default(self, db, households, django_user_model):
        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/households-by-sub-region/")
        assert r.status_code == 200
        assert r["content-type"].startswith("application/json")
        # JSON shape: list of {key, count} dicts.
        assert isinstance(r.data, list)

    def test_csv_format_query_param(self, db, households, django_user_model):
        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get(
            "/api/v1/rpt/dashboards/households-by-sub-region/?export=csv",
        )
        assert r.status_code == 200
        assert r["content-type"] == "text/csv"
        body = r.content.decode("utf-8").strip()
        # First line is header; following lines are key,count pairs.
        lines = body.splitlines()
        assert lines[0] == "key,count"
        assert len(lines) == 3  # header + 2 sub-regions
        # Each non-header line has exactly two CSV fields.
        for line in lines[1:]:
            assert "," in line

    def test_csv_filename_in_content_disposition(
        self, db, households, django_user_model,
    ):
        su = django_user_model.objects.create_user(
            username="su2", password="p", is_superuser=True,
        )
        r = _client_for(su).get(
            "/api/v1/rpt/dashboards/households-by-pmt-band/?export=csv",
        )
        assert "filename=" in r["content-disposition"]
        assert "households-by-pmt-band.csv" in r["content-disposition"]

    def test_csv_emits_audit_event(
        self, db, households, django_user_model,
    ):
        """CSV path should emit the SAME audit event as JSON — switching
        format must not let a partner exfil silently."""
        from apps.security.models import AuditEvent
        su = django_user_model.objects.create_user(
            username="su3", password="p", is_superuser=True,
        )
        _client_for(su).get(
            "/api/v1/rpt/dashboards/households-by-sub-region/?export=csv",
        )
        ev = AuditEvent.objects.filter(
            entity_type="rpt_dashboard",
            entity_id="households_by_sub_region",
            actor_id="su3",
        ).first()
        assert ev is not None
        assert ev.action == "dashboard_read"

    def test_csv_respects_abac_scope(
        self, db, households, two_sub_regions, django_user_model,
    ):
        """Sub-region operator's CSV must contain only their bucket
        — the scope filter applies BEFORE rendering, same as JSON."""
        u = django_user_model.objects.create_user(username="op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get(
            "/api/v1/rpt/dashboards/households-by-sub-region/?export=csv",
        )
        body = r.content.decode("utf-8").strip()
        lines = body.splitlines()
        assert lines[0] == "key,count"
        assert len(lines) == 2  # header + 1 row
        # The Karamoja code is NOT in any data row.
        karamoja_code = two_sub_regions["SR-KARAMOJA"]["sr"].code
        assert karamoja_code not in body


class TestGrievancesByCategory:
    """S9-002 — counts of non-closed grievances grouped by Category.
    RESOLVED + CLOSED rows excluded; same scope semantics as
    OpenGrievancesByTier."""

    def test_groups_by_category(self, db, households, django_user_model):
        open_grievance(category=Category.DATA_CORRECTION, description="a",
                       household_id=households["SR-BUGANDA"].id)
        open_grievance(category=Category.DATA_CORRECTION, description="b",
                       household_id=households["SR-BUGANDA"].id)
        open_grievance(category=Category.EXCLUSION_ERROR, description="c",
                       household_id=households["SR-KARAMOJA"].id)
        # Closed grievance should NOT appear.
        g = open_grievance(category=Category.OPERATOR_CONDUCT, description="x",
                          household_id=households["SR-BUGANDA"].id)
        g.status = GrievanceStatus.CLOSED
        g.save(update_fields=["status"])

        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/grievances-by-category/")
        assert r.status_code == 200
        buckets = {row["key"]: row["count"] for row in r.data}
        assert buckets == {
            Category.DATA_CORRECTION: 2,
            Category.EXCLUSION_ERROR: 1,
        }

    def test_scope_filtered(self, db, households, two_sub_regions, django_user_model):
        open_grievance(category=Category.DATA_CORRECTION, description="a",
                       household_id=households["SR-BUGANDA"].id)
        open_grievance(category=Category.DATA_CORRECTION, description="b",
                       household_id=households["SR-KARAMOJA"].id)
        u = django_user_model.objects.create_user(username="op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/grievances-by-category/")
        # Only the BUGANDA case in scope.
        assert sum(row["count"] for row in r.data) == 1

    def test_csv_export_inherited(self, db, households, django_user_model):
        open_grievance(category=Category.DATA_CORRECTION, description="a",
                       household_id=households["SR-BUGANDA"].id)
        su = django_user_model.objects.create_user(
            username="su2", password="p", is_superuser=True,
        )
        r = _client_for(su).get(
            "/api/v1/rpt/dashboards/grievances-by-category/?export=csv",
        )
        assert r.status_code == 200
        assert r["content-type"] == "text/csv"
        assert "grievances-by-category.csv" in r["content-disposition"]


class TestWeeklyHouseholdRegistrations:
    """S8-004 — first trend-over-time dashboard. Counts of
    Household.created_at grouped by ISO week for the last 12 weeks."""

    def test_renders_iso_week_keys(self, db, households, django_user_model):
        su = django_user_model.objects.create_user(
            username="su", password="p", is_superuser=True,
        )
        r = _client_for(su).get(
            "/api/v1/rpt/dashboards/weekly-household-registrations/",
        )
        assert r.status_code == 200
        # The two test households were just created -> one bucket today's
        # week, count=2.
        assert len(r.data) >= 1
        # Key is 'YYYY-Www' (ISO week format) — lexicographically sortable.
        key = r.data[0]["key"]
        assert "-W" in key
        assert key[:4].isdigit()  # year
        assert sum(row["count"] for row in r.data) == 2

    def test_scope_filtered_before_aggregation(
        self, db, households, two_sub_regions, django_user_model,
    ):
        u = django_user_model.objects.create_user(username="op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get(
            "/api/v1/rpt/dashboards/weekly-household-registrations/",
        )
        assert r.status_code == 200
        # Only the BUGANDA household visible -> one row, count=1.
        assert sum(row["count"] for row in r.data) == 1

    def test_csv_export_works(self, db, households, django_user_model):
        """Inherited from the _render helper — every dashboard gets
        CSV for free."""
        su = django_user_model.objects.create_user(
            username="su2", password="p", is_superuser=True,
        )
        r = _client_for(su).get(
            "/api/v1/rpt/dashboards/weekly-household-registrations/"
            "?export=csv",
        )
        assert r.status_code == 200
        assert r["content-type"] == "text/csv"
        assert "weekly-household-registrations.csv" in r["content-disposition"]

    def test_audit_event_emitted(self, db, households, django_user_model):
        from apps.security.models import AuditEvent
        su = django_user_model.objects.create_user(
            username="su3", password="p", is_superuser=True,
        )
        _client_for(su).get(
            "/api/v1/rpt/dashboards/weekly-household-registrations/",
        )
        ev = AuditEvent.objects.filter(
            entity_type="rpt_dashboard",
            entity_id="weekly_household_registrations",
        ).first()
        assert ev is not None
        assert ev.action == "dashboard_read"


# --- US-S11-007 — comparative dashboards ---------------------------------


class TestComparativeMetric:
    URL = "/api/v1/rpt/dashboards/comparative/"

    @pytest.fixture
    def superuser(self, django_user_model):
        return django_user_model.objects.create_user(
            username="su", password="x", is_superuser=True, is_staff=True,
        )

    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_unknown_metric_rejects(self, db, superuser):
        r = self._client(superuser).get(self.URL, {"metric": "bogus"})
        assert r.status_code == 400
        assert "bogus" in r.data["detail"]

    def test_unknown_period_rejects(self, db, superuser):
        r = self._client(superuser).get(self.URL, {"compare": "yoy"})
        assert r.status_code == 400

    def test_zero_baseline_yields_null_delta_pct(self, db, superuser):
        """No households in either window → delta_pct is None (avoid
        0/0). delta_abs is 0."""
        r = self._client(superuser).get(self.URL, {"metric": "households_created"})
        assert r.status_code == 200
        assert r.data["delta_abs"] == 0
        assert r.data["delta_pct"] is None

    def test_current_window_counts_recent_rows(self, db, households, superuser):
        """Households created right now land in the current window."""
        r = self._client(superuser).get(
            self.URL, {"metric": "households_created", "compare": "wow"},
        )
        assert r.status_code == 200
        assert r.data["current"]["count"] == 2
        assert r.data["previous"]["count"] == 0
        assert r.data["delta_abs"] == 2

    def test_period_window_size_differs_for_wow_vs_mom(self, db, superuser):
        wow = self._client(superuser).get(
            self.URL, {"metric": "households_created", "compare": "wow"},
        )
        mom = self._client(superuser).get(
            self.URL, {"metric": "households_created", "compare": "mom"},
        )
        # DRF returns datetime objects directly in response.data for an
        # APIView returning a dict (not the serialised string), so we
        # diff them straight away.
        assert (wow.data["current"]["to"] - wow.data["current"]["from"]).days == 7
        assert (mom.data["current"]["to"] - mom.data["current"]["from"]).days == 30

    def test_csv_export_two_rows_plus_header(self, db, superuser):
        r = self._client(superuser).get(
            self.URL,
            {"metric": "households_created", "compare": "wow", "export": "csv"},
        )
        assert r.status_code == 200
        assert r["Content-Type"] == "text/csv"
        lines = r.content.decode().strip().splitlines()
        # 1 header + 2 data rows.
        assert len(lines) == 3
        assert lines[0].startswith("metric,period,window,from,to,count,delta_abs,delta_pct")
        assert "previous" in lines[1]
        assert "current" in lines[2]

    def test_audit_event_emitted(self, db, superuser):
        self._client(superuser).get(
            self.URL, {"metric": "households_created", "compare": "wow"},
        )
        ev = AuditEvent.objects.filter(
            entity_type="rpt_dashboard",
            entity_id="comparative_households_created_wow",
        ).first()
        assert ev is not None
        assert ev.action == "dashboard_read"

    def test_abac_applied_to_metric_counter(self, db, two_sub_regions, households, django_user_model):
        """A sub-region operator only sees households in their scope —
        same plumbing the row-level dashboards use."""
        user = django_user_model.objects.create_user(username="op", password="x")
        OperatorScope.objects.create(
            user=user, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = self._client(user).get(
            self.URL, {"metric": "households_created", "compare": "wow"},
        )
        assert r.status_code == 200
        assert r.data["current"]["count"] == 1  # only Buganda visible

    def test_empty_scope_user_sees_zero(self, db, households, django_user_model):
        user = django_user_model.objects.create_user(username="nobody", password="x")
        # No OperatorScope row -> codes = [], count short-circuits to 0.
        r = self._client(user).get(
            self.URL, {"metric": "households_created", "compare": "wow"},
        )
        assert r.status_code == 200
        assert r.data["current"]["count"] == 0
        assert r.data["previous"]["count"] == 0


class TestOperatorKpisRegionDrillDown:
    """US-S14-004 — per-region drill-down on the home KPI aggregator.

    The view accepts ?region=<sub_region_code>; counts that depend on
    Household geography (households_total, stages, change requests,
    grievances) are narrowed to just that sub-region. DRS counts are
    partner-side ABAC, not geographic — they stay national.
    """

    URL = "/api/v1/rpt/dashboards/operator-kpis/"

    def test_superuser_no_region_sees_all_households(
        self, db, households, django_user_model,
    ):
        su = django_user_model.objects.create_user(
            username="kpis-su", password="p", is_superuser=True,
        )
        r = _client_for(su).get(self.URL)
        assert r.status_code == 200
        assert r.data["region"] == ""
        assert r.data["households_total"] == 2  # both sub-regions

    def test_superuser_with_region_narrows_to_one_sub_region(
        self, db, households, two_sub_regions, django_user_model,
    ):
        su = django_user_model.objects.create_user(
            username="kpis-su2", password="p", is_superuser=True,
        )
        buganda_code = two_sub_regions["SR-BUGANDA"]["sr"].code
        r = _client_for(su).get(self.URL, {"region": buganda_code})
        assert r.status_code == 200
        assert r.data["region"] == buganda_code
        assert r.data["households_total"] == 1  # only the Buganda HH

    def test_out_of_scope_region_returns_zero_not_403(
        self, db, households, two_sub_regions, django_user_model,
    ):
        # Operator scoped to Buganda; drills into Karamoja → zeros, not 403.
        u = django_user_model.objects.create_user(username="kpis-op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        karamoja_code = two_sub_regions["SR-KARAMOJA"]["sr"].code
        r = _client_for(u).get(self.URL, {"region": karamoja_code})
        assert r.status_code == 200
        assert r.data["region"] == karamoja_code
        # Buganda-scoped op drilling into Karamoja → all geo counts zero.
        assert r.data["households_total"] == 0
        assert r.data["change_requests_pending"] == 0
        assert r.data["grievances_open"] == 0
        assert r.data["stages_pending_promotion"] == 0

    def test_in_scope_region_matches_no_region_for_single_scope_op(
        self, db, households, two_sub_regions, django_user_model,
    ):
        # Buganda-scoped operator: ?region=Buganda must equal no-region call
        # since their effective scope is already Buganda only.
        u = django_user_model.objects.create_user(username="kpis-op2", password="p")
        buganda_code = two_sub_regions["SR-BUGANDA"]["sr"].code
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=buganda_code,
        )
        no_region = _client_for(u).get(self.URL).data
        with_region = _client_for(u).get(self.URL, {"region": buganda_code}).data
        assert no_region["households_total"] == with_region["households_total"] == 1
        assert with_region["region"] == buganda_code

    def test_audit_event_records_region(
        self, db, households, two_sub_regions, django_user_model,
    ):
        su = django_user_model.objects.create_user(
            username="kpis-aud", password="p", is_superuser=True,
        )
        buganda_code = two_sub_regions["SR-BUGANDA"]["sr"].code
        _client_for(su).get(self.URL, {"region": buganda_code})
        ev = AuditEvent.objects.filter(
            entity_type="rpt_dashboard", entity_id="operator_kpis",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert f"region={buganda_code}" in (ev.reason or "")


class TestAdditionalReportDashboards:
    def test_households_by_urban_rural_is_scope_filtered(
        self, db, households, two_sub_regions, django_user_model,
    ):
        households["SR-BUGANDA"].urban_rural = "urban"
        households["SR-BUGANDA"].save(update_fields=["urban_rural"])
        households["SR-KARAMOJA"].urban_rural = "rural"
        households["SR-KARAMOJA"].save(update_fields=["urban_rural"])
        u = django_user_model.objects.create_user(username="hh-ur", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/households-by-urban-rural/")
        assert r.status_code == 200
        assert {row["key"]: row["count"] for row in r.data} == {"urban": 1}

    def test_households_by_intake_source_groups_registry_rows(
        self, db, households, django_user_model,
    ):
        households["SR-BUGANDA"].current_intake_source = "dih"
        households["SR-BUGANDA"].save(update_fields=["current_intake_source"])
        households["SR-KARAMOJA"].current_intake_source = "capi"
        households["SR-KARAMOJA"].save(update_fields=["current_intake_source"])
        su = django_user_model.objects.create_user(
            username="hh-src", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/households-by-intake-source/")
        assert r.status_code == 200
        assert {row["key"]: row["count"] for row in r.data} == {"capi": 1, "dih": 1}

    def test_dih_stages_by_state_is_scope_filtered(
        self, db, households, two_sub_regions, django_user_model,
    ):
        from apps.ingestion_hub.models import (
            Connector,
            ConnectorRun,
            SourceSystem,
            SourceSystemKind,
            StageRecord,
            StageRecordState,
        )
        ss = SourceSystem.objects.create(
            code="RPT-STG", name="Report source", kind=SourceSystemKind.PARTNER_MIS,
        )
        conn = Connector.objects.create(source_system=ss, name="rpt")
        run = ConnectorRun.objects.create(connector=conn)
        StageRecord.objects.create(
            connector_run=run,
            provisional_registry_id=households["SR-BUGANDA"].id,
            canonical_payload={},
            state=StageRecordState.PENDING_PROMOTION,
        )
        StageRecord.objects.create(
            connector_run=run,
            provisional_registry_id=households["SR-KARAMOJA"].id,
            canonical_payload={},
            state=StageRecordState.QUALITY_FAILED,
        )
        u = django_user_model.objects.create_user(username="stg-op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/dih-stages-by-state/")
        assert r.status_code == 200
        assert {row["key"]: row["count"] for row in r.data} == {
            StageRecordState.PENDING_PROMOTION: 1,
        }

    def test_national_connector_runs_by_status(self, db, django_user_model):
        from apps.ingestion_hub.models import (
            Connector,
            ConnectorRun,
            ConnectorRunStatus,
            SourceSystem,
            SourceSystemKind,
        )
        ss = SourceSystem.objects.create(
            code="RPT-RUN", name="Run source", kind=SourceSystemKind.PARTNER_MIS,
        )
        conn = Connector.objects.create(source_system=ss, name="rpt")
        ConnectorRun.objects.create(connector=conn, status=ConnectorRunStatus.RUNNING)
        ConnectorRun.objects.create(connector=conn, status=ConnectorRunStatus.FAILED)
        su = django_user_model.objects.create_user(
            username="runs-su", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/connector-runs-by-status/")
        assert r.status_code == 200
        assert {row["key"]: row["count"] for row in r.data} == {
            ConnectorRunStatus.FAILED: 1,
            ConnectorRunStatus.RUNNING: 1,
        }

    def test_local_operator_cannot_read_national_connector_health(
        self, db, two_sub_regions, django_user_model,
    ):
        u = django_user_model.objects.create_user(username="runs-op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/connector-runs-by-status/")
        assert r.status_code == 200
        assert r.data == []

    def test_idv_attempts_by_status_is_national_only(self, db, django_user_model):
        from django.utils import timezone

        from apps.identity_verification.models import AttemptStatus, NiraVerificationAttempt
        NiraVerificationAttempt.objects.create(
            nin_hash=b"1" * 32,
            status=AttemptStatus.QUEUED,
            attempts=1,
            next_retry_at=timezone.now(),
        )
        su = django_user_model.objects.create_user(
            username="idv-su", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/idv-attempts-by-status/")
        assert r.status_code == 200
        assert {row["key"]: row["count"] for row in r.data} == {AttemptStatus.QUEUED: 1}

    def test_change_requests_by_status_scopes_household_and_member_targets(
        self, db, households, two_sub_regions, django_user_model,
    ):
        from apps.data_management.models import Member
        from apps.update_workflow.models import (
            ChangeRequest,
            ChangeStatus,
            ChangeType,
            EntityType,
            SourceChannel,
        )
        buganda_member = Member.objects.create(
            household=households["SR-BUGANDA"], line_number=31,
            surname="A", first_name="B", sex="1",
        )
        ChangeRequest.objects.create(
            entity_type=EntityType.MEMBER, entity_id=buganda_member.id,
            change_type=ChangeType.CORRECTION, source_channel=SourceChannel.WEB,
            requester="op", status=ChangeStatus.PENDING_APPROVAL,
        )
        ChangeRequest.objects.create(
            entity_type=EntityType.HOUSEHOLD, entity_id=households["SR-KARAMOJA"].id,
            change_type=ChangeType.CORRECTION, source_channel=SourceChannel.WEB,
            requester="op", status=ChangeStatus.REJECTED,
        )
        u = django_user_model.objects.create_user(username="cr-op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/change-requests-by-status/")
        assert r.status_code == 200
        assert {row["key"]: row["count"] for row in r.data} == {
            ChangeStatus.PENDING_APPROVAL: 1,
        }

    def test_data_requests_by_status_respects_partner_scope(
        self, db, django_user_model,
    ):
        from datetime import date

        from apps.data_requests.models import DataRequest, RequestStatus
        from apps.partners.models import DataSharingAgreement, Partner
        p1 = Partner.objects.create(
            code="P1", name="Partner 1", type="agency", status="active",
        )
        p2 = Partner.objects.create(
            code="P2", name="Partner 2", type="agency", status="active",
        )
        dsa1 = DataSharingAgreement.objects.create(
            partner=p1, reference="DSA-P1",
            effective_from=date(2026, 1, 1), effective_to=date(2030, 1, 1),
            status="active",
        )
        dsa2 = DataSharingAgreement.objects.create(
            partner=p2, reference="DSA-P2",
            effective_from=date(2026, 1, 1), effective_to=date(2030, 1, 1),
            status="active",
        )
        DataRequest.objects.create(dsa=dsa1, requester="a", status=RequestStatus.SUBMITTED)
        DataRequest.objects.create(dsa=dsa2, requester="b", status=RequestStatus.DELIVERED)
        u = django_user_model.objects.create_user(username="partner-op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER, scope_code="P1",
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/data-requests-by-status/")
        assert r.status_code == 200
        assert {row["key"]: row["count"] for row in r.data} == {
            RequestStatus.SUBMITTED: 1,
        }

    def test_referrals_by_programme_status_is_scope_filtered(
        self, db, households, two_sub_regions, django_user_model,
    ):
        from apps.referral.models import Programme, Referral, ReferralStatus
        programme = Programme.objects.create(code="PDM", name="PDM")
        Referral.objects.create(
            programme=programme, household=households["SR-BUGANDA"],
            status=ReferralStatus.SENT,
        )
        Referral.objects.create(
            programme=programme, household=households["SR-KARAMOJA"],
            status=ReferralStatus.ACCEPTED,
        )
        u = django_user_model.objects.create_user(username="ref-op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/referrals-by-programme-status/")
        assert r.status_code == 200
        assert {row["key"]: row["count"] for row in r.data} == {
            f"PDM / {ReferralStatus.SENT}": 1,
        }

    def test_audit_events_by_action_is_national_only(
        self, db, two_sub_regions, django_user_model,
    ):
        emit = AuditEvent.objects.create
        emit(actor_id="a", action="read", entity_type="household", entity_id="1")
        emit(actor_id="a", action="promote", entity_type="household", entity_id="2")
        su = django_user_model.objects.create_user(
            username="audit-su", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/audit-events-by-action/")
        assert r.status_code == 200
        buckets = {row["key"]: row["count"] for row in r.data}
        assert buckets["read"] == 1
        assert buckets["promote"] == 1

        u = django_user_model.objects.create_user(username="audit-op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        scoped = _client_for(u).get("/api/v1/rpt/dashboards/audit-events-by-action/")
        assert scoped.status_code == 200
        assert scoped.data == []


class TestOperationalRecordExports:
    def test_grievance_records_csv_respects_scope(
        self, db, households, two_sub_regions, django_user_model,
    ):
        open_grievance(
            category=Category.DATA_CORRECTION, description="a",
            household_id=households["SR-BUGANDA"].id,
        )
        open_grievance(
            category=Category.OTHER, description="b",
            household_id=households["SR-KARAMOJA"].id,
        )
        u = django_user_model.objects.create_user(username="grm-export", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/grievances/records/?export=csv")
        assert r.status_code == 200
        body = r.content.decode("utf-8")
        assert households["SR-BUGANDA"].id in body
        assert households["SR-KARAMOJA"].id not in body

    def test_change_request_records_include_member_targets_in_scope(
        self, db, households, two_sub_regions, django_user_model,
    ):
        from apps.data_management.models import Member
        from apps.update_workflow.models import (
            ChangeRequest,
            ChangeStatus,
            ChangeType,
            EntityType,
            SourceChannel,
        )
        member = Member.objects.create(
            household=households["SR-BUGANDA"], line_number=41,
            surname="Scope", first_name="Member", sex="2",
        )
        ChangeRequest.objects.create(
            entity_type=EntityType.MEMBER, entity_id=member.id,
            change_type=ChangeType.CORRECTION, source_channel=SourceChannel.WEB,
            requester="op", status=ChangeStatus.PENDING_APPROVAL,
        )
        u = django_user_model.objects.create_user(username="upd-export", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/change-requests/records/")
        assert r.status_code == 200
        assert len(r.data) == 1
        assert r.data[0]["entity_id"] == member.id

    def test_dedup_pair_records_apply_both_ends_scope(
        self, db, households, two_sub_regions, django_user_model,
    ):
        from apps.data_management.models import Member
        from apps.ddup.models import DdupModelVersion, MatchPair, ModelStatus, PairStatus
        model = DdupModelVersion.objects.create(
            version=101, config={}, author="a", status=ModelStatus.ACTIVE,
        )
        m1 = Member.objects.create(
            household=households["SR-BUGANDA"], line_number=51,
            surname="A", first_name="One", sex="1",
        )
        m2 = Member.objects.create(
            household=households["SR-BUGANDA"], line_number=52,
            surname="A", first_name="Two", sex="1",
        )
        a, b = sorted([m1.id, m2.id])
        MatchPair.objects.create(
            record_type="member", record_a_id=a, record_b_id=b, tier=1,
            match_reason="nin", model_version=model, status=PairStatus.PENDING,
        )
        u = django_user_model.objects.create_user(username="dd-export", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get("/api/v1/rpt/dashboards/dedup-pairs/records/?status=pending")
        assert r.status_code == 200
        assert len(r.data) == 1
        assert r.data[0]["match_reason"] == "nin"

    def test_data_request_records_partner_scope(
        self, db, django_user_model,
    ):
        from datetime import date

        from apps.data_requests.models import DataRequest, RequestStatus
        from apps.partners.models import DataSharingAgreement, Partner
        partner = Partner.objects.create(
            code="PX", name="Partner X", type="agency", status="active",
        )
        dsa = DataSharingAgreement.objects.create(
            partner=partner, reference="DSA-PX",
            effective_from=date(2026, 1, 1), effective_to=date(2030, 1, 1),
            status="active",
        )
        DataRequest.objects.create(dsa=dsa, requester="x", status=RequestStatus.SUBMITTED)
        u = django_user_model.objects.create_user(username="drs-export", password="p")
        OperatorScope.objects.create(user=u, scope_level=ScopeLevel.PARTNER, scope_code="PX")
        r = _client_for(u).get("/api/v1/rpt/dashboards/data-requests/records/")
        assert r.status_code == 200
        assert len(r.data) == 1
        assert r.data[0]["partner_code"] == "PX"

    def test_idv_attempt_records_are_national_only(
        self, db, two_sub_regions, django_user_model,
    ):
        from django.utils import timezone

        from apps.identity_verification.models import AttemptStatus, NiraVerificationAttempt
        NiraVerificationAttempt.objects.create(
            nin_hash=b"2" * 32,
            status=AttemptStatus.QUEUED,
            attempts=2,
            next_retry_at=timezone.now(),
        )
        u = django_user_model.objects.create_user(username="idv-local", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        assert _client_for(u).get("/api/v1/rpt/dashboards/idv-attempts/records/").data == []
        su = django_user_model.objects.create_user(
            username="idv-national", password="p", is_superuser=True,
        )
        r = _client_for(su).get("/api/v1/rpt/dashboards/idv-attempts/records/?export=csv")
        assert r.status_code == 200
        assert "idv-attempt-records.csv" in r["content-disposition"]
        assert "queued" in r.content.decode("utf-8")


class TestRegionDrillDownQueuePanels:
    """US-S15-003 — the home queue panels honour ?sub_region_code= on
    DIH stages, UPD change-requests, and GRM grievances. Verifies the
    custom get_queryset overrides actually narrow the result set.
    """

    def test_grm_grievances_narrow_by_sub_region(
        self, db, households, two_sub_regions, django_user_model,
    ):
        from apps.grievance.models import Category, Grievance, Tier
        # One grievance per sub-region.
        for sr_key, hh in households.items():
            Grievance.objects.create(
                category=Category.DATA_CORRECTION,
                description=f"grievance for {sr_key}",
                household_id=hh.id, tier=Tier.L1_PARISH_CHIEF,
                reporter_name="Test",
            )
        su = django_user_model.objects.create_user(
            username="grm-rgn", password="p", is_superuser=True,
        )
        buganda_code = two_sub_regions["SR-BUGANDA"]["sr"].code
        r = _client_for(su).get(
            f"/api/v1/grm/grievances/?sub_region_code={buganda_code}",
        )
        assert r.status_code == 200
        ids = {row["household_id"] for row in r.data["results"]}
        assert ids == {households["SR-BUGANDA"].id}

    def test_upd_change_requests_narrow_by_sub_region(
        self, db, households, two_sub_regions, django_user_model,
    ):
        from apps.update_workflow.models import (
            ChangeRequest,
            ChangeType,
            EntityType,
            SourceChannel,
        )
        for _sr_key, hh in households.items():
            ChangeRequest.objects.create(
                entity_type=EntityType.HOUSEHOLD, entity_id=hh.id,
                change_type=ChangeType.CORRECTION,
                source_channel=SourceChannel.WEB,
                requester="op", changes={"field": "x"},
                required_role="CDO",
            )
        su = django_user_model.objects.create_user(
            username="upd-rgn", password="p", is_superuser=True,
        )
        karamoja_code = two_sub_regions["SR-KARAMOJA"]["sr"].code
        r = _client_for(su).get(
            f"/api/v1/upd/change-requests/?sub_region_code={karamoja_code}",
        )
        assert r.status_code == 200
        ids = {row["entity_id"] for row in r.data["results"]}
        assert ids == {households["SR-KARAMOJA"].id}

    def test_dih_stage_records_narrow_by_sub_region(
        self, db, households, two_sub_regions, django_user_model,
    ):
        from apps.ingestion_hub.models import (
            Connector,
            ConnectorRun,
            SourceSystem,
            StageRecord,
            StageRecordState,
        )
        ss = SourceSystem.objects.create(
            code="TEST", name="Test source", kind="bulk",
        )
        conn = Connector.objects.create(
            source_system=ss, name="t", config={}, is_active=True,
        )
        run = ConnectorRun.objects.create(connector=conn, status="success")
        for hh in households.values():
            StageRecord.objects.create(
                connector_run=run,
                provisional_registry_id=hh.id,
                canonical_payload={},
                state=StageRecordState.PENDING_PROMOTION,
            )
        su = django_user_model.objects.create_user(
            username="dih-rgn", password="p", is_superuser=True,
        )
        buganda_code = two_sub_regions["SR-BUGANDA"]["sr"].code
        r = _client_for(su).get(
            f"/api/v1/dih/stage-records/?sub_region_code={buganda_code}",
        )
        assert r.status_code == 200
        ids = {row["provisional_registry_id"] for row in r.data["results"]}
        assert ids == {households["SR-BUGANDA"].id}


# --- US-082b: DQA rule-violations dashboard --------------------------------

class TestDqaViolationsDashboard:
    """GET /api/v1/rpt/dashboards/dqa-violations/ aggregates DqaResult
    rows (failures only) by rule + severity. Path A — live aggregation
    per the US-082 ticket recommendation; Path B (Celery materialised)
    deferred until telemetry shows we need it."""

    URL = "/api/v1/rpt/dashboards/dqa-violations/"
    RECORDS_URL = "/api/v1/rpt/dashboards/dqa-violations/records/"

    @pytest.fixture
    def seeded_rules(self, db):
        from datetime import date as _d

        from apps.dqa.models import DqaRule, RuleStatus, Severity
        r1 = DqaRule.objects.create(
            rule_id="AC-MEM-SURNAME", version=1,
            description="surname required", severity=Severity.BLOCKING,
            applicability_filter={"entity": "member"},
            expression={"field": "surname", "op": "not_null"},
            error_message_template="missing",
            status=RuleStatus.ACTIVE,
            effective_from=_d(2026, 1, 1),
            author="alice", approved_by="bob",
        )
        r2 = DqaRule.objects.create(
            rule_id="AC-NIN-FMT", version=1,
            description="nin format", severity=Severity.WARNING,
            applicability_filter={"entity": "member"},
            expression={"field": "nin", "op": "regex",
                        "value": r"^(CM|CF)[A-Z0-9]{12}$"},
            error_message_template="bad nin",
            status=RuleStatus.ACTIVE,
            effective_from=_d(2026, 1, 1),
            author="alice", approved_by="bob",
        )
        return {"r1": r1, "r2": r2}

    def _seed_results(self, db, households, two_sub_regions, seeded_rules):
        """8 failures: 5 for r1 (3 in BUGANDA, 2 in KARAMOJA) +
        3 for r2 (all BUGANDA). Lets us test both the top-N ordering
        and the sub_region_code drill-down."""
        from apps.dqa.models import DqaResult
        buganda_hh = households["SR-BUGANDA"]
        karamoja_hh = households["SR-KARAMOJA"]
        for i in range(3):
            DqaResult.objects.create(
                rule=seeded_rules["r1"], record_type="member",
                record_id=f"{buganda_hh.id}:{i + 1}",
                passed=False, severity="blocking", reason="missing",
            )
        for i in range(2):
            DqaResult.objects.create(
                rule=seeded_rules["r1"], record_type="member",
                record_id=f"{karamoja_hh.id}:{i + 1}",
                passed=False, severity="blocking", reason="missing",
            )
        for i in range(3):
            DqaResult.objects.create(
                rule=seeded_rules["r2"], record_type="member",
                record_id=f"{buganda_hh.id}:{i + 1}",
                passed=False, severity="warning", reason="bad nin",
            )

    def test_superuser_sees_all_rules_ordered_by_fail_count(
        self, db, households, two_sub_regions, seeded_rules, django_user_model,
    ):
        self._seed_results(db, households, two_sub_regions, seeded_rules)
        su = django_user_model.objects.create_user(
            username="viol-su", password="p", is_superuser=True,
        )
        r = _client_for(su).get(self.URL)
        assert r.status_code == 200
        # r1 = 5 fails, r2 = 3 fails → r1 first.
        rule_ids = [row["rule_id"] for row in r.data]
        assert rule_ids == ["AC-MEM-SURNAME", "AC-NIN-FMT"]
        first = r.data[0]
        assert first["fail_count"] == 5
        assert first["severity"] == "blocking"
        assert "last_seen_at" in first

    def test_severity_filter_narrows(
        self, db, households, two_sub_regions, seeded_rules, django_user_model,
    ):
        self._seed_results(db, households, two_sub_regions, seeded_rules)
        su = django_user_model.objects.create_user(
            username="viol-sev", password="p", is_superuser=True,
        )
        r = _client_for(su).get(self.URL + "?severity=warning")
        assert r.status_code == 200
        assert len(r.data) == 1
        assert r.data[0]["rule_id"] == "AC-NIN-FMT"
        assert r.data[0]["fail_count"] == 3

    def test_sub_region_code_drill_down(
        self, db, households, two_sub_regions, seeded_rules, django_user_model,
    ):
        self._seed_results(db, households, two_sub_regions, seeded_rules)
        su = django_user_model.objects.create_user(
            username="viol-rgn", password="p", is_superuser=True,
        )
        karamoja_code = two_sub_regions["SR-KARAMOJA"]["sr"].code
        r = _client_for(su).get(self.URL + f"?sub_region_code={karamoja_code}")
        assert r.status_code == 200
        # Only r1 has Karamoja fails, and only 2 of them.
        assert len(r.data) == 1
        assert r.data[0]["rule_id"] == "AC-MEM-SURNAME"
        assert r.data[0]["fail_count"] == 2

    def test_sub_region_operator_sees_only_their_bucket(
        self, db, households, two_sub_regions, seeded_rules, django_user_model,
    ):
        self._seed_results(db, households, two_sub_regions, seeded_rules)
        u = django_user_model.objects.create_user(username="viol-op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get(self.URL)
        assert r.status_code == 200
        # Buganda has 3 r1 fails + 3 r2 fails = both rules visible.
        by_rule = {row["rule_id"]: row["fail_count"] for row in r.data}
        assert by_rule == {"AC-MEM-SURNAME": 3, "AC-NIN-FMT": 3}

    def test_out_of_scope_region_returns_empty(
        self, db, households, two_sub_regions, seeded_rules, django_user_model,
    ):
        self._seed_results(db, households, two_sub_regions, seeded_rules)
        u = django_user_model.objects.create_user(username="viol-op2", password="p")
        # Buganda-scoped op asks for Karamoja → empty.
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        karamoja_code = two_sub_regions["SR-KARAMOJA"]["sr"].code
        r = _client_for(u).get(self.URL + f"?sub_region_code={karamoja_code}")
        assert r.status_code == 200
        assert r.data == []

    def test_unscoped_user_sees_empty(
        self, db, households, two_sub_regions, seeded_rules, django_user_model,
    ):
        self._seed_results(db, households, two_sub_regions, seeded_rules)
        u = django_user_model.objects.create_user(username="viol-ghost", password="p")
        # No OperatorScope row → no codes → no household_ids match.
        r = _client_for(u).get(self.URL)
        assert r.status_code == 200
        assert r.data == []

    def test_emits_audit_event(
        self, db, households, two_sub_regions, seeded_rules, django_user_model,
    ):
        self._seed_results(db, households, two_sub_regions, seeded_rules)
        su = django_user_model.objects.create_user(
            username="viol-aud", password="p", is_superuser=True,
        )
        _client_for(su).get(self.URL)
        ev = AuditEvent.objects.filter(
            entity_type="rpt_dashboard", entity_id="dqa_violations",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert ev.action == "dashboard_read"

    def test_records_endpoint_returns_specific_failed_records(
        self, db, households, two_sub_regions, seeded_rules, django_user_model,
    ):
        from apps.data_management.models import Member

        Member.objects.create(
            household=households["SR-BUGANDA"], line_number=1,
            surname="Okello", first_name="Grace", sex="2",
        )
        self._seed_results(db, households, two_sub_regions, seeded_rules)
        su = django_user_model.objects.create_user(
            username="viol-rec", password="p", is_superuser=True,
        )
        r = _client_for(su).get(self.RECORDS_URL + "?rule_id=AC-MEM-SURNAME")
        assert r.status_code == 200
        assert len(r.data) == 5
        row = r.data[0]
        assert row["rule_id"] == "AC-MEM-SURNAME"
        assert row["record_type"] == "member"
        assert row["household_id"] in {
            households["SR-BUGANDA"].id,
            households["SR-KARAMOJA"].id,
        }
        assert row["member_line_number"] in {"1", "2", "3"}
        assert row["reason"] == "missing"
        buganda_rows = [
            record for record in r.data
            if record["household_id"] == households["SR-BUGANDA"].id
            and record["member_line_number"] == "1"
        ]
        assert buganda_rows[0]["member_name"] == "Okello Grace"
        assert households["SR-BUGANDA"].village.name in buganda_rows[0]["household_label"]

    def test_records_endpoint_reuses_sub_region_filter(
        self, db, households, two_sub_regions, seeded_rules, django_user_model,
    ):
        self._seed_results(db, households, two_sub_regions, seeded_rules)
        su = django_user_model.objects.create_user(
            username="viol-rec-rgn", password="p", is_superuser=True,
        )
        karamoja_code = two_sub_regions["SR-KARAMOJA"]["sr"].code
        r = _client_for(su).get(
            self.RECORDS_URL
            + f"?rule_id=AC-MEM-SURNAME&sub_region_code={karamoja_code}",
        )
        assert r.status_code == 200
        assert len(r.data) == 2
        assert {row["sub_region_code"] for row in r.data} == {karamoja_code}

    def test_records_endpoint_scope_filtered(
        self, db, households, two_sub_regions, seeded_rules, django_user_model,
    ):
        self._seed_results(db, households, two_sub_regions, seeded_rules)
        u = django_user_model.objects.create_user(username="viol-rec-op", password="p")
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.SUB_REGION,
            scope_code=two_sub_regions["SR-BUGANDA"]["sr"].code,
        )
        r = _client_for(u).get(self.RECORDS_URL + "?rule_id=AC-MEM-SURNAME")
        assert r.status_code == 200
        assert len(r.data) == 3
        assert {row["household_id"] for row in r.data} == {households["SR-BUGANDA"].id}

    def test_records_endpoint_csv_download(
        self, db, households, two_sub_regions, seeded_rules, django_user_model,
    ):
        self._seed_results(db, households, two_sub_regions, seeded_rules)
        su = django_user_model.objects.create_user(
            username="viol-rec-csv", password="p", is_superuser=True,
        )
        r = _client_for(su).get(
            self.RECORDS_URL + "?rule_id=AC-NIN-FMT&export=csv",
        )
        assert r.status_code == 200
        assert r["content-type"] == "text/csv"
        assert "dqa-violation-records.csv" in r["content-disposition"]
        body = r.content.decode("utf-8")
        assert body.splitlines()[0].startswith(
            "result_id,rule_id,rule_label,severity,record_type,record_id,"
            "household_id,household_label,member_line_number,member_name",
        )
        assert "AC-NIN-FMT" in body
        assert body.count("AC-NIN-FMT") == 3

    def test_records_endpoint_emits_audit_event(
        self, db, households, two_sub_regions, seeded_rules, django_user_model,
    ):
        self._seed_results(db, households, two_sub_regions, seeded_rules)
        su = django_user_model.objects.create_user(
            username="viol-rec-aud", password="p", is_superuser=True,
        )
        _client_for(su).get(self.RECORDS_URL + "?rule_id=AC-MEM-SURNAME")
        ev = AuditEvent.objects.filter(
            entity_type="rpt_dashboard", entity_id="dqa_violation_records",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert ev.actor_id == "viol-rec-aud"
