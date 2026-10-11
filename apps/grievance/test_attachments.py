"""A document filed against a grievance.

The complaint that arrives with a photograph of the posted beneficiary
list is the evidence the case turns on, and a grievance could hold a
note and a task and nothing else. STAAC's intake payload carries an
`attachments` array, so a case transferred with its evidence would have
arrived without it and nobody would have been told.
"""

from __future__ import annotations

import hashlib
from datetime import date

import pytest

from apps.grievance.models import (
    Category,
    Grievance,
    GrievanceAttachment,
    GrievanceStatus,
)
from apps.grievance.services import (
    GrievanceError,
    attach_document,
    open_grievance,
)
from apps.reference_data.models import GeographicUnit
from apps.security.models import AuditEvent
from apps.update_workflow.evidence_storage import (
    MAX_FILES,
    MAX_TOTAL_BYTES,
    get_evidence_storage,
)

pytestmark = pytest.mark.django_db

PDF = "application/pdf"


@pytest.fixture
def parish(db):
    parent = None
    for level, code in [
        ("region", "R-A"), ("sub_region", "SR-A"), ("district", "D-A"),
        ("county", "C-A"), ("sub_county", "SC-A"), ("parish", "P-A"),
    ]:
        parent = GeographicUnit.objects.create(
            level=level, code=code, name=code, parent=parent,
            effective_from=date(2026, 1, 1),
        )
    return parent


@pytest.fixture
def grievance(parish):
    return open_grievance(
        category=Category.EXCLUSION_ERROR, description="omitted from the list",
        geographic_code="P-A", actor="t",
    )


def test_the_bytes_go_to_the_store_and_the_row_holds_the_digest(grievance):
    """The row is the index; the store holds the file. A row pointing at
    bytes that were never stored is a case whose evidence cannot be
    opened."""
    body = b"%PDF-1.4 the posted list"
    row = attach_document(
        grievance, filename="list.pdf", content_type=PDF, body=body,
        actor="officer",
    )
    assert row.sha256 == hashlib.sha256(body).hexdigest()
    assert row.size_bytes == len(body)
    assert get_evidence_storage().get(row.sha256) == body
    assert list(grievance.attachments.all()) == [row]


def test_the_same_file_twice_is_one_attachment(grievance):
    """What makes a transfer safe to retry. Counting it again would make
    one photograph look like two pieces of evidence."""
    body = b"%PDF-1.4 the posted list"
    first = attach_document(
        grievance, filename="list.pdf", content_type=PDF, body=body,
        actor="officer",
    )
    again = attach_document(
        grievance, filename="list-resent.pdf", content_type=PDF, body=body,
        actor="officer",
    )
    assert again.pk == first.pk
    assert grievance.attachments.count() == 1


def test_the_same_file_on_another_case_is_its_own_attachment(grievance, parish):
    """Uniqueness is per case. Two complainants photographing the same
    posted list have two pieces of evidence, stored once."""
    other = open_grievance(
        category=Category.EXCLUSION_ERROR, description="also omitted",
        geographic_code="P-A", actor="t",
    )
    body = b"%PDF-1.4 the posted list"
    a = attach_document(
        grievance, filename="list.pdf", content_type=PDF, body=body,
        actor="officer",
    )
    b = attach_document(
        other, filename="list.pdf", content_type=PDF, body=body, actor="officer",
    )
    assert a.pk != b.pk
    assert a.sha256 == b.sha256


def test_an_unaccepted_type_is_refused(grievance):
    with pytest.raises(GrievanceError, match="not an accepted document type"):
        attach_document(
            grievance, filename="payload.exe",
            content_type="application/x-msdownload", body=b"MZ",
            actor="officer",
        )


def test_an_empty_file_is_refused(grievance):
    with pytest.raises(GrievanceError, match="is empty"):
        attach_document(
            grievance, filename="blank.pdf", content_type=PDF, body=b"",
            actor="officer",
        )


