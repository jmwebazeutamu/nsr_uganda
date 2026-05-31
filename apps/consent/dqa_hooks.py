"""Capture-time AC-CONSENT-* checks (US-CONSENT-09).

These are the synchronous guards invoked before a ConsentRecord is written
(apps.consent.api.MemberCaptureView). They mirror the seeded DQA rule pack in
scripts/seed_dqa_consent_rules.py — the rule pack carries the dual-approved,
versioned definitions the engine evaluates at promotion; these hooks enforce
the same intent at the point of capture so a bad record never lands.

Returned value is a list of {code, message} dicts — empty means the capture
passes. Severity follows the four-tier vocabulary in 04_ui_design_brief.md §8;
at capture time every rule here is blocking.
"""

from __future__ import annotations

from .models import CaptureMethod, ConsentState

# Statement-version-current and capture-timestamp-plausible are evaluated by
# the engine over the staged record; the capture endpoint enforces the two
# that must hold at the instant of capture plus the minor-proxy invariant.
MINOR_AGE = 18


def check_capture(*, state: str, capture_method: str, witness_name: str,
                  witness_role: str, member, proxy_relationship: str,
                  purpose_code: str) -> list[dict]:
    errors: list[dict] = []

    # AC-CONSENT-MANDATORY — REGISTRATION must be an explicit grant/refusal,
    # never blank, to proceed.
    if purpose_code == "REGISTRATION" and not state:
        errors.append({
            "code": "AC-CONSENT-MANDATORY",
            "message": "Registration consent state is mandatory.",
        })

    # AC-CONSENT-METHOD-VALID — a verbal-witnessed grant requires a witness
    # name AND role (CR1: guards against coerced verbal consent).
    if (state == ConsentState.GRANTED
            and capture_method == CaptureMethod.VERBAL_WITNESSED):
        if not witness_name.strip() or not witness_role.strip():
            errors.append({
                "code": "AC-CONSENT-METHOD-VALID",
                "message": (
                    "Verbal-witnessed consent requires both a witness name "
                    "and a witness role."),
            })

    # AC-CONSENT-MINOR-PROXY-PRESENT — a member under 18 must have a proxy
    # relationship recorded when granting.
    age = getattr(member, "age_years", None)
    if (state == ConsentState.GRANTED and age is not None and age < MINOR_AGE
            and not proxy_relationship.strip()):
        errors.append({
            "code": "AC-CONSENT-MINOR-PROXY-PRESENT",
            "message": (
                f"Members under {MINOR_AGE} require a proxy relationship "
                "(parent/guardian) for consent."),
        })

    return errors
