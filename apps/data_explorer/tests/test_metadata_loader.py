from __future__ import annotations

import pytest

from apps.data_explorer.models import Variable, VariableStatus
from apps.data_explorer.seeds.privacy_class_defaults import (
    DATASET_VARIABLE_DEFAULTS,
)

pytestmark = pytest.mark.django_db


def test_refresh_loads_live_matview_variables():
    from apps.data_explorer import metadata_loader

    result = metadata_loader.refresh(activate=True)
    assert result["skipped"] is False

    for dataset_code, variable_rows in DATASET_VARIABLE_DEFAULTS.items():
        expected = sorted(row["code"] for row in variable_rows)
        got = list(
            Variable.objects.filter(
                dataset__code=dataset_code,
                status=VariableStatus.ACTIVE,
            )
            .order_by("code")
            .values_list("code", flat=True)
        )
        assert got == expected
