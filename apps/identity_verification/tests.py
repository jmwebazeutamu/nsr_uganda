"""NIRA mock tests."""

from __future__ import annotations

import pytest

from apps.identity_verification.mock import NiraError, verify_nin


class TestVerifyNin:
    def test_match_returns_demographics(self):
        result = verify_nin("CM1234567890AB")
        assert result["status"] == "match"
        demo = result["demographics"]
        assert demo["nin"] == "CM1234567890AB"
        # ChoiceOption code on the seeded sex list (1=Male).
        assert demo["sex"] == "1"

    def test_female_prefix_returns_f(self):
        # ChoiceOption code on the seeded sex list (2=Female).
        assert verify_nin("CF1234567890AB")["demographics"]["sex"] == "2"

    def test_no_match_suffix(self):
        assert verify_nin("CM1234567890NM") == {"status": "no_match"}

    def test_mismatch_suffix(self):
        result = verify_nin("CM1234567890MM")
        assert result["status"] == "mismatch"

    def test_service_unavailable_suffix_raises(self):
        with pytest.raises(NiraError):
            verify_nin("CM1234567890SU")

    def test_bad_format(self):
        result = verify_nin("BADNIN")
        assert result["status"] == "bad_format"


class TestVerifyApi:
    @pytest.fixture(autouse=True)
    def enable_debug(self, settings):
        settings.DEBUG = True

    @pytest.fixture
    def auth_client(self, db, client, django_user_model):
        user = django_user_model.objects.create_user(username="t-user", password="t-pass")
        client.force_login(user)
        return client

    def test_endpoint_returns_match(self, auth_client):
        r = auth_client.post("/api/v1/idv/nira-mock/verify",
                             data='{"nin": "CM1234567890AB"}',
                             content_type="application/json")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "match"

    def test_endpoint_service_unavailable(self, auth_client):
        r = auth_client.post("/api/v1/idv/nira-mock/verify",
                             data='{"nin": "CM1234567890SU"}',
                             content_type="application/json")
        assert r.status_code == 503

    def test_endpoint_disabled_outside_debug(self, auth_client, settings):
        settings.DEBUG = False
        r = auth_client.post("/api/v1/idv/nira-mock/verify",
                             data='{"nin": "CM1234567890AB"}',
                             content_type="application/json")
        assert r.status_code == 404

    def test_endpoint_refuses_unauthenticated(self, db, client):
        # Sprint 1 security gate: no auth -> 403.
        r = client.post("/api/v1/idv/nira-mock/verify",
                        data='{"nin": "CM1234567890AB"}',
                        content_type="application/json")
        assert r.status_code == 403


class TestNiraClientFactory:
    """SAD §4.5 provider seam — callers call get_nira_client(), so the
    mock-vs-live decision is one settings flag instead of conditional
    code at every call site."""

    def test_default_provider_is_mock(self, settings):
        from apps.identity_verification.client import (
            MockNiraClient,
            get_nira_client,
        )
        # Default is "mock" per settings; ensure the factory returns it.
        settings.NIRA_PROVIDER = "mock"
        assert isinstance(get_nira_client(), MockNiraClient)

    def test_mock_client_delegates_to_mock_module(self, settings):
        from apps.identity_verification.client import get_nira_client
        settings.NIRA_PROVIDER = "mock"
        r = get_nira_client().verify_nin("CM1234567890AB")
        assert r["status"] == "match"

    def test_live_client_selected_when_flag_set(self, settings):
        from apps.identity_verification.client import (
            LiveNiraClient,
            get_nira_client,
        )
        settings.NIRA_PROVIDER = "live"
        assert isinstance(get_nira_client(), LiveNiraClient)

    def test_live_client_raises_not_implemented(self, settings):
        from apps.identity_verification.client import get_nira_client
        settings.NIRA_PROVIDER = "live"
        with pytest.raises(NotImplementedError, match="NIRA-O-01"):
            get_nira_client().verify_nin("CM1234567890AB")

    def test_unknown_provider_raises_value_error(self, settings):
        from apps.identity_verification.client import get_nira_client
        settings.NIRA_PROVIDER = "neither"
        with pytest.raises(ValueError, match="NIRA_PROVIDER"):
            get_nira_client()

    def test_provider_choice_re_read_per_call(self, settings):
        """Per-test settings override must take effect on the very next
        call — important because the factory is invoked from request
        handlers, not bound at module import."""
        from apps.identity_verification.client import (
            LiveNiraClient,
            MockNiraClient,
            get_nira_client,
        )
        settings.NIRA_PROVIDER = "mock"
        assert isinstance(get_nira_client(), MockNiraClient)
        settings.NIRA_PROVIDER = "live"
        assert isinstance(get_nira_client(), LiveNiraClient)


