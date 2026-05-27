"""US-S11-044 — Pipeline gateway for intra-household DQA.

Wraps the pure HouseholdRuleEvaluator + applies severity routing per
the spec:

    BLOCK                 → raise DqaBlockError (caller aborts).
    REJECT_WITH_OVERRIDE  → raise DqaRejectWithOverrideError unless
                            override_reason is supplied; otherwise the
                            override is recorded and the call proceeds.
    FLAG                  → does not abort. Emits a
                            `dqa.household.flag` AuditEvent so UPD can
                            open a review case (full UPD-case wiring is
                            its own follow-up).
    INFO                  → logged via the evaluation row only.

Feature-flag-gated on DQA_INTRA_HOUSEHOLD_ENABLED. When off, the
gateway is a no-op — it returns None and the caller proceeds.

Convention: at DIH_INGEST the staged record always survives (the queue
is the triage surface), so we persist the evaluation but never abort.
At DIH_PROMOTE the gateway can refuse promotion (BLOCK / REJECT). At
REGISTRY_POST_PROMOTE the promotion already happened, so the gateway
records the evaluation for audit only and never raises.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)


# Per-stage abort policy. The gateway consults this table instead of
# branching on the stage string at each callsite — adding a new stage
# means one entry here.
_STAGE_CAN_ABORT = {
    "dih_ingest": False,
    "dih_promote": True,
    "registry_post_promote": False,
}


class DqaBlockError(Exception):
    """The household failed at least one BLOCK rule and the stage's
    abort policy says we must refuse. Carries the failed rule codes
    so the caller can surface them verbatim."""

    def __init__(self, codes: list[str], evaluation_id: str | None = None):
        self.codes = codes
        self.evaluation_id = evaluation_id
        super().__init__(
            f"Household DQA blocked: {', '.join(codes) or '<unknown>'}"
        )


class DqaRejectWithOverrideError(Exception):
    """The household failed at least one REJECT_WITH_OVERRIDE rule.
    Pass `override_reason` to the gateway to proceed; the override is
    audited."""

    def __init__(self, codes: list[str], evaluation_id: str | None = None):
        self.codes = codes
        self.evaluation_id = evaluation_id
        super().__init__(
            "Household DQA reject-with-override: "
            f"{', '.join(codes) or '<unknown>'}"
        )


def _flag_enabled() -> bool:
    return bool(getattr(settings, "DQA_INTRA_HOUSEHOLD_ENABLED", False))


def _collect_by_severity(results: list[dict]) -> dict[str, list[str]]:
    """Group failed rule_codes by severity. Pass results are dropped;
    only fail / error contribute. Error treated as block."""
    grouped: dict[str, list[str]] = {
        "block": [], "reject_with_override": [], "flag": [], "info": [],
    }
    for r in results:
        if r.get("status") not in ("fail", "error"):
            continue
        sev = r.get("severity") or "block"
        # Errors with no severity fall through to block — the rule
        # author didn't write a passing case, so we err on the side
        # of safety.
        if r.get("status") == "error":
            sev = "block"
        grouped.setdefault(sev, []).append(r.get("rule_code") or "<unknown>")
    return grouped


def run_household_gate(
    payload: dict, *,
    stage: str,
    household_id: str,
    actor: str = "system",
    household_version: int | None = None,
    override_reason: str | None = None,
) -> Any:
    """Run the intra-household evaluator and apply the routing policy.

    Returns the persisted DqaEvaluation row (or None when the flag is
    off). Raises DqaBlockError / DqaRejectWithOverrideError when the
    stage permits abort and the household failed a blocking rule.

    `override_reason` is consumed only when REJECT_WITH_OVERRIDE
    violations are present; it does NOT bypass BLOCK rules.
    """
    if not _flag_enabled():
        return None
    # Lazy-import: avoids dragging Django models into module import
    # graph when the flag is off / during apps.dqa.__init__.
    from apps.security.audit import emit as emit_audit

    from .household_evaluator import persist_household_evaluation

    eval_row = persist_household_evaluation(
        payload, stage=stage, actor=actor,
        household_id=household_id,
        household_version=household_version,
    )

    by_severity = _collect_by_severity(eval_row.results or [])
    can_abort = _STAGE_CAN_ABORT.get(stage, False)

    if by_severity["block"] and can_abort:
        raise DqaBlockError(by_severity["block"], evaluation_id=str(eval_row.id))

    if by_severity["reject_with_override"] and can_abort:
        if not override_reason:
            raise DqaRejectWithOverrideError(
                by_severity["reject_with_override"],
                evaluation_id=str(eval_row.id),
            )
        # Override consumed — record the fact in the audit chain. The
        # household_id reference is the link back; we don't re-emit
        # the payload.
        emit_audit(
            "dqa.household.override", "household", household_id,
            actor=actor,
            reason=override_reason,
            field_changes={
                "evaluation_id": str(eval_row.id),
                "stage": stage,
                "overridden_codes": by_severity["reject_with_override"],
            },
        )

    if by_severity["flag"]:
        # UPD review case opening is its own follow-up; for now we emit
        # the marker AuditEvent so an UPD reactor can pick it up off the
        # audit chain (the queue scaffold + case-open hook lands in
        # P8 / a separate UPD ticket).
        emit_audit(
            "dqa.household.flag", "household", household_id,
            actor=actor,
            reason=f"stage={stage}",
            field_changes={
                "evaluation_id": str(eval_row.id),
                "stage": stage,
                "flagged_codes": by_severity["flag"],
            },
        )

    if by_severity["info"]:
        # Info severity is informational — captured by the evaluation
        # row, no extra audit, but log so ops dashboards see it.
        logger.info(
            "dqa.household.info household=%s stage=%s codes=%s",
            household_id, stage, by_severity["info"],
        )

    return eval_row


# ---------------------------------------------------------------------------
# Household ORM → DSL payload
#
# At DIH ingest / promote the canonical_payload lives on the
# StageRecord already, so callers pass it directly. At
# registry_post_promote the household is an ORM instance — we shape it
# into the DSL-readable dict here.

def household_to_dqa_payload(household) -> dict:
    """Project a Household ORM (with prefetched members) into the dict
    shape the DSL operators expect.

    Keeps every field the seeded rules touch: relationship_to_head,
    age, line_number, nin_hash, sex, mother_line_number,
    father_line_number, orphan_flag, disability_flag,
    reported_household_size. Other fields the DSL might walk later
    (via `$.<path>`) are merged in opportunistically so rule authors
    don't have to wait for this helper to learn a new key.
    """
    members = []
    for m in household.members.all():
        members.append({
            "id": str(m.id),
            "line_number": getattr(m, "line_number", None),
            "relationship_to_head": getattr(m, "relationship_to_head", None),
            "age": getattr(m, "age", None),
            "sex": getattr(m, "sex", None),
            "nin_hash": getattr(m, "nin_hash", None),
            "mother_line_number": getattr(m, "mother_line_number", None),
            "father_line_number": getattr(m, "father_line_number", None),
            "orphan_flag": getattr(m, "orphan_flag", None),
            "disability_flag": getattr(m, "disability_flag", None),
            "alive": getattr(m, "alive", None),
        })
    return {
        "household_id": str(household.id),
        "reported_household_size": getattr(household, "reported_household_size", None),
        "members": members,
    }
