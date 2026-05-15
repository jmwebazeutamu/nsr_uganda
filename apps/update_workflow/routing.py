"""Routing matrix per SAD §4.4.4.

UPD-O-01 closure: the matrix is now operations-editable through
apps.update_workflow.models.UpdRoutingRule. The DEFAULT_MATRIX below
is the fallback used when no active row exists for a
(change_type, pmt_relevant) tuple — deleting every row cannot break
the system, the SAD defaults take over.

The fallback also serves as the seed source for the data migration
that populates the table on first deploy (migration 0003).
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
    """Return (required_role, sla_window) for a change_type+pmt_relevant pair.

    Looks up the active UpdRoutingRule first; falls back to
    DEFAULT_MATRIX when no row exists. The DB read is a single
    indexed query so the hot path stays cheap.
    """
    from .models import UpdRoutingRule
    rule = (
        UpdRoutingRule.objects
        .filter(change_type=change_type, pmt_relevant=pmt_relevant, is_active=True)
        .only("required_role", "sla_hours")
        .first()
    )
    if rule is not None:
        return rule.required_role, timedelta(hours=rule.sla_hours)
    role, hours = DEFAULT_MATRIX[(change_type, pmt_relevant)]
    return role, timedelta(hours=hours)
