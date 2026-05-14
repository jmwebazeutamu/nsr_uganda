"""Hook PMT recompute to the UPD post-commit signal.

Connected in apps/pmt/apps.py::ready. Until apps.pmt is installed and
ready, post_change_committed has no listeners (the UPD module signal is
defined but unused), which is the correct Sprint 0 behaviour.
"""

from __future__ import annotations

from apps.data_management.models import Household
from apps.update_workflow.models import EntityType
from apps.update_workflow.services import post_change_committed

from .services import recompute_for_household


def on_change_committed(sender, *, change_request, target, **kwargs):
    if not change_request.pmt_relevant:
        return
    # Resolve the affected household. Member-level updates recompute for
    # the parent household, not for the member.
    if change_request.entity_type == EntityType.HOUSEHOLD:
        household = target
    else:
        household = Household.objects.get(pk=target.household_id)
    recompute_for_household(
        household, triggered_by="upd_commit", actor=change_request.approver or "system",
    )


# Connect at module-import time so apps.py::ready importing this module is
# enough to wire the hook. dispatch_uid keeps it a single connection.
post_change_committed.connect(on_change_committed, dispatch_uid="pmt.on_change_committed")


def connect() -> None:
    """Retained for backwards-compat / explicit re-connect during tests."""
    post_change_committed.connect(on_change_committed, dispatch_uid="pmt.on_change_committed")
