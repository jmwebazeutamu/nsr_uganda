"""Hashing + encryption tests."""

from __future__ import annotations

import pytest
from cryptography.fernet import InvalidToken

from apps.security.encryption import decrypt, encrypt
from apps.security.hashing import nin_hash, nin_last4


class TestNinHash:
    def test_deterministic_for_same_input(self):
        assert nin_hash("CM1234567890AB") == nin_hash("CM1234567890AB")

    def test_normalises_case_and_whitespace(self):
        assert nin_hash("cm1234567890ab") == nin_hash("  CM1234567890AB  ")

    def test_different_nins_produce_different_hashes(self):
        assert nin_hash("CM1234567890AB") != nin_hash("CM1234567890AC")

    def test_includes_pepper_so_not_bare_sha256(self):
        import hashlib
        bare = hashlib.sha256(b"CM1234567890AB").digest()
        assert nin_hash("CM1234567890AB") != bare

    def test_returns_32_bytes(self):
        h = nin_hash("CM1234567890AB")
        assert isinstance(h, bytes) and len(h) == 32

    def test_last4_handles_short_input(self):
        assert nin_last4("AB") == "AB"
        assert nin_last4("CM1234567890AB") == "90AB"


class TestEncryption:
    def test_roundtrip(self):
        plaintext = b"CM1234567890AB"
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_ciphertext_differs_each_call(self):
        # Fernet uses a random IV per encryption; the ciphertext should
        # not be deterministic even for identical plaintext.
        a = encrypt(b"CM1234567890AB")
        b = encrypt(b"CM1234567890AB")
        assert a != b

    def test_decrypt_rejects_garbage(self):
        with pytest.raises(InvalidToken):
            decrypt(b"not-a-valid-fernet-token")

    def test_encrypt_rejects_str(self):
        with pytest.raises(TypeError):
            encrypt("CM1234567890AB")


class TestEncryptedField:
    """End-to-end through the Django field on a real Member row."""

    def test_member_nin_value_roundtrips_via_field(self, db):
        from datetime import date

        from apps.data_management.models import Household, Member
        from apps.reference_data.models import GeographicUnit

        # Minimal 7-level ladder.
        nodes = {}
        for level, key, parent in [
            ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
            ("county", "c", "d"), ("sub_county", "sc", "c"),
            ("parish", "p", "sc"), ("village", "v", "p"),
        ]:
            nodes[key] = GeographicUnit.objects.create(
                level=level, code=f"E-{key.upper()}", name=key.title(),
                parent=nodes.get(parent), effective_from=date(2026, 1, 1),
            )
        hh = Household.objects.create(
            region=nodes["r"], sub_region=nodes["sr"], district=nodes["d"], county=nodes["c"],
            sub_county=nodes["sc"], parish=nodes["p"], village=nodes["v"], urban_rural="2",
        )
        plaintext = b"CM1234567890AB"
        m = Member.objects.create(
            household=hh, line_number=1, surname="Okot", first_name="J", sex="1",
            nin_value=plaintext, nin_hash=nin_hash("CM1234567890AB"),
            nin_last4="90AB", nin_status="1",
        )

        fetched = Member.objects.get(pk=m.pk)
        # The descriptor returns the plaintext bytes that went in.
        assert bytes(fetched.nin_value) == plaintext


