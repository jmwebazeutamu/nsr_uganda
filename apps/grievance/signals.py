"""GRM ↔ UPD wiring.

SAD §4.4: "A grievance that resolves to a data correction opens a
linked UPD; the UPD's commit closes the GRM case."

This module subscribes to post_change_committed and closes the matching
grievance (linked_change_request_id == change_request.id). The
auto-open path is the inverse — apps.grievance.services.
open_change_request_for_grievance creates the linked DRAFT CR.

Connected at module-import time; apps.grievance.apps.ready imports this
module to wire the receiver.
"""

from __future__ import annotations

from django.utils import timezone

from apps.update_workflow.services import post_change_committed

from .models import Grievance, GrievanceStatus


def on_change_committed(sender, *, change_request, target, **kwargs):
    """When a ChangeRequest commits, close any grievance linked to it."""
    g = Grievance.objects.filter(
        linked_change_request_id=change_request.id,
    ).exclude(status__in=[GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED]).first()
    if g is None:
        return
    g.status = GrievanceStatus.CLOSED
    g.closed_at = timezone.now()
    g.resolution_narrative = (
        g.resolution_narrative
        or f"Auto-closed by ChangeRequest {change_request.id} commit."
    )
    g.save(update_fields=[
        "status", "closed_at", "resolution_narrative", "updated_at",
    ])


post_change_committed.connect(on_change_committed, dispatch_uid="grm.on_change_committed")
