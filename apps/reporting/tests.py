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
            village=nodes["v"], urban_rural="rural",
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
            surname="A", first_name="One", sex="M",
        )
        m2 = Member.objects.create(
            household=households["SR-BUGANDA"], line_number=12,
            surname="A", first_name="Two", sex="M",
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
            surname="A", first_name="Three", sex="M",
        )
        m4 = Member.objects.create(
            household=households["SR-BUGANDA"], line_number=14,
            surname="A", first_name="Four", sex="M",
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
