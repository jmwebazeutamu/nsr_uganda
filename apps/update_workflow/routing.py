"""Default routing matrix per SAD §4.4.4.

Open item UPD-O-01 will finalise this; the defaults below are what the
SAD proposes. Encoding the matrix here keeps the rules data-shaped so
the eventual REF-DATA-managed table replaces this module 1:1.
"""

from __future__ import annotations

from datetime import timedelta

from .models import ChangeType

# (change_type, pmt_relevant) -> (required_role, sla_hours)
DEFAULT_MATRIX: dict[tuple[str, bool], tuple[str, int]] = {
    (ChangeType.CORRECTION,      False): ("supervisor",       72),
    (ChangeType.CORRECTION,      True):  ("cdo",              48),
    (ChangeType.ADDITION,        False): ("parish_chief",     72),
    (ChangeType.ADDITION,        True):  ("cdo",              48),
    (ChangeType.REMOVAL,         False): ("cdo",              48),
    (ChangeType.REMOVAL,         True):  ("district_m_and_e", 48),
    # Vital events and programme-state events auto-commit per SAD §4.4.4;
    # required_role kept for audit/lineage. The 1% sample policy applies
    # at the commit step.
    (ChangeType.VITAL_EVENT,     False): ("nira_auto",         0),
    (ChangeType.VITAL_EVENT,     True):  ("nira_auto",         0),
    (ChangeType.PROGRAMME_STATE, False): ("programme_auto",    0),
    (ChangeType.PROGRAMME_STATE, True):  ("programme_auto",    0),
    (ChangeType.RECERTIFICATION, False): ("district_m_and_e", 168),
    (ChangeType.RECERTIFICATION, True):  ("district_m_and_e", 168),
}


def route(change_type: str, *, pmt_relevant: bool) -> tuple[str, timedelta]:
    """Return (required_role, sla_window) for a change_type+pmt_relevant pair."""
    role, hours = DEFAULT_MATRIX[(change_type, pmt_relevant)]
    return role, timedelta(hours=hours)
