"""The reasons a grievance may change state, and what each one asserts.

These lived in `screens-grm.jsx` as three JavaScript arrays, so the
server took whatever string arrived. That is how a case was resolved
with the narrative "ab", and how "Data correction committed via linked
UPD" was accepted while the linked change request was an empty draft,
and "30-day grace expired without dispute" two minutes after resolve.

A reason is a claim about the world. Some claims are checkable, and the
ones that are get checked here rather than trusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# An operator must say something of their own beside the canned reason.
# Six characters is not a quality bar; it rejects "ab" and "ok".
MIN_NOTE_LENGTH = 6


@dataclass(frozen=True)
class Reason:
    code: str
    label: str
    # Checked server-side before the transition is allowed.
    requires: str = ""
    help_text: str = field(default="")


ESCALATE = (
    Reason("sla_breached", "SLA breached without resolution"),
    Reason("needs_higher_authority", "Requires higher authority (programme override)"),
    Reason("citizen_request", "Citizen escalation request on record"),
    Reason("other", "Other (specify in note)"),
)

RESOLVE = (
    Reason(
        "upd_committed", "Data correction committed via linked UPD",
        requires="linked_cr_applied",
        help_text=(
            "Only once the linked change request has been approved or "
            "applied. A draft is not a correction."
        ),
    ),
    Reason("not_substantiated", "Operator follow-up — issue not substantiated"),
    Reason("withdrawn", "Citizen withdrew complaint"),
    Reason("other", "Other (specify in note)"),
)

CLOSE = (
    Reason("reporter_confirmed", "Resolution confirmed by reporter"),
    Reason(
        "grace_expired", "30-day grace expired without dispute",
        requires="grace_elapsed",
        help_text=(
            "Only once the grace period has actually elapsed since the "
            "case was resolved."
        ),
    ),
    Reason("other", "Other (specify in note)"),
)

# No REOPEN vocabulary: there is no reopen action. See
# apps/grievance/visibility.allowed_actions for why.

BY_ACTION = {
    "escalate": ESCALATE,
    "resolve": RESOLVE,
    "close": CLOSE,
}


def catalogue() -> dict[str, list[dict]]:
    """The vocabulary, for any client that offers a choice.

    Served by the API so the console stops carrying its own copy.
    """
    return {
        action: [
            {
                "code": r.code, "label": r.label,
                "requires": r.requires, "help_text": r.help_text,
            }
            for r in reasons
        ]
        for action, reasons in BY_ACTION.items()
    }


def lookup(action: str, code: str) -> Reason | None:
    for reason in BY_ACTION.get(action, ()):
        if reason.code == code:
            return reason
    return None


def narrative_for(reason: Reason, note: str) -> str:
    """The stored sentence: the canned claim, then the operator's own
    words. One string, because that is what a reviewer reads."""
    return f"{reason.label} — {note}".strip(" —")