def test_the_per_file_cap_holds(grievance):
    from apps.update_workflow.evidence_storage import MAX_FILE_BYTES

    with pytest.raises(GrievanceError, match="the limit is"):
        attach_document(
            grievance, filename="big.pdf", content_type=PDF,
            body=b"x" * (MAX_FILE_BYTES + 1), actor="officer",
        )


def test_the_count_is_capped_over_the_case_not_the_call(grievance):
    """Three attachments in three calls must hit the same wall as three
    in one, or the cap is only a shape of request."""
    for n in range(MAX_FILES):
        attach_document(
            grievance, filename=f"{n}.pdf", content_type=PDF,
            body=f"%PDF-1.4 {n}".encode(), actor="officer",
        )
    with pytest.raises(GrievanceError, match="which is the limit"):
        attach_document(
            grievance, filename="one-more.pdf", content_type=PDF,
            body=b"%PDF-1.4 extra", actor="officer",
        )


def test_the_total_is_capped_over_the_case(parish, monkeypatch):
    """The per-file cap times the file count is EXACTLY the total today
    (3 x 5 MB = 15 MB), so the total guard cannot bite as the constants
    stand — three maximum files fit precisely. It is here so that
    raising MAX_FILES does not quietly remove the limit on what one
    case can hold, which is why it is tested by lowering the total
    rather than by uploading 15 MB."""
    from apps.update_workflow import evidence_storage

    assert (
        evidence_storage.MAX_FILE_BYTES * evidence_storage.MAX_FILES
        == evidence_storage.MAX_TOTAL_BYTES
    ), "the constants moved — this test's premise needs rereading"

    monkeypatch.setattr(evidence_storage, "MAX_TOTAL_BYTES", 32)
    g = open_grievance(
        category=Category.EXCLUSION_ERROR, description="omitted",
        geographic_code="P-A", actor="t",
    )
    attach_document(
        g, filename="a.pdf", content_type=PDF, body=b"%PDF-1.4" + b"a" * 12,
        actor="officer",
    )
    with pytest.raises(GrievanceError, match="over the"):
        attach_document(
            g, filename="b.pdf", content_type=PDF, body=b"%PDF-1.4" + b"b" * 12,
            actor="officer",
        )
    assert g.attachments.count() == 1


def test_a_closed_case_takes_no_attachment(grievance):
    """The closing narrative is the last word on what happened.
    Evidence arriving after it is a new case — the rule
    `_require_open_for_writing` states, and this is the fourth writer
    its docstring predicted."""
    Grievance.objects.filter(pk=grievance.pk).update(
        status=GrievanceStatus.CLOSED,
    )
    grievance.refresh_from_db()
    with pytest.raises(GrievanceError):
        attach_document(
            grievance, filename="late.pdf", content_type=PDF,
            body=b"%PDF-1.4 late", actor="officer",
        )


def test_attaching_is_audited_by_digest_not_by_bytes(grievance):
    """Personal data moved, so an AuditEvent says so. The digest
    identifies the document in the chain without putting a
    complainant's photograph into it."""
    body = b"%PDF-1.4 the posted list"
    row = attach_document(
        grievance, filename="list.pdf", content_type=PDF, body=body,
        actor="officer",
    )
    event = AuditEvent.objects.filter(
        entity_type="grievance.attachment", entity_id=row.id,
    ).first()
    assert event is not None
    assert event.actor_id == "officer"
    assert event.field_changes["sha256"] == row.sha256
    assert event.field_changes["grievance_id"] == grievance.id
    assert "the posted list" not in str(event.field_changes)


def test_the_senders_own_reference_is_kept(grievance):
    """So a partner asking "did you get attachment 7 of C-26-057528-8"
    can be answered."""
    row = attach_document(
        grievance, filename="list.pdf", content_type=PDF,
        body=b"%PDF-1.4 x", actor="staac-bridge",
        external_reference="STAAC-ATT-7",
    )
    assert row.external_reference == "STAAC-ATT-7"


def test_an_actor_is_required(grievance):
    with pytest.raises(GrievanceError, match="actor required"):
        attach_document(
            grievance, filename="list.pdf", content_type=PDF,
            body=b"%PDF-1.4 x", actor="",
        )