class TestQueueAndRetry:
    """S5-005 — queue_verification persists outages, drain_queue retries
    on the exponential backoff schedule (60s, 300s, 3600s, 24h, FAILED)."""

    def test_successful_first_call_marks_succeeded(self, db, settings):
        from apps.identity_verification.models import AttemptStatus
        from apps.identity_verification.queue import queue_verification
        settings.NIRA_PROVIDER = "mock"
        attempt = queue_verification("CM1234567890AB", requester="enum-1")
        assert attempt.status == AttemptStatus.SUCCEEDED
        assert attempt.attempts == 1
        assert attempt.result_payload is not None
        assert attempt.completed_at is not None

    def test_nira_error_lands_in_queue_with_backoff(self, db, settings):
        from apps.identity_verification.models import AttemptStatus
        from apps.identity_verification.queue import queue_verification
        settings.NIRA_PROVIDER = "mock"
        attempt = queue_verification("CM1234567890SU", requester="enum-2")
        assert attempt.status == AttemptStatus.QUEUED
        assert attempt.attempts == 1
        assert "service_unavailable" in attempt.last_error
        # First-failure backoff is 60s.
        from django.utils import timezone
        wait = (attempt.next_retry_at - timezone.now()).total_seconds()
        assert 55 < wait <= 60

    def test_raw_nin_never_persisted(self, db, settings):
        """The queue stores nin_hash only — the raw NIN must never land
        in the row's columns, including last_error."""
        from apps.identity_verification.queue import queue_verification
        settings.NIRA_PROVIDER = "mock"
        nin = "CM1234567890SU"
        attempt = queue_verification(nin)
        # Hash is present; raw is absent from every text column.
        assert len(bytes(attempt.nin_hash)) > 0
        assert nin not in attempt.last_error
        assert nin not in str(attempt.result_payload or "")
        assert nin not in attempt.requester

    def test_backoff_schedule_progresses(self, db, settings):
        from datetime import timedelta

        from django.utils import timezone

        from apps.identity_verification.models import (
            AttemptStatus,
            NiraVerificationAttempt,
        )
        from apps.identity_verification.queue import drain_queue
        settings.NIRA_PROVIDER = "mock"
        # Seed a QUEUED attempt with attempts=1 already and next_retry_at in
        # the past so drain picks it up. Use the SU suffix so retry fails.
        from apps.security.hashing import nin_hash as _h
        nin = "CM1234567890SU"
        NiraVerificationAttempt.objects.create(
            nin_hash=_h(nin), requester="x", status=AttemptStatus.QUEUED,
            attempts=1, last_error="prev",
            next_retry_at=timezone.now() - timedelta(seconds=10),
        )
        counts = drain_queue(lambda h: nin)
        assert counts["processed"] == 1
        assert counts["requeued"] == 1
        # After the second failed call, next_retry_at should be ~300s away.
        a = NiraVerificationAttempt.objects.get()
        assert a.attempts == 2
        wait = (a.next_retry_at - timezone.now()).total_seconds()
        assert 295 < wait <= 300

    def test_max_attempts_marks_failed(self, db, settings):
        from datetime import timedelta

        from django.utils import timezone

        from apps.identity_verification.models import (
            AttemptStatus,
            NiraVerificationAttempt,
        )
        from apps.identity_verification.queue import MAX_ATTEMPTS, drain_queue
        settings.NIRA_PROVIDER = "mock"
        from apps.security.hashing import nin_hash as _h
        nin = "CM1234567890SU"
        # Simulate having already burned through MAX-1 attempts.
        NiraVerificationAttempt.objects.create(
            nin_hash=_h(nin), requester="x", status=AttemptStatus.QUEUED,
            attempts=MAX_ATTEMPTS - 1, last_error="prev",
            next_retry_at=timezone.now() - timedelta(seconds=10),
        )
        drain_queue(lambda h: nin)
        a = NiraVerificationAttempt.objects.get()
        assert a.status == AttemptStatus.FAILED
        assert a.completed_at is not None

    def test_successful_retry_marks_succeeded(self, db, settings):
        from datetime import timedelta

        from django.utils import timezone

        from apps.identity_verification.models import (
            AttemptStatus,
            NiraVerificationAttempt,
        )
        from apps.identity_verification.queue import drain_queue
        settings.NIRA_PROVIDER = "mock"
        from apps.security.hashing import nin_hash as _h
        # Seed an attempt for a NIN that will SUCCEED on retry (not SU).
        good_nin = "CM1234567890AB"
        NiraVerificationAttempt.objects.create(
            nin_hash=_h(good_nin), requester="x",
            status=AttemptStatus.QUEUED, attempts=1, last_error="transient",
            next_retry_at=timezone.now() - timedelta(seconds=10),
        )
        counts = drain_queue(lambda h: good_nin)
        assert counts["succeeded"] == 1
        a = NiraVerificationAttempt.objects.get()
        assert a.status == AttemptStatus.SUCCEEDED
        assert a.result_payload["status"] == "match"

    def test_unresolved_nin_marks_failed(self, db, settings):
        from datetime import timedelta

        from django.utils import timezone

        from apps.identity_verification.models import (
            AttemptStatus,
            NiraVerificationAttempt,
        )
        from apps.identity_verification.queue import drain_queue
        settings.NIRA_PROVIDER = "mock"
        NiraVerificationAttempt.objects.create(
            nin_hash=b"\x00" * 32, requester="x",
            status=AttemptStatus.QUEUED, attempts=1, last_error="prev",
            next_retry_at=timezone.now() - timedelta(seconds=10),
        )
        # Resolver always returns None — simulates merged-loser case.
        counts = drain_queue(lambda h: None)
        assert counts["unresolved"] == 1
        a = NiraVerificationAttempt.objects.get()
        assert a.status == AttemptStatus.FAILED
        assert "resolvable" in a.last_error

    def test_drain_skips_not_yet_due(self, db, settings):
        from datetime import timedelta

        from django.utils import timezone

        from apps.identity_verification.models import (
            AttemptStatus,
            NiraVerificationAttempt,
        )
        from apps.identity_verification.queue import drain_queue
        settings.NIRA_PROVIDER = "mock"
        NiraVerificationAttempt.objects.create(
            nin_hash=b"\x01" * 32, requester="x",
            status=AttemptStatus.QUEUED, attempts=1, last_error="prev",
            next_retry_at=timezone.now() + timedelta(minutes=10),
        )
        counts = drain_queue(lambda h: "CM1234567890AB")
        assert counts["processed"] == 0

    def test_management_command_runs(self, db, settings, capsys):
        from django.core.management import call_command
        settings.NIRA_PROVIDER = "mock"
        # No rows pending — command should still run cleanly and log.
        call_command("drain_nira_queue")
        out = capsys.readouterr().out
        assert "drain_nira_queue" in out


