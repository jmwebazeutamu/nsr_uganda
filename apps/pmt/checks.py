"""Django system check — fail startup if any ACTIVE PMTModelVersion
variable references a `registered_function` name that isn't actually
registered (ADR-0025).

Without this gate, removing or renaming a function in
apps.pmt.registered_features without simultaneously updating the
active model's JSON would silently produce 0-contributions for that
variable — scoring drift with no error. The check turns the drift
into a deploy-blocking issue: `python manage.py check` exits non-zero,
CI refuses, and the engineer sees the broken reference at submit time.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.core.checks import Error, register


@register("pmt")
def pmt_registered_functions_check(app_configs: Any, **kwargs: Any) -> list[Error]:
    """Walk every ACTIVE PMTModelVersion's variables and confirm any
    `registered_function` reference is currently registered. Inactive
    versions are skipped — a stale draft isn't a deploy blocker."""
    errors: list[Error] = []
    # Import inside the callable so the AppConfig.ready() ordering
    # stays safe — the check is registered before the registry's
    # decorators have run.
    from apps.pmt.registry import is_registered, registered_names

    try:
        PMTModelVersion = apps.get_model("pmt", "PMTModelVersion")
    except LookupError:
        return errors

    try:
        active_qs = PMTModelVersion.objects.filter(status="active")
    except Exception:
        # First-run migrate before the table exists. Fail open.
        return errors

    for mv in active_qs:
        for var in (mv.variables or []):
            feat = var.get("feature") if isinstance(var, dict) else None
            if not isinstance(feat, dict):
                continue
            if feat.get("type") != "registered_function":
                continue
            name = feat.get("function")
            if name and not is_registered(name):
                errors.append(Error(
                    (
                        f"PMTModelVersion v{mv.version} variable "
                        f"{var.get('name', '?')!r} references "
                        f"registered_function {name!r} which is not "
                        f"registered. Available: {registered_names()}."
                    ),
                    hint=(
                        "Add an @register decorator in "
                        "apps/pmt/registered_features.py, or clone the "
                        "model version and remove the reference."
                    ),
                    obj=mv,
                    id="pmt.E001",
                ))
    return errors
