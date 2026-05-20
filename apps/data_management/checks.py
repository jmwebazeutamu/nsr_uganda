"""Django system checks for the data_management app.

`data_management.E001` enforces the ADR-0010 invariant: every field
registered in `choice_field_map.HOUSEHOLD_FIELDS` /
`MEMBER_FIELDS` (and any analogous registration shipped by the
partners app) MUST be a plain `CharField` with NO `choices=` set.
The DB is the single source of truth for coded values; a
`TextChoices` enum or `choices=[(...)]` declaration on the field
recreates the duplication ADR-0010 set out to eliminate.

This runs as part of `manage.py check` so CI fails on any
regression. To extend coverage to additional models, register the
field map under `_REGISTERED_FIELD_MAPS` below.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.apps import apps as django_apps
from django.core.checks import Error, register

E001_HINT = (
    "Drop the choices= argument; codes are persisted as raw "
    "ChoiceOption.code strings and resolved at read time. See ADR-0010."
)


# (app_label, model_name, field_map_dict)
# Lazy imports keep this module importable before app config ready.
def _registered_field_maps() -> list[tuple[str, str, dict]]:
    from apps.data_management.choice_field_map import (
        HOUSEHOLD_FIELDS,
        MEMBER_FIELDS,
    )
    pairs: list[tuple[str, str, dict]] = [
        ("data_management", "Household", HOUSEHOLD_FIELDS),
        ("data_management", "Member", MEMBER_FIELDS),
    ]
    # Partner app field map is opt-in: registered only when the
    # apps.partners.choice_field_map module exists (lands in US-S23-004).
    try:
        from apps.partners import choice_field_map as partners_map  # type: ignore
    except ImportError:
        partners_map = None
    if partners_map is not None:
        for model_name in getattr(partners_map, "MODEL_FIELDS", {}):
            pairs.append(
                ("partners", model_name,
                 partners_map.MODEL_FIELDS[model_name]),
            )
    # Referral app field map (lands in US-S26-003 / ADR-0015).
    try:
        from apps.referral import choice_field_map as referral_map  # type: ignore
    except ImportError:
        referral_map = None
    if referral_map is not None:
        for model_name in getattr(referral_map, "MODEL_FIELDS", {}):
            pairs.append(
                ("referral", model_name,
                 referral_map.MODEL_FIELDS[model_name]),
            )
    return pairs


def _iter_field_violations() -> Iterable[Error]:
    for app_label, model_name, fmap in _registered_field_maps():
        try:
            model = django_apps.get_model(app_label, model_name)
        except LookupError:
            # App not installed yet — skip; another check will flag
            # a missing model if the field map references one.
            continue
        for field_name in fmap:
            try:
                field = model._meta.get_field(field_name)
            except Exception:
                yield Error(
                    f"choice_field_map references unknown field "
                    f"{app_label}.{model_name}.{field_name}",
                    obj=model,
                    id="data_management.E001",
                )
                continue
            choices = getattr(field, "choices", None)
            if choices:
                yield Error(
                    f"{app_label}.{model_name}.{field_name} declares "
                    f"choices= but is registered in choice_field_map. "
                    f"Coded fields must be plain CharField (ADR-0010).",
                    hint=E001_HINT,
                    obj=field,
                    id="data_management.E001",
                )


@register()
def check_no_textchoices_on_mapped_fields(app_configs, **kwargs):
    """Run on every `manage.py check` / CI startup. Bound to the
    data_management app config in apps.py."""
    return list(_iter_field_violations())
