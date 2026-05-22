"""Registry for `registered_function` PMT features (ADR-0025).

Features whose computation doesn't fit the JSON DSL — FIES roll-ups,
FCS aggregation, percentile-based features that will land later —
live as decorated Python functions in `apps.pmt.registered_features`.
`PMTModelVersion.variables` references them by string name:

    {"name": "food_consumption_score_v1", "weight": 0.0,
     "feature": {"type": "registered_function",
                 "function": "food_consumption_score_v1"}}

Adding a new registered function requires:
  1. Write the function in `apps/pmt/registered_features.py` with
     `@register("name")`.
  2. Submit through code review (no JSON-only path because Python
     evaluation has more blast radius than a DSL expression).
  3. The Django system check at apps.pmt.checks.PMTRegisteredFunctions
     fails startup if any active model version references a name
     that isn't in the registry — so removing or renaming one is a
     deploy-blocking change.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_REGISTRY: dict[str, Callable[[Any], Any]] = {}


def register(name: str) -> Callable:
    """Decorator: add a function to the registry under `name`.

    Usage:
        @register("food_consumption_score_v1")
        def fcs_v1(features):
            ...

    Raises ValueError on duplicate names — the registry is global
    state, so a silent overwrite would mask a typo that another
    contributor relied on.
    """
    if not name or not isinstance(name, str):
        raise ValueError("register() requires a non-empty string name")

    def _decorator(fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
        if name in _REGISTRY:
            raise ValueError(
                f"registered_function {name!r} is already registered "
                f"(by {_REGISTRY[name].__module__}.{_REGISTRY[name].__name__}); "
                f"pick a distinct name.",
            )
        _REGISTRY[name] = fn
        return fn
    return _decorator


def call_registered(name: str, features: Any) -> Any:
    """Invoke a registered function by name. Raises LookupError when
    missing — the system check fails startup before this ever runs,
    so reaching this branch is a programming error, not a runtime
    fall-through."""
    fn = _REGISTRY.get(name)
    if fn is None:
        raise LookupError(
            f"registered_function {name!r} is not registered. "
            f"Available: {sorted(_REGISTRY)}",
        )
    return fn(features)


def is_registered(name: str) -> bool:
    return name in _REGISTRY


def registered_names() -> list[str]:
    """List every name currently in the registry — used by the
    startup check + the admin Rule Editor preview."""
    return sorted(_REGISTRY)


def _clear_for_tests() -> None:
    """Test-only — drop the registry contents. Used to isolate
    register() tests; production code must never call this."""
    _REGISTRY.clear()
