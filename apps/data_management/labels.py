"""Glue between the choice_field_map and the Household / Member
model classes (ADR-0010 §5).

When the data_management AppConfig is ready, we attach
`get_<field>_label()` (single-value) or `get_<field>_labels()`
(multi-value) onto each model so callers — admin views, serializers,
debug shell — can reach the resolved label without re-implementing
the lookup. The map is the only place a list_name is named.
"""

from __future__ import annotations

from .choice_field_map import HOUSEHOLD_FIELDS, MEMBER_FIELDS


def _make_single_label_method(field: str, list_name: str):
    """Closure: capture (field, list_name) so the method resolves
    `self.<field>` at call time, not at attach time."""
    def _label(self, *, as_of=None, language: str = "en") -> str:
        from apps.reference_data.services import resolve_label
        return resolve_label(
            list_name,
            getattr(self, field),
            language,
            as_of,
            context={"entity_id": getattr(self, "id", None), "field": field},
        )
    _label.__name__ = f"get_{field}_label"
    _label.__qualname__ = _label.__name__
    _label.__doc__ = (
        f"Resolve `self.{field}` against ChoiceList `{list_name}` "
        f"at `as_of` (default today) and return the label string. "
        f"Returns the raw code on miss; see services.resolve_label."
    )
    return _label


def _make_multi_label_method(field: str, list_name: str):
    def _labels(self, *, as_of=None, language: str = "en") -> list[str]:
        from apps.reference_data.services import resolve_labels
        return resolve_labels(
            list_name,
            getattr(self, field),
            language,
            as_of,
            context={"entity_id": getattr(self, "id", None), "field": field},
        )
    _labels.__name__ = f"get_{field}_labels"
    _labels.__qualname__ = _labels.__name__
    _labels.__doc__ = (
        f"Multi-select counterpart of get_{field}_label — `self.{field}` "
        f"is whitespace-split into codes and resolved against `{list_name}`."
    )
    return _labels


def attach_label_methods(household_cls, member_cls) -> None:
    """Idempotent: re-attaching the same method is a no-op."""
    for model, fmap in ((household_cls, HOUSEHOLD_FIELDS), (member_cls, MEMBER_FIELDS)):
        for field, (list_name, kind) in fmap.items():
            if kind == "multi":
                meth = _make_multi_label_method(field, list_name)
                attr = f"get_{field}_labels"
            else:
                meth = _make_single_label_method(field, list_name)
                attr = f"get_{field}_label"
            setattr(model, attr, meth)
