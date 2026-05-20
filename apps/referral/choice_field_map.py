"""Referral-module coded-field registrations (ADR-0010 §4, ADR-0015).

`MODEL_FIELDS` is the single-source-of-truth mapping of every
referral-side coded field to the ChoiceList it resolves against.
The `data_management.E001` system check walks this when the
referral app is installed, asserting every field listed here is
a plain CharField with empty `choices`.

Per ADR-0015 (US-S26-003) the legacy `ReferralStatus` and
`EnrolmentStatus` TextChoices were removed; their codes live in
the `referral_status` (US-S26-002) and `programme_enrolment_status`
(US-S25-006) ChoiceLists.
"""

from __future__ import annotations

from typing import Literal

Kind = Literal["single", "multi"]


MODEL_FIELDS: dict[str, dict[str, tuple[str, Kind]]] = {
    "Referral": {
        "status": ("referral_status", "single"),
    },
    "ProgrammeEnrolment": {
        "status": ("programme_enrolment_status", "single"),
    },
}
