"""DIH tests run against an approved DDUP model, because DIH does.

Promotion calls the shared tier-1 matcher, which reads the ACTIVE
`DdupModelVersion` — there are no hardcoded defaults behind it any
more, so a database with no approved model raises rather than guessing
how to match people. Production always has one (seeded by script); the
test database does not, which made sixteen DIH tests fail on
`DdupModelVersion.DoesNotExist` for a reason that had nothing to do
with what they were testing.

The fixture yields to a test that makes its own: it only fills the gap
when no ACTIVE version exists.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _active_ddup_model(db):
    from apps.ddup.models import DdupModelVersion, ModelStatus
    from apps.ddup.tests import model_config

    if DdupModelVersion.objects.filter(status=ModelStatus.ACTIVE).exists():
        return
    DdupModelVersion.objects.create(
        version=1,
        description="tier1 NIN deterministic (test default)",
        config=model_config(),
        author="tests",
        status=ModelStatus.ACTIVE,
    )