class TestCeleryTask:
    """S6-004 — drain_nira_queue_task wraps the same drain_queue
    logic as the management command. Tests invoke .run() directly
    (CELERY_TASK_ALWAYS_EAGER=True in test settings) — no broker
    needed."""

    def test_task_runs_with_empty_queue(self, db, settings):
        from apps.identity_verification.tasks import drain_nira_queue_task
        settings.NIRA_PROVIDER = "mock"
        result = drain_nira_queue_task.run()
        assert result == {"processed": 0, "succeeded": 0, "requeued": 0,
                          "failed": 0, "unresolved": 0}

    def test_task_processes_due_attempt(self, db, settings):
        from datetime import timedelta

        from django.utils import timezone

        from apps.data_management.models import Household, Member
        from apps.identity_verification.models import (
            AttemptStatus,
            NiraVerificationAttempt,
        )
        from apps.identity_verification.tasks import drain_nira_queue_task
        from apps.reference_data.models import GeographicUnit
        from apps.security.hashing import nin_hash as _h
        settings.NIRA_PROVIDER = "mock"

        # Need a Member with the nin_hash so the resolver finds it.
        from datetime import date as _date
        nodes = {}
        parent = None
        for level in ("region", "sub_region", "district", "county",
                      "sub_county", "parish", "village"):
            n = GeographicUnit.objects.create(
                level=level, code=f"CEL-{level}", name=level,
                parent=parent, effective_from=_date(2026, 1, 1),
            )
            nodes[level] = n
            parent = n
        hh = Household.objects.create(
            region=nodes["region"], sub_region=nodes["sub_region"],
            district=nodes["district"], county=nodes["county"],
            sub_county=nodes["sub_county"], parish=nodes["parish"],
            village=nodes["village"], urban_rural="2",
        )
        good_nin = "CM1234567890AB"
        Member.objects.create(
            household=hh, line_number=1, surname="X", first_name="Y",
            sex="1", nin_hash=_h(good_nin),
            nin_value=good_nin.encode("ascii"),
        )
        NiraVerificationAttempt.objects.create(
            nin_hash=_h(good_nin), requester="x",
            status=AttemptStatus.QUEUED, attempts=1, last_error="prev",
            next_retry_at=timezone.now() - timedelta(seconds=10),
        )
        result = drain_nira_queue_task.run()
        assert result["succeeded"] == 1
        a = NiraVerificationAttempt.objects.get()
        assert a.status == AttemptStatus.SUCCEEDED


class TestBeatSchedule:
    """The Celery beat schedule is the source of truth for which
    sweeps run automatically in production. A regression test catches
    accidental renames + ensures both S5 sweeps stay scheduled."""

    def test_schedule_includes_drain_and_expire(self):
        from nsr_mis.celery import app
        schedule = app.conf.beat_schedule
        tasks = {entry["task"] for entry in schedule.values()}
        assert "apps.identity_verification.tasks.drain_nira_queue_task" in tasks
        assert "apps.data_requests.tasks.expire_data_requests_task" in tasks
