"""US-114 restore — UBOS bulk and NIRA reverse-feed as live DIH connectors.

End-to-end coverage of the two kinds that left "(coming soon)":

UBOS bulk (file drop)
- credentials_for / run_test_connection through UbosCredential
- GET  /source-systems/{id}/forms/   lists drop files with the checksum gate
- POST /source-systems/{id}/trigger-run/ lands + stages the file rows,
  pins the file, skips duplicates on re-pull, honours dry-run
- the Celery beat task now visits UBOS sources

NIRA reverse-feed (push)
- credentials_for / run_test_connection through NiraCredential (probe
  goes through the IDV provider seam — mock in tests)
- POST /nira/vital-events/  signature gate, death auto-commit,
  idempotent replay, birth + unknown-NIN quarantine, malformed 400,
  unconfigured 503
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.data_management.models import Household, Member
from apps.reference_data.models import GeographicUnit
from apps.security.hashing import nin_hash as _h
from apps.security.models import AuditEvent
from apps.update_workflow.models import ChangeRequest, ChangeStatus

from .connection_test import (
    PULL_KINDS,
    SUPPORTED_KINDS,
    CredentialMissingError,
    credentials_for,
    run_test_connection,
)
from .connectors.nira_vital import sign_body
from .models import (
    Connector,
    ConnectorRun,
    ConnectorRunStatus,
    ConnectorRunType,
    DataProvisionAgreement,
    NiraCredential,
    Quarantine,
    RawLanding,
    SourceSystem,
    SourceSystemKind,
    StageRecord,
    UbosCredential,
)
from .services import resolve_pinned_form_uid

pytestmark = pytest.mark.django_db

NIRA_SECRET = "test-webhook-secret"  # noqa: S105 — synthetic


# --- Shared fixtures --------------------------------------------------------

@pytest.fixture
def geo_codes(db):
    """7-level UBOS ladder referenced by the staged payloads."""
    parent = None
    out = {}
    for level in ("region", "sub_region", "district", "county",
                  "sub_county", "parish", "village"):
        code = f"UN-{level}"
        parent = GeographicUnit.objects.create(
            level=level, code=code, name=code, parent=parent,
            effective_from=date(2026, 1, 1),
        )
        out[level] = code
    return out


def _admin_client(django_user_model, name="u-nsr-admin"):
    from django.contrib.auth.models import Group
    user = django_user_model.objects.create_user(username=name, password="x")
    grp, _ = Group.objects.get_or_create(name="nsr_admin")
    user.groups.add(grp)
    client = APIClient()
    client.force_authenticate(user)
    return client, user


def _household(geo: dict, head: str) -> dict:
    return {
        "geographic": dict(geo),
        "urban_rural": "rural",
        "address_narrative": f"{head} homestead",
        "gps_lat": "1.234567", "gps_lng": "33.000000", "gps_accuracy_m": "5.00",
        "members": [
            {"surname": head, "first_name": "James", "sex": "M",
             "relationship_to_head": "01", "is_head": True},
            {"surname": head, "first_name": "Mary", "sex": "F",
             "relationship_to_head": "02"},
        ],
    }


def _drop_file(drop, name: str, rows: list[dict]) -> str:
    path = drop / name
    path.write_text(json.dumps(rows), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(name + ".sha256").write_text(f"{digest}  {name}\n")
    return digest


@pytest.fixture
def ubos_source(db, tmp_path):
    """UBOS-BULK with DPA + drop credential (code matches the registered
    connector)."""
    drop = tmp_path / "ubos-drop"
    drop.mkdir()
    src = SourceSystem.objects.create(
        code="UBOS-BULK", name="UBOS mass enumeration", kind=SourceSystemKind.UBOS,
    )
    UbosCredential.objects.create(source_system=src, drop_path=str(drop))
    DataProvisionAgreement.objects.create(
        source_system=src, reference="DPA-UBOS-TEST",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
        residence_policy_days=90,
    )
    src.drop = drop  # test convenience
    return src


@pytest.fixture
def nira_source(db):
    src = SourceSystem.objects.create(
        code="NIRA-REVERSE", name="NIRA reverse-feed", kind=SourceSystemKind.NIRA,
    )
    NiraCredential.objects.create(
        source_system=src, webhook_secret_encrypted=NIRA_SECRET,
        configured_by_username="dpo",
    )
    DataProvisionAgreement.objects.create(
        source_system=src, reference="DPA-NIRA-TEST",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
        residence_policy_days=90,
    )
    return src


@pytest.fixture
def member_with_nin(db):
    nodes = {}
    parent = None
    for level in ("region", "sub_region", "district", "county",
                  "sub_county", "parish", "village"):
        parent = GeographicUnit.objects.create(
            level=level, code=f"NR-{level}", name=level,
            parent=parent, effective_from=date(2026, 1, 1),
        )
        nodes[level] = parent
    hh = Household.objects.create(
        region=nodes["region"], sub_region=nodes["sub_region"],
        district=nodes["district"], county=nodes["county"],
        sub_county=nodes["sub_county"], parish=nodes["parish"],
        village=nodes["village"], urban_rural="2",
    )
    nin = "CM1234567890AB"
    m = Member.objects.create(
        household=hh, line_number=1, surname="Okot", first_name="James",
        sex="1", nin_hash=_h(nin), nin_value=nin.encode("ascii"),
    )
    return m, nin


def _post_event(client, payload: dict, *, secret: str | None = NIRA_SECRET, header=None):
    body = json.dumps(payload).encode("utf-8")
    kwargs = {}
    if header is not None:
        kwargs["HTTP_X_NIRA_SIGNATURE"] = header
    elif secret is not None:
        kwargs["HTTP_X_NIRA_SIGNATURE"] = sign_body(secret, body)
    return client.post(
        "/api/v1/dih/nira/vital-events/", data=body,
        content_type="application/json", **kwargs,
    )


# --- Kind gates ---------------------------------------------------------------

class TestKindGates:
    def test_supported_and_pull_sets(self):
        assert SUPPORTED_KINDS == {
            SourceSystemKind.KOBO, SourceSystemKind.UBOS, SourceSystemKind.NIRA,
        }
        assert PULL_KINDS == {SourceSystemKind.KOBO, SourceSystemKind.UBOS}
        assert SourceSystemKind.NIRA not in PULL_KINDS  # push-based

    def test_nira_kind_is_a_model_choice(self):
        assert SourceSystemKind.NIRA == "nira"
        assert dict(SourceSystemKind.choices)["nira"].startswith("NIRA")


# --- UBOS: credentials + test connection --------------------------------------

class TestUbosCredentials:
    def test_credentials_for_shape(self, ubos_source):
        creds = credentials_for(ubos_source)
        assert creds == {"drop_path": str(ubos_source.drop), "require_checksum": True}

    def test_missing_credential_row(self, db):
        src = SourceSystem.objects.create(
            code="UBOS-BULK", name="UBOS", kind=SourceSystemKind.UBOS,
        )
        with pytest.raises(CredentialMissingError, match="UBOS bulk credential"):
            credentials_for(src)

    def test_run_test_connection_records_run_and_freshness(self, ubos_source):
        _drop_file(ubos_source.drop, "hh.json", [])
        run, result = run_test_connection(ubos_source, actor="admin-user")
        assert result.ok is True
        assert result.server_version == "drop:1 file(s)"
        assert run.run_type == ConnectorRunType.TEST
        assert run.status == ConnectorRunStatus.SUCCEEDED
        cred = ubos_source.ubos_credential
        cred.refresh_from_db()
        assert cred.last_test_ok is True and cred.last_test_at is not None
        assert AuditEvent.objects.filter(
            action="test_connection", entity_id=ubos_source.id,
        ).exists()

    def test_run_test_connection_failure_is_recorded(self, ubos_source):
        cred = ubos_source.ubos_credential
        cred.drop_path = str(ubos_source.drop / "missing")
        cred.save()
        run, result = run_test_connection(ubos_source, actor="admin-user")
        assert result.ok is False
        assert run.status == ConnectorRunStatus.FAILED
        cred.refresh_from_db()
        assert cred.last_test_ok is False


# --- UBOS: forms endpoint + trigger ---------------------------------------------

class TestUbosForms:
    def _url(self, source):
        return f"/api/v1/dih/source-systems/{source.id}/forms/"

    def test_lists_drop_files_with_checksum_gate(self, ubos_source, geo_codes, django_user_model):
        _drop_file(ubos_source.drop, "good.json", [_household(geo_codes, "A")])
        bad = ubos_source.drop / "bad.json"
        bad.write_text("[]")
        bad.with_name("bad.json.sha256").write_text("0" * 64 + "\n")
        client, _ = _admin_client(django_user_model)
        resp = client.get(self._url(ubos_source))
        assert resp.status_code == 200, resp.content
        by_uid = {f["uid"]: f for f in resp.json()}
        assert by_uid["good.json"]["deployed"] is True
        assert by_uid["bad.json"]["deployed"] is False
        assert all(f["pinned"] is False for f in by_uid.values())

    def test_missing_credentials_400(self, db, django_user_model):
        src = SourceSystem.objects.create(
            code="UBOS-BULK", name="UBOS", kind=SourceSystemKind.UBOS,
        )
        client, _ = _admin_client(django_user_model)
        resp = client.get(self._url(src))
        assert resp.status_code == 400
        assert "credential" in resp.json()["detail"]


class TestUbosTrigger:
    def _url(self, source):
        return f"/api/v1/dih/source-systems/{source.id}/trigger-run/"

    def test_pull_lands_stages_and_pins_the_file(self, ubos_source, geo_codes, django_user_model):
        _drop_file(ubos_source.drop, "hh.json",
                   [_household(geo_codes, "Okot"), _household(geo_codes, "Auma")])
        client, user = _admin_client(django_user_model)
        resp = client.post(self._url(ubos_source), {"form_uid": "hh.json"}, format="json")
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["source_code"] == "UBOS-BULK"
        assert body["form_uid"] == "hh.json"
        assert body["landed"] == 2
        assert body["staged"] == 2
        assert body["quarantined"] == 0
        run = ConnectorRun.objects.get(id=body["run_id"])
        assert run.run_type == ConnectorRunType.IMPORT
        assert run.status == ConnectorRunStatus.SUCCEEDED
        assert RawLanding.objects.filter(connector_run=run).count() == 2
        stages = StageRecord.objects.filter(connector_run=run)
        assert stages.count() == 2
        lineage = stages.first().canonical_payload["_source_keys"]
        assert lineage["ubos_file"] == "hh.json"
        assert lineage["ubos_row"] in (1, 2)
        # Connector row is kind-neutral and pins the file for next time.
        row = Connector.objects.get(source_system=ubos_source, name="ubos-hh.json")
        assert row.config["form_uid"] == "hh.json"
        assert resolve_pinned_form_uid(ubos_source) == "hh.json"
        actions = set(AuditEvent.objects.filter(actor_id=user.username)
                      .values_list("action", flat=True))
        assert {"dih.connector.triggered", "dih.connector.trigger_succeeded"} <= actions

    def test_default_form_is_first_pullable_file(self, ubos_source, geo_codes, django_user_model):
        _drop_file(ubos_source.drop, "b.json", [_household(geo_codes, "B")])
        _drop_file(ubos_source.drop, "a.json", [_household(geo_codes, "A")])
        client, _ = _admin_client(django_user_model)
        resp = client.post(self._url(ubos_source), {}, format="json")
        assert resp.status_code == 200, resp.content
        assert resp.json()["form_uid"] == "a.json"  # sorted listing

    def test_re_pull_skips_already_landed_rows(self, ubos_source, geo_codes, django_user_model):
        _drop_file(ubos_source.drop, "hh.json", [_household(geo_codes, "Okot")])
        client, _ = _admin_client(django_user_model)
        first = client.post(self._url(ubos_source), {"form_uid": "hh.json"}, format="json")
        assert first.status_code == 200, first.content
        second = client.post(self._url(ubos_source), {"form_uid": "hh.json"}, format="json")
        assert second.status_code == 200, second.content
        assert second.json()["landed"] == 0
        assert second.json()["skipped_duplicate"] == 1
        assert RawLanding.objects.filter(
            connector_run__connector__source_system=ubos_source,
        ).count() == 1

    def test_malformed_row_is_quarantined_not_fatal(self, ubos_source, geo_codes, django_user_model):
        _drop_file(ubos_source.drop, "hh.json",
                   [_household(geo_codes, "Okot"), {"geographic": geo_codes}])  # no members
        client, _ = _admin_client(django_user_model)
        resp = client.post(self._url(ubos_source), {"form_uid": "hh.json"}, format="json")
        assert resp.status_code == 200, resp.content
        assert resp.json()["staged"] == 1
        assert resp.json()["quarantined"] == 1

    def test_checksum_mismatch_is_rejected(self, ubos_source, geo_codes, django_user_model):
        _drop_file(ubos_source.drop, "good.json", [_household(geo_codes, "G")])
        bad = ubos_source.drop / "bad.json"
        bad.write_text(json.dumps([_household(geo_codes, "X")]))
        bad.with_name("bad.json.sha256").write_text("0" * 64 + "\n")
        client, _ = _admin_client(django_user_model)
        resp = client.post(self._url(ubos_source), {"form_uid": "bad.json"}, format="json")
        assert resp.status_code == 400
        # Not in the deployed list, so the explicit pick is refused
        # before anything lands.
        assert "not in the deployed-forms list" in resp.json()["detail"]
        assert RawLanding.objects.count() == 0

    def test_only_unpullable_files_is_rejected(self, ubos_source, geo_codes, django_user_model):
        bad = ubos_source.drop / "bad.json"
        bad.write_text(json.dumps([_household(geo_codes, "X")]))
        bad.with_name("bad.json.sha256").write_text("0" * 64 + "\n")
        client, _ = _admin_client(django_user_model)
        resp = client.post(self._url(ubos_source), {}, format="json")
        assert resp.status_code == 400
        assert "no deployed forms" in resp.json()["detail"]
        assert RawLanding.objects.count() == 0

    def test_dry_run_counts_without_landing(self, ubos_source, geo_codes, django_user_model):
        _drop_file(ubos_source.drop, "hh.json",
                   [_household(geo_codes, "A"), _household(geo_codes, "B")])
        client, _ = _admin_client(django_user_model)
        resp = client.post(self._url(ubos_source), {"dry_run": True}, format="json")
        assert resp.status_code == 200, resp.content
        assert resp.json()["landed"] == 2
        assert RawLanding.objects.count() == 0
        run = ConnectorRun.objects.get(id=resp.json()["run_id"])
        assert run.run_type == ConnectorRunType.TEST

    def test_nira_source_cannot_be_pulled(self, nira_source, django_user_model):
        client, _ = _admin_client(django_user_model)
        resp = client.post(self._url(nira_source), {}, format="json")
        assert resp.status_code == 400
        assert "pulled on demand" in resp.json()["detail"]


class TestBeatVisitsUbos:
    def test_pending_ubos_landings_are_processed(self, ubos_source, geo_codes):
        from .services import land_payload, start_connector_run
        from .tasks import process_pending_kobo_landings_task

        row = Connector.objects.create(source_system=ubos_source, name="ubos-hh.json")
        run = start_connector_run(row, actor="test")
        land_payload(run, _household(geo_codes, "Beat"), source_reference="x#1")
        summary = process_pending_kobo_landings_task()
        assert summary["UBOS-BULK"]["staged"] == 1
        assert StageRecord.objects.filter(connector_run=run).count() == 1


# --- NIRA: credentials + test connection --------------------------------------

class TestNiraCredentials:
    def test_credentials_for_decrypts_secret(self, nira_source):
        assert credentials_for(nira_source) == {"webhook_secret": NIRA_SECRET}

    def test_run_test_connection_probes_mock_provider(self, nira_source, settings):
        settings.NIRA_PROVIDER = "mock"
        run, result = run_test_connection(nira_source, actor="admin-user")
        assert result.ok is True, result
        assert result.server_version == "nira:mock"
        assert run.run_type == ConnectorRunType.TEST
        cred = nira_source.nira_credential
        cred.refresh_from_db()
        assert cred.last_test_ok is True

    def test_live_provider_without_wiring_fails_honestly(self, nira_source, settings):
        settings.NIRA_PROVIDER = "live"
        _run, result = run_test_connection(nira_source, actor="admin-user")
        assert result.ok is False
        assert result.server_version == "nira:live"
        assert "NIRA-O-01" in result.error


# --- NIRA: vital-events webhook ---------------------------------------------------

class TestNiraWebhook:
    def test_unconfigured_source_503(self, db):
        resp = _post_event(APIClient(), {"event_type": "death"})
        assert resp.status_code == 503

    def test_missing_credential_503(self, db):
        SourceSystem.objects.create(
            code="NIRA-REVERSE", name="NIRA", kind=SourceSystemKind.NIRA,
        )
        resp = _post_event(APIClient(), {"event_type": "death"})
        assert resp.status_code == 503
        assert "credential" in resp.json()["detail"]

    def test_bad_signature_401_and_audited(self, nira_source):
        resp = _post_event(APIClient(), {"event_type": "death"}, secret="wrong")
        assert resp.status_code == 401
        assert AuditEvent.objects.filter(action="dih.nira.signature_rejected").exists()
        assert RawLanding.objects.count() == 0

    def test_missing_signature_401(self, nira_source):
        resp = _post_event(APIClient(), {"event_type": "death"}, secret=None)
        assert resp.status_code == 401

    def test_death_auto_commits_and_lands(self, nira_source, member_with_nin):
        member, nin = member_with_nin
        payload = {"event_type": "death", "nin": nin, "event_date": "2026-04-12",
                   "registration_ref": "NIRA-DTH-2026-1"}
        resp = _post_event(APIClient(), payload)
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["outcome"] == "committed"
        assert body["event_ref"] == "NIRA-DTH-2026-1"
        member.refresh_from_db()
        assert member.residency_status == "deceased"
        cr = ChangeRequest.objects.get(id=body["change_request_id"])
        assert cr.status == ChangeStatus.COMMITTED
        run = ConnectorRun.objects.get(id=body["run_id"])
        assert run.status == ConnectorRunStatus.SUCCEEDED
        assert run.records_landed == 1 and run.records_promoted == 1
        landing = RawLanding.objects.get(id=body["landing_id"])
        assert landing.payload == payload  # raw, untouched
        assert landing.source_reference == "NIRA-DTH-2026-1"
        assert AuditEvent.objects.filter(
            action="dih.nira.event_received", entity_id=landing.id,
        ).exists()

    def test_replay_is_idempotent(self, nira_source, member_with_nin):
        _member, nin = member_with_nin
        payload = {"event_type": "death", "nin": nin, "event_date": "2026-04-12",
                   "registration_ref": "NIRA-DTH-2026-2", "event_id": "EVT-2"}
        first = _post_event(APIClient(), payload)
        assert first.status_code == 200
        second = _post_event(APIClient(), payload)
        assert second.status_code == 200
        assert second.json()["outcome"] == "duplicate"
        assert second.json()["event_ref"] == "EVT-2"  # event_id wins
        assert RawLanding.objects.filter(source_reference="EVT-2").count() == 1
        assert ChangeRequest.objects.count() == 1

    def test_already_deceased_is_noop(self, nira_source, member_with_nin):
        member, nin = member_with_nin
        member.residency_status = "deceased"
        member.save(update_fields=["residency_status"])
        resp = _post_event(APIClient(), {
            "event_type": "death", "nin": nin, "event_date": "2026-04-12",
            "registration_ref": "NIRA-DTH-2026-3",
        })
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "noop"
        assert ChangeRequest.objects.count() == 0

    def test_birth_is_landed_and_quarantined(self, nira_source):
        resp = _post_event(APIClient(), {
            "event_type": "birth", "nin": "CF9999000011112222",
            "event_date": "2026-05-01", "registration_ref": "NIRA-BTH-1",
        })
        assert resp.status_code == 200, resp.content
        assert resp.json()["outcome"] == "quarantined"
        q = Quarantine.objects.get()
        assert q.reason == "nira_unroutable"
        assert q.raw_landing_id == resp.json()["landing_id"]
        run = ConnectorRun.objects.get(id=resp.json()["run_id"])
        assert run.status == ConnectorRunStatus.QUARANTINED
        assert run.records_quarantined == 1

    def test_unknown_nin_is_quarantined(self, nira_source):
        resp = _post_event(APIClient(), {
            "event_type": "death", "nin": "CM0000000000XX",
            "event_date": "2026-04-12", "registration_ref": "NIRA-DTH-9",
        })
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "quarantined"
        assert Quarantine.objects.get().reason == "nira_unroutable"

    def test_malformed_event_400_but_landed(self, nira_source):
        resp = _post_event(APIClient(), {
            "event_type": "marriage", "nin": "CM0000000000AB",
            "event_date": "2026-04-12", "registration_ref": "NIRA-MRG-1",
        })
        assert resp.status_code == 400
        assert resp.json()["outcome"] == "quarantined"
        assert Quarantine.objects.get().reason == "nira_malformed"
        assert RawLanding.objects.filter(source_reference="NIRA-MRG-1").exists()

    def test_missing_event_reference_400(self, nira_source):
        resp = _post_event(APIClient(), {"event_type": "death", "nin": "CM0000000000AB",
                                         "event_date": "2026-04-12"})
        assert resp.status_code == 400
        assert "idempotency" in resp.json()["detail"]

    def test_no_dpa_503(self, db, member_with_nin):
        src = SourceSystem.objects.create(
            code="NIRA-REVERSE", name="NIRA", kind=SourceSystemKind.NIRA,
        )
        NiraCredential.objects.create(
            source_system=src, webhook_secret_encrypted=NIRA_SECRET,
        )
        _member, nin = member_with_nin
        resp = _post_event(APIClient(), {
            "event_type": "death", "nin": nin, "event_date": "2026-04-12",
            "registration_ref": "NIRA-DTH-NODPA",
        })
        assert resp.status_code == 503
        assert "DPA" in resp.json()["detail"]
        assert RawLanding.objects.count() == 0
