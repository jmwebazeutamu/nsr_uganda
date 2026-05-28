"""Shared DATA-EXP fixtures, importable from any tests/ subdir.

Living outside the conftest.py file so it can be imported under any
pytest rootdir without triggering ImportPathMismatchError (the same
conftest.py can't load under two paths). Each tests/ subdir's
conftest.py imports `*` from here.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group


@pytest.fixture
def privacy_classes(db):
    """Upsert the four canonical PrivacyClass rows.

    Caps per ADR-0023 D6 / OPEN-3 defaults. Tests that need different
    caps mutate the row in-place (it's just a dict on the model).
    """
    from apps.data_explorer.models import PrivacyClass

    rows = {}
    for code, label, k_floor, user_cap, org_cap, blocks in [
        ("public",    "Public",    0,  None,  None, False),
        ("internal",  "Internal",  5,  100,  5000, False),
        ("personal",  "Personal", 10,   25,   500, False),
        ("sensitive", "Sensitive", 0,    0,     0, True),
    ]:
        row, _ = PrivacyClass.objects.update_or_create(
            code=code,
            defaults={
                "label": label,
                "k_floor": k_floor,
                "daily_user_cap": user_cap,
                "daily_org_cap": org_cap,
                "blocks_aggregate": blocks,
            },
        )
        rows[code] = row
    return rows


@pytest.fixture
def refresh_cadences(db):
    from apps.data_explorer.models import RefreshCadence

    rows = {}
    for code, label, interval in [
        ("daily", "Daily", 24 * 3600),
        ("weekly", "Weekly", 7 * 24 * 3600),
    ]:
        row, _ = RefreshCadence.objects.update_or_create(
            code=code,
            defaults={"label": label, "interval_seconds": interval},
        )
        rows[code] = row
    return rows


@pytest.fixture
def dataset(privacy_classes, refresh_cadences):
    from apps.data_explorer.models import Dataset

    return Dataset.objects.create(
        code="household_by_subcounty_pmt",
        label="Household × PMT by sub-county",
        description="Aggregate of Household joined to PMTResult.",
        source_matview="mv_explorer_household_by_subcounty_pmt",
        privacy_class=privacy_classes["internal"],
        refresh_cadence=refresh_cadences["daily"],
        geographic_floor="sub_county",
    )


@pytest.fixture
def variable_internal(dataset, privacy_classes):
    from apps.data_explorer.models import Variable, VariableStatus

    return Variable.objects.create(
        dataset=dataset,
        code="household.dwelling_type",
        label="Dwelling type",
        source_model="data_management.Dwelling",
        source_field="dwelling_type",
        data_type="select",
        privacy_class=privacy_classes["internal"],
        status=VariableStatus.ACTIVE,
    )


@pytest.fixture
def variable_personal(dataset, privacy_classes):
    from apps.data_explorer.models import Variable, VariableStatus

    return Variable.objects.create(
        dataset=dataset,
        code="member.chronic_illness_present",
        label="Has chronic illness",
        source_model="data_management.Health",
        source_field="chronic_illness_present",
        data_type="boolean",
        privacy_class=privacy_classes["personal"],
        status=VariableStatus.ACTIVE,
    )


@pytest.fixture
def variable_sensitive(dataset, privacy_classes):
    from apps.data_explorer.models import Variable, VariableStatus

    return Variable.objects.create(
        dataset=dataset,
        code="member.hiv_status",
        label="HIV status",
        source_model="data_management.Health",
        source_field="hiv_status",
        data_type="select",
        privacy_class=privacy_classes["sensitive"],
        status=VariableStatus.ACTIVE,
    )


@pytest.fixture
def explorer_user(db):
    """A user with EXPLORER role. Mirrors how the Admin Console tests
    materialise a group — Keycloak realm role lands as a Django Group
    under the local mapping (ADR-0006)."""
    user_cls = get_user_model()
    u = user_cls.objects.create_user(
        username="explorer-test", password="p", email="explorer@example.com",
    )
    grp, _ = Group.objects.get_or_create(name="EXPLORER")
    u.groups.add(grp)
    return u


@pytest.fixture
def non_explorer_user(db):
    user_cls = get_user_model()
    return user_cls.objects.create_user(
        username="random-test", password="p", email="random@example.com",
    )
