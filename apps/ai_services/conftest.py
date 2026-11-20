import pytest

# The 7-level geography ladder fixture is owned by the DDUP tests; reuse it
# rather than keep a second copy that could drift from the real ladder.
from apps.ddup.tests import geo  # noqa: F401


@pytest.fixture
def enabled(settings):
    """The master switch on. It defaults to off everywhere (ADR-0045 D4)."""
    settings.AI_SERVICES_ENABLED = True
