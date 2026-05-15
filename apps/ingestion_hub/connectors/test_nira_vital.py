"""NIRA reverse-feed (vital events) connector tests.

The mapper is pure; the driver is side-effecting and routes through
the UPD vital-event auto-commit pipeline (S3-003).
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_management.models import Household, Member
from apps.ingestion_hub.connectors.nira_vital import (
    NiraVitalEventError,
    nira_vital_to_canonical,
    process_nira_vital_event,
)
from apps.reference_data.models import GeographicUnit
from apps.security.hashing import nin_hash as _h
from apps.security.models import AuditEvent
from apps.update_workflow.models import ChangeStatus

# --- Pure mapping ----------------------------------------------------------


class TestVitalMapping:
    def test_death_payload_normalises(self):
        raw = {
            "event_type": "DEATH",
            "nin": "  cm1234567890ab  ",
            "event_date": "2026-04-12",
            "registration_ref": "NIRA-DTH-2026-00012345",
        }
        out = nira_vital_to_canonical(raw)
        # Case + whitespace normalisation.
        assert out["event_type"] == "death"
        assert out["nin"] == "CM1234567890AB"
        assert out["registration_ref"] == "NIRA-DTH-2026-00012345"

    def test_birth_payload_normalises(self):
        raw = {
            "event_type": "birth",
            "nin": "CF9999000011112222",
            "event_date": "2026-05-01",
            "demographics": {"surname": "OPIYO", "first_name": "JOY"},
        }
        out = nira_vital_to_canonical(raw)
        assert out["event_type"] == "birth"
        assert out["demographics"]["surname"] == "OPIYO"

    def test_unknown_event_type_raises(self):
        with pytest.raises(ValueError, match="unknown NIRA event_type"):
            nira_vital_to_canonical(
                {"event_type": "marriage", "nin": "CM" + "0" * 12,
                 "event_date": "2026-01-01"},
            )

    def test_missing_nin_raises(self):
        with pytest.raises(KeyError):
            nira_vital_to_canonical(
                {"event_type": "death", "event_date": "2026-01-01"},
            )


# --- End-to-end driver -----------------------------------------------------


@pytest.fixture
def member_with_nin(db):
    """One household, one member with a known NIN hash, residing."""
    nodes = {}
    parent = None
    for level in ("region", "sub_region", "district", "county",
                  "sub_county", "parish", "village"):
        n = GeographicUnit.objects.create(
            level=level, code=f"VIT-{level}", name=level,
            parent=parent, effective_from=date(2026, 1, 1),
        )
        nodes[level] = n
        parent = n
    hh = Household.objects.create(
        region=nodes["region"], sub_region=nodes["sub_region"],
        district=nodes["district"], county=nodes["county"],
        sub_county=nodes["sub_county"], parish=nodes["parish"],
        village=nodes["village"], urban_rural="rural",
    )
    nin = "CM1234567890AB"
    m = Member.objects.create(
        household=hh, line_number=1, surname="Okot", first_name="James",
        sex="M", nin_hash=_h(nin), nin_value=nin.encode("ascii"),
    )
    return m, nin


class TestDeathPath:
    def test_death_flips_residency_status(self, member_with_nin):
        m, nin = member_with_nin
        raw = {"event_type": "death", "nin": nin,
               "event_date": "2026-04-12",
               "registration_ref": "NIRA-DTH-1"}
        cr = process_nira_vital_event(raw)
        m.refresh_from_db()
        assert m.residency_status == "deceased"
        # Auto-commit ran: CR is COMMITTED.
        assert cr.status == ChangeStatus.COMMITTED
        # Audit chain carries a commit emitted by NIRA reverse-feed.
        ev = AuditEvent.objects.filter(
            entity_type="change_request", entity_id=cr.id, action="commit",
        ).first()
        assert ev is not None

    def test_unknown_nin_raises(self, db):
        raw = {"event_type": "death", "nin": "CM0000000000XX",
               "event_date": "2026-04-12"}
        with pytest.raises(NiraVitalEventError, match="does not match"):
            process_nira_vital_event(raw)

    def test_already_deceased_is_no_op(self, member_with_nin):
        m, nin = member_with_nin
        m.residency_status = "deceased"
        m.save(update_fields=["residency_status"])
        raw = {"event_type": "death", "nin": nin,
               "event_date": "2026-04-12"}
        result = process_nira_vital_event(raw)
        assert result is None  # explicit no-op return


class TestBirthPath:
    def test_birth_raises_pending_household_context(self, db):
        raw = {"event_type": "birth",
               "nin": "CF9999000011112222",
               "event_date": "2026-05-01",
               "registration_ref": "NIRA-BTH-1"}
        with pytest.raises(NiraVitalEventError, match="not yet auto-promoted"):
            process_nira_vital_event(raw)
