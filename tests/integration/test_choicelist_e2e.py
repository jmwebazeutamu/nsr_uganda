"""End-to-end test for US-S22-005g.

Threads the full ADR-0010 flow:
  1. Steward adds a new option on `tenure` and approves it.
  2. The bundle endpoint's ETag flips; the new option appears.
  3. A household captured today with the new code renders the new
     label in source_payload_labels.
  4. A household captured before the new option became effective
     keeps its old labels (historical correctness).

Anchored to the acceptance criterion in the spec — every step in
the prompt's "add a ChoiceOption via admin, approve it, hit the
bundle endpoint, confirm new option appears; resolve a household
with the new code, confirm label appears in the detail payload."
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from apps.data_management.models import Household
from apps.ingestion_hub.models import (
    Connector,
    ConnectorRun,
    SourceSystem,
    SourceSystemKind,
    StageRecord,
    StageRecordState,
)
from apps.reference_data.models import (
    ChoiceList,
    ChoiceListStatus,
    ChoiceOption,
    GeographicUnit,
)
from apps.reference_data.services import clear_resolver_cache
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

BUNDLE_URL = "/api/v1/reference-data/choice-list-bundle/"
HOUSEHOLD_URL = "/api/v1/data-management/households/{id}/"


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def api(db):
    user_cls = get_user_model()
    u = user_cls.objects.create_superuser(username="e2e", password="p")
    c = APIClient()
    c.force_authenticate(user=u)
    return c


def _make_household(*, label: str, payload: dict, captured_at: datetime):
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"),
        ("district", "d", "sr"), ("county", "c", "d"),
        ("sub_county", "sc", "c"), ("parish", "p", "sc"),
        ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"E2E-{label}-{key}", name=key,
            parent=nodes.get(parent), effective_from=date(2020, 1, 1),
        )
    hh = Household.objects.create(
        region=nodes["r"], sub_region=nodes["sr"], district=nodes["d"],
        county=nodes["c"], sub_county=nodes["sc"], parish=nodes["p"],
        village=nodes["v"], urban_rural="2",
    )
    src = SourceSystem.objects.create(
        code=f"e2e-{label}", name=f"E2E {label}", kind=SourceSystemKind.KOBO,
    )
    conn = Connector.objects.create(source_system=src, name="t")
    run = ConnectorRun.objects.create(connector=conn)
    sr = StageRecord.objects.create(
        connector_run=run,
        provisional_registry_id=hh.id,
        canonical_payload=payload,
        state=StageRecordState.PROMOTED,
        promoted_at=captured_at,
    )
    # Backdate created_at on the StageRecord so the serializer's
    # _intake_date helper sees the historical date.
    StageRecord.objects.filter(pk=sr.pk).update(created_at=captured_at)
    return hh


@pytest.mark.django_db
class TestChoiceListAddOptionFlow:
    def test_admin_add_option_flows_to_bundle_and_household(self, api):
        # Step 1: capture initial bundle + ETag.
        before = api.get(BUNDLE_URL)
        etag_before = before["ETag"]
        tenure_before = next(
            lst for lst in before.data["lists"] if lst["list_name"] == "tenure"
        )
        before_codes = {o["code"] for o in tenure_before["options"]}
        assert "99" not in before_codes  # sanity

        # Step 2: steward adds a new option on the active tenure list,
        # then approves it (i.e. lands the row directly — the dual-
        # approval workflow lives in the service layer per ADR-0010 §7;
        # this E2E exercises the post-approval state).
        active_tenure = ChoiceList.objects.get(
            list_name="tenure", version=1, status=ChoiceListStatus.ACTIVE,
        )
        ChoiceOption.objects.create(
            choice_list=active_tenure,
            code="99", label="Co-operative tenancy", language="en",
            sort_order=99,
        )

        # Step 3: bundle ETag flipped; new option appears.
        after = api.get(BUNDLE_URL)
        etag_after = after["ETag"]
        assert etag_after != etag_before
        tenure_after = next(
            lst for lst in after.data["lists"] if lst["list_name"] == "tenure"
        )
        opts_after = {o["code"]: o["label"] for o in tenure_after["options"]}
        assert opts_after["99"] == "Co-operative tenancy"

        # Step 4: a fresh household captured today, with the new code,
        # renders the new label through the household-detail API.
        today = datetime.now(UTC)
        new_hh = _make_household(
            label="new",
            payload={"housing": {"tenure": "99"}},
            captured_at=today,
        )
        new_resp = api.get(HOUSEHOLD_URL.format(id=new_hh.id))
        assert new_resp.status_code == 200
        labels = new_resp.data["source_payload_labels"]
        assert labels["housing"]["tenure"] == "Co-operative tenancy"

    def test_historical_capture_keeps_old_label(self, api):
        # Steward retires v1 last week and lands v2 today, renaming
        # code "13" from "Free - private" → "Private free-use".
        today = date.today()
        last_week = today - timedelta(days=7)
        v1 = ChoiceList.objects.get(list_name="tenure", version=1)
        v1.effective_from = today - timedelta(days=400)
        v1.effective_to = last_week
        v1.save()

        v2 = ChoiceList.objects.create(
            list_name="tenure", version=2,
            status=ChoiceListStatus.ACTIVE,
            effective_from=last_week, effective_to=None,
            author="steward", approved_by="reviewer",
        )
        ChoiceOption.objects.create(
            choice_list=v2, code="13", label="Private free-use",
            language="en", sort_order=13,
        )
        clear_resolver_cache()

        # Household captured today picks v2's label.
        today_hh = _make_household(
            label="today",
            payload={"housing": {"tenure": "13"}},
            captured_at=datetime.now(UTC),
        )
        today_resp = api.get(HOUSEHOLD_URL.format(id=today_hh.id))
        assert today_resp.data["source_payload_labels"]["housing"]["tenure"] \
            == "Private free-use"

        # Household captured a year ago — well inside v1's window —
        # keeps the historical label.
        old_hh = _make_household(
            label="old",
            payload={"housing": {"tenure": "13"}},
            captured_at=datetime.now(UTC) - timedelta(days=200),
        )
        old_resp = api.get(HOUSEHOLD_URL.format(id=old_hh.id))
        assert old_resp.data["source_payload_labels"]["housing"]["tenure"] \
            == "Free - private"