class TestDefaultPagination:
    """ADR-0008 / US-S15-004 — ?page_size= is honoured up to
    max_page_size=500. Before ADR-0008 DRF's stock PageNumberPagination
    dropped the param silently and the React side was over-fetching
    home queue panels by 12× (4 wanted, 50 returned)."""

    URL = "/api/v1/reference-data/geographic-units/"

    @pytest.fixture
    def geo_seed(self, db):
        from datetime import date

        from apps.reference_data.models import GeographicUnit
        # 60 geographic units so we can probe both directions of the
        # default (50) and confirm the cap behaviour without seeding
        # 500+ rows.
        for i in range(60):
            GeographicUnit.objects.create(
                level="village", code=f"V-PAG-{i:03d}",
                name=f"Pag village {i}",
                effective_from=date(2026, 1, 1),
            )
        return 60

    def _client(self, django_user_model):
        from rest_framework.test import APIClient
        u = django_user_model.objects.create_user(
            username="pag", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        return c

    def test_default_returns_50(self, geo_seed, django_user_model):
        r = self._client(django_user_model).get(self.URL)
        assert r.status_code == 200
        assert len(r.data["results"]) == 50

    def test_smaller_page_size_honoured(self, geo_seed, django_user_model):
        r = self._client(django_user_model).get(self.URL + "?page_size=4")
        assert r.status_code == 200
        assert len(r.data["results"]) == 4

    def test_larger_page_size_honoured_up_to_cap(
        self, geo_seed, django_user_model,
    ):
        r = self._client(django_user_model).get(self.URL + "?page_size=60")
        assert r.status_code == 200
        assert len(r.data["results"]) == 60

    def test_page_size_above_cap_clamps(self, geo_seed, django_user_model):
        # Cap is 500; seed only has 60 rows so we can only assert the
        # clamp doesn't error and returns at most the available rows.
        # The semantic guarantee is on max_page_size, which the class
        # asserts at the class level — this test proves the request
        # path doesn't 400 and doesn't blow past the data we seeded.
        r = self._client(django_user_model).get(self.URL + "?page_size=10000")
        assert r.status_code == 200
        assert len(r.data["results"]) == 60  # all 60 rows, ≤ 500 cap


class TestMemberPagination:
    """US-S16-003 / ADR-0008 OI-PAG-01 closure — Member endpoint has
    a tighter max_page_size (100) because each row carries the most
    PII surface (NIN ciphertext, NIN last4, phone, DoB)."""

    URL = "/api/v1/data-management/members/"

    @pytest.fixture
    def seed_members(self, db):
        from datetime import date

        from apps.data_management.models import Household, Member
        from apps.reference_data.models import GeographicUnit
        nodes = {}
        for level, key, parent in [
            ("region", "r", None), ("sub_region", "sr", "r"),
            ("district", "d", "sr"), ("county", "c", "d"),
            ("sub_county", "sc", "c"), ("parish", "p", "sc"),
            ("village", "v", "p"),
        ]:
            nodes[key] = GeographicUnit.objects.create(
                level=level, code=f"MP-{key.upper()}", name=key,
                parent=nodes.get(parent), effective_from=date(2026, 1, 1),
            )
        hh = Household.objects.create(
            region=nodes["r"], sub_region=nodes["sr"],
            district=nodes["d"], county=nodes["c"],
            sub_county=nodes["sc"], parish=nodes["p"],
            village=nodes["v"], urban_rural="2",
        )
        # 120 members — past the 100 cap so we can probe the clamp.
        for i in range(120):
            Member.objects.create(
                household=hh, line_number=i + 1,
                surname=f"S{i}", first_name=f"F{i}", sex="1",
            )
        return 120

    def _client(self, django_user_model):
        from rest_framework.test import APIClient
        u = django_user_model.objects.create_user(
            username="memcap", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        return c

    def test_within_cap_honoured(self, seed_members, django_user_model):
        r = self._client(django_user_model).get(self.URL + "?page_size=80")
        assert r.status_code == 200
        assert len(r.data["results"]) == 80

    def test_at_cap_returns_cap(self, seed_members, django_user_model):
        r = self._client(django_user_model).get(self.URL + "?page_size=100")
        assert r.status_code == 200
        assert len(r.data["results"]) == 100

    def test_above_cap_clamps_to_100_not_500(
        self, seed_members, django_user_model,
    ):
        # Ask for 500 (the DefaultPagination cap). MemberPagination
        # should clamp to 100, not the global 500.
        r = self._client(django_user_model).get(self.URL + "?page_size=500")
        assert r.status_code == 200
        assert len(r.data["results"]) == 100


class TestAuditChainVerifier:
    """US-S16-004 — the SQLite-friendly half of the chain integrity
    verifier. The Postgres-only half (chain-break detection on a
    real trigger-installed db) lives in tests/integration/
    test_audit_chain_postgres.py since the trigger only runs there.
    """

    def test_empty_chain_returns_ok_with_empty_mode(self, db):
        from apps.security.integrity import verify_audit_chain
        from apps.security.models import AuditEvent
        AuditEvent.objects.all().delete()
        report = verify_audit_chain()
        assert report.ok is True
        assert report.mode == "empty"
        assert report.rows_scanned == 0
        assert report.breaks == []

    @pytest.mark.sqlite_only
    def test_sqlite_chain_returns_no_chain_mode(self, db):
        from apps.security.audit import emit
        from apps.security.integrity import verify_audit_chain
        from apps.security.models import AuditEvent
        AuditEvent.objects.all().delete()
        emit("create", "test", "id-1", actor="alice")
        emit("update", "test", "id-1", actor="bob")
        report = verify_audit_chain()
        # On SQLite the trigger is a no-op; both hashes are NULL,
        # so the verifier reports no_chain rather than falsely
        # claiming the chain is intact. On Postgres the trigger
        # populates hashes and mode == "verified" — see the
        # @postgres-tagged counterpart in tests/integration/
        # test_audit_chain_postgres.py.
        assert report.ok is True
        assert report.mode == "no_chain"
        assert report.rows_scanned == 2

    @pytest.mark.sqlite_only
    def test_task_logs_no_chain_silently(self, db):
        """The Celery task should NOT emit a noisy audit row on
        SQLite — dev local runs would otherwise spam the log."""
        from apps.security.audit import emit
        from apps.security.models import AuditEvent
        from apps.security.tasks import verify_audit_chain_task
        AuditEvent.objects.all().delete()
        emit("create", "test", "id-1", actor="alice")
        before = AuditEvent.objects.filter(
            action__in=["chain_integrity_verified", "chain_integrity_break"],
        ).count()
        result = verify_audit_chain_task()
        assert result["mode"] == "no_chain"
        assert result["ok"] is True
        after = AuditEvent.objects.filter(
            action__in=["chain_integrity_verified", "chain_integrity_break"],
        ).count()
        assert after == before  # no audit row written on SQLite

    def test_task_registered_on_beat_schedule(self):
        from nsr_mis.celery import app
        tasks = {entry["task"] for entry in app.conf.beat_schedule.values()}
        assert "apps.security.tasks.verify_audit_chain_task" in tasks

    def test_verify_chain_endpoint_returns_report(self, db, django_user_model):
        from rest_framework.test import APIClient

        from apps.security.models import AuditEvent

        AuditEvent.objects.all().delete()
        user = django_user_model.objects.create_user(username="audit-admin")
        client = APIClient()
        client.force_authenticate(user)

        resp = client.post("/api/v1/security/audit-events/verify-chain/", {}, format="json")

        assert resp.status_code == 200
        assert resp.data["ok"] is True
        assert resp.data["mode"] == "empty"
        assert resp.data["rows_scanned"] == 0
        assert resp.data["breaks"] == []


class TestChainBreakAlerts:
    """US-S18-004 — on chain_integrity_break, the task notifies the DPO
    out-of-band via Slack webhook (preferred) and/or email. Both
    channels default to no-op when their respective env settings
    aren't configured, so dev/CI doesn't accidentally fire.
    """

    def _seed_breaks(self):
        """Build a synthetic break report so tests don't depend on the
        Postgres trigger (this suite stays SQLite-friendly)."""
        from apps.security.integrity import ChainBreak, ChainReport
        return ChainReport(
            ok=False, mode="verified", rows_scanned=42,
            breaks=[ChainBreak(
                event_id="01TESTBREAK00000000000000",
                expected_prev_hash=None, actual_prev_hash=b"\x00" * 32,
                occurred_at="2026-05-15T10:00:00+00:00",
            )],
        )

    def test_notify_is_noop_when_no_env(self, db, settings):
        from apps.security.tasks import _notify_chain_break
        settings.SLACK_WEBHOOK_URL = ""
        settings.DPO_EMAIL = ""
        report = self._seed_breaks()
        # No webhook + no email → returns False/False. Doesn't raise.
        result = _notify_chain_break(report)
        assert result["slack_sent"] is False
        assert result["email_sent"] is False

    def test_notify_sends_to_slack_when_url_set(self, db, settings):
        from unittest.mock import patch

        from apps.security.tasks import _notify_chain_break
        settings.SLACK_WEBHOOK_URL = "https://hooks.slack.example/T/B/X"
        settings.DPO_EMAIL = ""
        report = self._seed_breaks()
        with patch("apps.security.tasks.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            result = _notify_chain_break(report)
        assert result["slack_sent"] is True
        assert mock_post.called
        call_args = mock_post.call_args
        assert call_args.args[0] == "https://hooks.slack.example/T/B/X"
        body_text = str(call_args.kwargs.get("json") or {})
        assert "1 break" in body_text or "chain_integrity_break" in body_text

    def test_notify_emails_dpo_when_address_set(self, db, settings):
        from unittest.mock import patch

        from apps.security.tasks import _notify_chain_break
        settings.SLACK_WEBHOOK_URL = ""
        settings.DPO_EMAIL = "dpo@example.org"
        report = self._seed_breaks()
        with patch("apps.security.tasks.send_mail", return_value=1) as mock_send:
            result = _notify_chain_break(report)
        assert result["email_sent"] is True
        # send_mail(subject, message, from_email, recipient_list)
        args = mock_send.call_args.args
        kwargs = mock_send.call_args.kwargs
        recipients = args[3] if len(args) >= 4 else kwargs.get("recipient_list")
        assert "dpo@example.org" in recipients

    def test_notify_swallows_slack_failure(self, db, settings):
        """A flaky webhook shouldn't crash the celery task or hide the
        audit row that was already written."""
        from unittest.mock import patch

        from apps.security.tasks import _notify_chain_break
        settings.SLACK_WEBHOOK_URL = "https://hooks.slack.example/T/B/X"
        settings.DPO_EMAIL = ""
        report = self._seed_breaks()
        with patch(
            "apps.security.tasks.requests.post",
            side_effect=RuntimeError("network down"),
        ) as mock_post:
            result = _notify_chain_break(report)
        assert result["slack_sent"] is False
        assert mock_post.called

    @pytest.mark.sqlite_only
    def test_task_skips_notify_on_no_chain(self, db, settings):
        """On a SQLite/no-trigger backend the task short-circuits
        before alerting anything."""
        from unittest.mock import patch

        from apps.security.audit import emit
        from apps.security.models import AuditEvent
        from apps.security.tasks import verify_audit_chain_task
        settings.SLACK_WEBHOOK_URL = "https://hooks.slack.example/T/B/X"
        AuditEvent.objects.all().delete()
        emit("create", "test", "id-1", actor="alice")
        with patch("apps.security.tasks._notify_chain_break") as mock_notify:
            result = verify_audit_chain_task()
        assert result["mode"] == "no_chain"
        assert not mock_notify.called


@pytest.mark.django_db
class TestUsersMe:
    """GET /api/v1/security/users/me/ — identity endpoint the React
    shell reads on mount to show the real authenticated user in the
    topbar. Returns role + partner derived from OperatorScope."""

    URL = "/api/v1/security/users/me/"

    def test_anonymous_is_unauthorised(self, db):
        from rest_framework.test import APIClient
        r = APIClient().get(self.URL)
        assert r.status_code in (401, 403)

    def test_superuser_resolves_to_nsr_unit_role(
        self, db, django_user_model,
    ):
        from rest_framework.test import APIClient
        u = django_user_model.objects.create_superuser(
            username="ms-test-super", password="p",
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.get(self.URL)
        assert r.status_code == 200
        assert r.data["username"] == "ms-test-super"
        assert r.data["is_superuser"] is True
        assert r.data["role"] == "nsr-unit"
        assert r.data["partner"] is None

    def test_partner_scoped_user_resolves_partner_payload(
        self, db, django_user_model,
    ):
        from rest_framework.test import APIClient

        from apps.partners.models import Partner
        from apps.security.models import OperatorScope, ScopeLevel

        Partner.objects.create(
            code="OPM-T", name="OPM (test)", type="ministry",
            sector="social_protection", status="active", tone="system",
        )
        u = django_user_model.objects.create_user(
            username="ms-test-opm", password="p",
        )
        OperatorScope.objects.create(
            user=u, scope_level=ScopeLevel.PARTNER, scope_code="OPM-T",
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.get(self.URL)
        assert r.status_code == 200
        assert r.data["role"] == "partner-analyst"
        assert r.data["partner"]["code"] == "OPM-T"
        assert r.data["partner"]["name"] == "OPM (test)"

    def test_user_with_no_scope_falls_back_to_operator(
        self, db, django_user_model,
    ):
        from rest_framework.test import APIClient
        u = django_user_model.objects.create_user(
            username="ms-test-ghost", password="p",
        )
        c = APIClient()
        c.force_authenticate(user=u)
        r = c.get(self.URL)
        assert r.status_code == 200
        # No superuser flag, no partner scope — role hint is "operator"
        # rather than the more privileged "nsr-unit".
        assert r.data["role"] == "operator"
        assert r.data["partner"] is None
        assert r.data["is_superuser"] is False


# --- US-S11-028 — OperatorScope management API ---------------------------

from datetime import date  # noqa: E402

from rest_framework.test import APIClient  # noqa: E402

from apps.reference_data.models import GeographicUnit  # noqa: E402
from apps.security.models import OperatorScope, ScopeLevel  # noqa: E402


@pytest.fixture
def geo_ladder(db):
    """Region → Sub-Region → District seeded so bulk-grant validation
    has real GeographicUnit rows to match against."""
    region = GeographicUnit.objects.create(
        level="region", code="R-CENTRAL", name="Central",
        parent=None, effective_from=date(2026, 1, 1),
    )
    sub_region = GeographicUnit.objects.create(
        level="sub_region", code="SR-BUGANDA-SOUTH", name="Buganda South",
        parent=region, effective_from=date(2026, 1, 1),
    )
    d_wakiso = GeographicUnit.objects.create(
        level="district", code="D-WAKISO", name="Wakiso",
        parent=sub_region, effective_from=date(2026, 1, 1),
    )
    d_kampala = GeographicUnit.objects.create(
        level="district", code="D-KAMPALA", name="Kampala",
        parent=sub_region, effective_from=date(2026, 1, 1),
    )
    return {
        "region": region, "sub_region": sub_region,
        "districts": [d_wakiso, d_kampala],
    }


def _nsr_admin(django_user_model):
    from django.contrib.auth.models import Group
    user = django_user_model.objects.create_user(
        username="scope-admin", password="x",
    )
    grp, _ = Group.objects.get_or_create(name="nsr_admin")
    user.groups.add(grp)
    return user


def _plain_user(
    django_user_model, username="ops-grace",
    first_name="Grace", last_name="Akello",
):
    return django_user_model.objects.create_user(
        username=username, password="x",
        first_name=first_name, last_name=last_name,
    )


@pytest.mark.django_db
class TestOperatorScopeListAndDelete:
    def test_anonymous_caller_gets_403(self):
        client = APIClient()
        resp = client.get("/api/v1/security/operator-scopes/")
        assert resp.status_code in (401, 403)

    def test_non_admin_authenticated_gets_403(self, django_user_model):
        u = _plain_user(django_user_model)
        client = APIClient()
        client.force_authenticate(u)
        resp = client.get("/api/v1/security/operator-scopes/")
        assert resp.status_code == 403

    def test_list_returns_scope_label_and_display_name(
        self, django_user_model, geo_ladder,
    ):
        admin = _nsr_admin(django_user_model)
        target = _plain_user(django_user_model)
        OperatorScope.objects.create(
            user=target, scope_level=ScopeLevel.DISTRICT,
            scope_code="D-WAKISO", granted_by="seeded",
        )
        client = APIClient()
        client.force_authenticate(admin)
        resp = client.get("/api/v1/security/operator-scopes/")
        assert resp.status_code == 200, resp.content
        results = resp.json().get("results", resp.json())
        row = results[0]
        assert row["username"] == "ops-grace"
        assert row["display_name"] == "Grace Akello"
        # scope_label resolves "D-WAKISO" against GeographicUnit.
        assert "Wakiso" in row["scope_label"]

    def test_destroy_emits_audit_and_removes_row(
        self, django_user_model, geo_ladder,
    ):
        admin = _nsr_admin(django_user_model)
        target = _plain_user(django_user_model)
        scope = OperatorScope.objects.create(
            user=target, scope_level=ScopeLevel.DISTRICT,
            scope_code="D-WAKISO", granted_by="seeded",
        )
        client = APIClient()
        client.force_authenticate(admin)
        resp = client.delete(f"/api/v1/security/operator-scopes/{scope.id}/")
        assert resp.status_code == 204
        assert not OperatorScope.objects.filter(id=scope.id).exists()
        from apps.security.models import AuditEvent
        ev = AuditEvent.objects.filter(
            action="security.operator_scope.revoked",
        ).first()
        assert ev is not None
        assert "D-WAKISO" in ev.reason


@pytest.mark.django_db
class TestOperatorScopeBulkGrant:
    def _url(self) -> str:
        return "/api/v1/security/operator-scopes/bulk-grant/"

    def test_grants_multiple_districts_in_one_call(
        self, django_user_model, geo_ladder,
    ):
        admin = _nsr_admin(django_user_model)
        target = _plain_user(django_user_model)
        client = APIClient()
        client.force_authenticate(admin)
        resp = client.post(
            self._url(),
            {
                "user_id": target.id,
                "scope_level": "district",
                "scope_codes": ["D-WAKISO", "D-KAMPALA"],
                "note": "field ops",
            },
            format="json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert len(body["granted"]) == 2
        assert body["skipped_existing"] == []
        codes = {s["scope_code"] for s in body["granted"]}
        assert codes == {"D-WAKISO", "D-KAMPALA"}
        # Every grant emits its own audit event.
        from apps.security.models import AuditEvent
        events = AuditEvent.objects.filter(
            action="security.operator_scope.granted",
        )
        assert events.count() == 2

    def test_unknown_district_code_rejects_the_whole_call(
        self, django_user_model, geo_ladder,
    ):
        admin = _nsr_admin(django_user_model)
        target = _plain_user(django_user_model)
        client = APIClient()
        client.force_authenticate(admin)
        resp = client.post(
            self._url(),
            {
                "user_id": target.id,
                "scope_level": "district",
                "scope_codes": ["D-WAKISO", "D-OOPS"],
            },
            format="json",
        )
        assert resp.status_code == 400
        assert "D-OOPS" in str(resp.json())
        # No partial grants — atomic-feeling 400 is the contract.
        assert OperatorScope.objects.filter(user=target).count() == 0

    def test_idempotent_on_duplicate(
        self, django_user_model, geo_ladder,
    ):
        admin = _nsr_admin(django_user_model)
        target = _plain_user(django_user_model)
        OperatorScope.objects.create(
            user=target, scope_level=ScopeLevel.DISTRICT,
            scope_code="D-WAKISO", granted_by="seeded",
        )
        client = APIClient()
        client.force_authenticate(admin)
        resp = client.post(
            self._url(),
            {
                "user_id": target.id,
                "scope_level": "district",
                "scope_codes": ["D-WAKISO", "D-KAMPALA"],
            },
            format="json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert {s["scope_code"] for s in body["granted"]} == {"D-KAMPALA"}
        assert body["skipped_existing"] == ["D-WAKISO"]

    def test_national_takes_empty_codes(
        self, django_user_model, geo_ladder,
    ):
        admin = _nsr_admin(django_user_model)
        target = _plain_user(django_user_model)
        client = APIClient()
        client.force_authenticate(admin)
        resp = client.post(
            self._url(),
            {
                "user_id": target.id,
                "scope_level": "national",
                "scope_codes": [],
                "note": "DPO wildcard",
            },
            format="json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert len(body["granted"]) == 1
        assert body["granted"][0]["scope_code"] == ""

    def test_national_with_code_is_rejected(
        self, django_user_model, geo_ladder,
    ):
        admin = _nsr_admin(django_user_model)
        target = _plain_user(django_user_model)
        client = APIClient()
        client.force_authenticate(admin)
        resp = client.post(
            self._url(),
            {
                "user_id": target.id,
                "scope_level": "national",
                "scope_codes": ["R-CENTRAL"],
            },
            format="json",
        )
        assert resp.status_code == 400
        assert "national" in str(resp.json())

    def test_non_admin_gets_403(self, django_user_model, geo_ladder):
        u = _plain_user(django_user_model)
        client = APIClient()
        client.force_authenticate(u)
        resp = client.post(
            self._url(),
            {
                "user_id": u.id,
                "scope_level": "district",
                "scope_codes": ["D-WAKISO"],
            },
            format="json",
        )
        assert resp.status_code == 403


@pytest.mark.django_db
class TestUserSearch:
    def test_returns_matches_by_username_or_name(self, django_user_model):
        admin = _nsr_admin(django_user_model)
        _plain_user(django_user_model, username="ops-grace",
                    first_name="Grace", last_name="Akello")
        _plain_user(django_user_model, username="ops-pete",
                    first_name="Pete", last_name="Onyango")
        client = APIClient()
        client.force_authenticate(admin)
        resp = client.get("/api/v1/security/users/?q=grace")
        assert resp.status_code == 200
        usernames = {u["username"] for u in resp.json()}
        assert usernames == {"ops-grace"}
        # Match by display-name substring too.
        resp = client.get("/api/v1/security/users/?q=onyango")
        assert {u["username"] for u in resp.json()} == {"ops-pete"}

    def test_blank_query_returns_first_50(self, django_user_model):
        admin = _nsr_admin(django_user_model)
        # Plant 5 — far under the cap.
        for i in range(5):
            _plain_user(django_user_model, username=f"u{i}")
        client = APIClient()
        client.force_authenticate(admin)
        resp = client.get("/api/v1/security/users/")
        assert resp.status_code == 200
        assert len(resp.json()) >= 5  # admin + 5 = 6 users

    def test_non_admin_gets_403(self, django_user_model):
        u = _plain_user(django_user_model)
        client = APIClient()
        client.force_authenticate(u)
        resp = client.get("/api/v1/security/users/")
        assert resp.status_code == 403