def test_nothing_is_written_when_the_file_is_refused(grievance):
    with pytest.raises(GrievanceError):
        attach_document(
            grievance, filename="payload.exe",
            content_type="application/x-msdownload", body=b"MZ",
            actor="officer",
        )
    assert not GrievanceAttachment.objects.filter(grievance=grievance).exists()


# ── through the API, which is how the console sends one ────────────────

class TestTheIntakeApi:
    """The console's New-grievance form posts the case and its documents
    together, so the API has to take them together."""

    @pytest.fixture
    def client(self, db, django_user_model):
        from rest_framework.test import APIClient

        user = django_user_model.objects.create_user(
            username="grm-op", password="p", is_superuser=True, is_staff=True,
        )
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    @staticmethod
    def _doc(body=b"%PDF-1.4 photo of the posted list", name="list.pdf",
             content_type=PDF):
        import base64

        return {
            "filename": name,
            "content_type": content_type,
            "data_base64": base64.b64encode(body).decode("ascii"),
        }

    def test_a_case_arrives_with_its_evidence(self, client, parish):
        body = b"%PDF-1.4 photo of the posted list"
        r = client.post("/api/v1/grm/grievances/", data={
            "category": Category.EXCLUSION_ERROR,
            "description": "Omitted from the posted list",
            "documents": [self._doc(body)],
        }, format="json")
        assert r.status_code == 201, r.data
        assert len(r.data["attachments"]) == 1
        row = r.data["attachments"][0]
        assert row["filename"] == "list.pdf"
        assert row["sha256"] == hashlib.sha256(body).hexdigest()
        # The bytes are not on the case. They are in the store, and
        # serving them back is a separate, audited read.
        assert "data_base64" not in row
        assert "body" not in row

    def test_a_refused_document_refuses_the_case(self, client, parish):
        """Each of open_grievance and attach_document is atomic on its
        own, which is not the same thing. Without one transaction over
        both, a refused second document leaves a grievance already
        created and the operator who retries files the same complaint
        twice."""
        r = client.post("/api/v1/grm/grievances/", data={
            "category": Category.EXCLUSION_ERROR,
            "description": "Omitted from the posted list",
            "documents": [
                self._doc(),
                self._doc(b"MZ", "payload.exe", "application/x-msdownload"),
            ],
        }, format="json")
        assert r.status_code == 400
        assert "not an accepted document type" in str(r.data)
        assert not Grievance.objects.exists()
        assert not GrievanceAttachment.objects.exists()

    def test_bad_base64_is_refused_as_bad_base64(self, client, parish):
        r = client.post("/api/v1/grm/grievances/", data={
            "category": Category.OTHER,
            "description": "x",
            "documents": [{
                "filename": "list.pdf", "content_type": PDF,
                "data_base64": "not base64 at all!!",
            }],
        }, format="json")
        assert r.status_code == 400
        assert "base64" in str(r.data)
        assert not Grievance.objects.exists()

    def test_a_case_with_no_documents_still_opens(self, client, parish):
        r = client.post("/api/v1/grm/grievances/", data={
            "category": Category.OTHER, "description": "x",
        }, format="json")
        assert r.status_code == 201
        assert r.data["attachments"] == []

    def test_the_reporters_sex_and_age_round_trip(self, client, parish):
        r = client.post("/api/v1/grm/grievances/", data={
            "category": Category.EXCLUSION_ERROR,
            "description": "Omitted from the posted list",
            "reporter_name": "Sarah Nakato",
            "reporter_gender": "2",
            "reporter_age_years": 64,
        }, format="json")
        assert r.status_code == 201, r.data
        assert r.data["reporter_gender"] == "2"
        assert r.data["reporter_age_years"] == 64

    def test_a_gender_outside_the_sex_list_is_refused_with_a_reason(
        self, client, parish,
    ):
        """And in words an operator can act on, not a 500."""
        r = client.post("/api/v1/grm/grievances/", data={
            "category": Category.OTHER, "description": "x",
            "reporter_gender": "female",
        }, format="json")
        assert r.status_code == 400
        assert "not a code on the 'sex' list" in str(r.data)
