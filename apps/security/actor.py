"""The acting identity for a state transition — taken from the session,
never from the request body.

Approve / reject / merge / promote endpoints used to read the actor out of
the payload:

    actor = serializers.CharField(max_length=64)      # client-supplied
    commit_change_request(req, approver=ser.validated_data["actor"])

That defeated two controls at once:

1. **Segregation of duties.** Every author-cannot-approve guard compares the
   record's author against the approver. When the approver is a string the
   caller chooses, the requester approves their own change request by sending
   somebody else's name (AC-UPD-NO-SELF-APPROVE, AC-DDUP-MODEL-VERSION,
   AC-CHOICELIST-NO-SELF-APPROVE all reduce to a string comparison the
   attacker controls).

2. **Non-repudiation.** `emit_audit(actor=...)` wrote that same string into
   the hash-chained AuditEvent log. The chain proves a row was not altered
   after it was written; it cannot prove the person named in it did anything.
   For a DPPA-governed registry whose audit trail is the primary compliance
   artefact, an attacker-chosen actor field hollows the whole chain out.

`apps/data_requests/api.py` and the UPD bundle endpoint already derived the
actor from `request.user`, so the correct pattern existed — it just was not
applied uniformly.

Use `actor_from_request(request)` at every operator-initiated transition.
System-initiated paths (NIRA auto-commit, connector runs, scheduled jobs)
pass their own identifier explicitly at the service layer and never go
through here — that seam stays visible on purpose.
"""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied


def actor_from_request(request) -> str:
    """Return the authenticated username to attribute this action to.

    Raises PermissionDenied for anonymous callers rather than falling back to
    a placeholder: every caller of this helper is behind IsAuthenticated, so
    an anonymous request here means a permission class was removed, and the
    audit trail should refuse the write rather than record "system".
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        raise PermissionDenied(
            "an authenticated user is required to act on this record",
        )
    username = user.get_username()
    if not username:
        raise PermissionDenied("authenticated user has no username to attribute")
    return username
