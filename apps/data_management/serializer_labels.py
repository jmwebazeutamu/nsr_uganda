"""Shared helper that injects <field>_label SerializerMethodFields
onto a DRF ModelSerializer from a choice_field_map entry.

Extracted from apps.data_management.api so other apps (partners, ...)
can attach the same shape of label fields without duplicating
the DRF metaclass-injection dance. See ADR-0010 §5.
"""

from __future__ import annotations

from collections.abc import Callable

from rest_framework import serializers


def attach_label_methodfields(
    serializer_cls,
    fmap: dict[str, tuple[str, str]],
    *,
    as_of_for: Callable | None = None,
) -> None:
    """Inject a SerializerMethodField for each entry in `fmap` onto
    `serializer_cls`. Each `<field>_label` (single) or
    `<field>_labels` (multi) field calls
    apps.reference_data.services.resolve_label / resolve_labels at
    serialise time.

    `fmap` shape: {field_name: (list_name, "single" | "multi")}.

    `as_of_for` is an optional callable that resolves an `as_of`
    date from the serialised object. When omitted, the resolver
    uses today (versioned-but-current). For Household/Member the
    intake date is preferred; for partners the live label is
    appropriate.

    The fields are written into `_declared_fields` because the
    DRF SerializerMetaclass collected them at class creation; a
    post-creation `setattr` alone won't be picked up.
    """
    for field, (list_name, kind) in fmap.items():
        attr = f"{field}_label" if kind == "single" else f"{field}_labels"
        method_name = f"get_{attr}"

        def _make(field=field, kind=kind, list_name=list_name,
                  as_of_for=as_of_for):
            def method(self, obj):
                from apps.reference_data.services import (
                    resolve_label,
                    resolve_labels,
                )
                as_of = as_of_for(obj) if as_of_for else None
                resolver = resolve_label if kind == "single" else resolve_labels
                return resolver(
                    list_name,
                    getattr(obj, field),
                    as_of=as_of,
                    context={
                        "entity_id": getattr(obj, "id", None),
                        "field": field,
                    },
                )
            return method

        smf = serializers.SerializerMethodField(method_name=method_name)
        setattr(serializer_cls, attr, smf)
        serializer_cls._declared_fields[attr] = smf
        setattr(serializer_cls, method_name, _make())
