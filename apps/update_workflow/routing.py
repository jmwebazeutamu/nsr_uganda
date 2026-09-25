"""Routing matrix per SAD §4.4.4.

UPD-O-01 closure: the matrix is operations-editable through
apps.update_workflow.models.UpdRoutingRule, and that table is now the
only source. `route()` raises when a (change_type, pmt_relevant) pair
has no active row rather than falling back, so routing policy cannot be
changed by a code release.

DEFAULT_MATRIX is kept as the SEED SOURCE and as the record of what
each combination was set to originally — migrations 0004 and 0006 read
it. It is not consulted at runtime. A change here changes nothing until
a migration or an operator puts it in the table.
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
    # US-S22-003 — operator-named change_type routing per the Open-CR
    # modal spec. Roles use the existing vocabulary so existing
    # dashboards / sweeps keep working; the spec's display labels
    # ("CDO (parish)" etc.) are surfaced separately by route_label().
    (ChangeType.LIFE_EVENT,      False): ("cdo",              72),
    (ChangeType.LIFE_EVENT,      True):  ("me_officer",       48),
    (ChangeType.VERIFICATION,    False): ("cdo",              72),
    (ChangeType.VERIFICATION,    True):  ("me_officer",       48),
    (ChangeType.ADDRESS_MOVE,    False): ("cdo_receiving",    96),
    (ChangeType.ADDRESS_MOVE,    True):  ("district_m_and_e", 48),
    (ChangeType.ROSTER_CHANGE,   False): ("cdo",              72),
    (ChangeType.ROSTER_CHANGE,   True):  ("district_m_and_e", 48),
    (ChangeType.ASSET_CHANGE,    False): ("cdo",              72),
    (ChangeType.ASSET_CHANGE,    True):  ("district_m_and_e", 48),
}


# US-S22-003 — display labels echoed back in `routed_to` on the bundle
# endpoint. The system-side `required_role` (above) stays canonical
# for downstream sweeps; this map is the operator-facing surface.
ROUTE_LABEL: dict[tuple[str, bool], str] = {
    (ChangeType.CORRECTION,      False): "CDO (parish)",
    (ChangeType.CORRECTION,      True):  "M&E Officer",
    (ChangeType.LIFE_EVENT,      False): "CDO (parish)",
    (ChangeType.LIFE_EVENT,      True):  "M&E Officer",
    (ChangeType.VERIFICATION,    False): "CDO (parish)",
    (ChangeType.VERIFICATION,    True):  "M&E Officer",
    (ChangeType.ADDRESS_MOVE,    False): "CDO + receiving CDO",
    (ChangeType.ADDRESS_MOVE,    True):  "District M&E",
    (ChangeType.ROSTER_CHANGE,   False): "CDO (parish)",
    (ChangeType.ROSTER_CHANGE,   True):  "District M&E",
    (ChangeType.ASSET_CHANGE,    False): "CDO (parish)",
    (ChangeType.ASSET_CHANGE,    True):  "District M&E",
}


def route_label(change_type: str, *, pmt_relevant: bool) -> str:
    """Operator-facing reviewer label for the (change_type, pmt) pair.

    ROUTE_LABEL first: it is the spec's own wording, and some of it
    says something the role code cannot. "CDO + receiving CDO" on an
    address move names TWO reviewers — a household moving between
    districts needs both — and there is no single role code for that.

    This stopped consulting ROUTE_LABEL and returned the role instead,
    so the bundle endpoint echoed `cdo_receiving` at operators where it
    had said "CDO + receiving CDO". Deployed on 25 September before it
    was caught.

    Falls back to the role's catalogue label, then to the bare code:
    the legacy ADDITION / REMOVAL / VITAL_EVENT / PROGRAMME_STATE /
    RECERTIFICATION rows have no spec label, and `parish_chief` is what
    they have always shown.
    """
    if (change_type, pmt_relevant) in ROUTE_LABEL:
        return ROUTE_LABEL[(change_type, pmt_relevant)]
    role, _ = route(change_type, pmt_relevant=pmt_relevant)
    return role


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
    if rule is None:
        from .services import UpdError
        raise UpdError(
            "Missing active UPD routing configuration for "
            f"change_type={change_type!r}, pmt_relevant={pmt_relevant!r}"
        )
    return rule.required_role, timedelta(hours=rule.sla_hours)
