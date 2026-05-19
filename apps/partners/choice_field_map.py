"""Partner-module coded-field registrations (ADR-0010 §4, ADR-0011).

`MODEL_FIELDS` is a model_name -> field_name -> (list_name, kind)
mapping. The data_management.E001 system check walks this when the
partners app is installed, asserting every field listed here is a
plain CharField with empty `choices`.

The structure mirrors apps.data_management.choice_field_map but is
shipped per-app so each module owns its own slice of coded fields.
"""

from __future__ import annotations

from typing import Literal

Kind = Literal["single", "multi"]


MODEL_FIELDS: dict[str, dict[str, tuple[str, Kind]]] = {
    "Partner": {
        "type":   ("partner_type",   "single"),
        "sector": ("partner_sector", "single"),
        "status": ("partner_status", "single"),
        "tone":   ("ui_tone",        "single"),
    },
    "PartnerContact": {
        "role": ("partner_contact_role", "single"),
    },
    "Programme": {
        "kind":   ("programme_kind",   "single"),
        "status": ("programme_status", "single"),
    },
    # DataSharingAgreement / DsaSignature land in US-S23-006.
}
