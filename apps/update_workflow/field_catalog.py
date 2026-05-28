"""Backend-owned Open-CR field catalog.

The change-request wizard must not carry its own questionnaire/model
catalog. This module derives the editable surface from Django model
metadata and the existing ADR-0010 ChoiceList maps in
apps.data_management.choice_field_map.
"""

from __future__ import annotations

from functools import lru_cache

from django.db import models

from apps.data_management import choice_field_map as choices
from apps.data_management.models import (
    Disability,
    Dwelling,
    Education,
    Employment,
    FoodConsumption,
    FoodSecurity,
    Health,
    Household,
    Livelihood,
    Member,
    Utilities,
)
from apps.reference_data.models import GeographicUnit

EXCLUDED_FIELDS = {
    "id",
    "created_at",
    "updated_at",
    "deleted_at",
    "is_deleted",
    "sub_region_code",
    "merged_into",
    "nin_value",
    "nin_hash",
    "nin_last4",
    "current_pmt_score",
    "current_vulnerability_band",
    "current_intake_source",
    "current_consent_state",
    "head_member",
    "household",
    "member",
}

QUESTIONNAIRE_SECTIONS = {
    "household": "A/B",
    "member": "C",
    "health": "D",
    "disability": "D",
    "education": "E",
    "employment": "F",
    "dwelling": "G1-G7",
    "utilities": "G8-G14",
    "livelihood": "G16/H",
    "food_security": "I1-I8",
    "food_consumption": "I9-I17",
}

CATALOG_MODELS = [
    {
        "key": "household",
        "label": "Household",
        "tone": "identity",
        "model": Household,
        "entity": "household",
        "choice_map": choices.HOUSEHOLD_FIELDS,
    },
    {
        "key": "member",
        "label": "Roster member",
        "tone": "update",
        "model": Member,
        "entity": "member",
        "choice_map": choices.MEMBER_FIELDS,
    },
    {
        "key": "health",
        "label": "Health",
        "tone": "danger",
        "model": Health,
        "entity": "member",
        "choice_map": choices.HEALTH_FIELDS,
    },
    {
        "key": "disability",
        "label": "Disability",
        "tone": "danger",
        "model": Disability,
        "entity": "member",
        "choice_map": choices.DISABILITY_FIELDS,
    },
    {
        "key": "education",
        "label": "Education",
        "tone": "programme",
        "model": Education,
        "entity": "member",
        "choice_map": choices.EDUCATION_FIELDS,
    },
    {
        "key": "employment",
        "label": "Employment",
        "tone": "system",
        "model": Employment,
        "entity": "member",
        "choice_map": choices.EMPLOYMENT_FIELDS,
    },
    {
        "key": "dwelling",
        "label": "Dwelling",
        "tone": "eligibility",
        "model": Dwelling,
        "entity": "household",
        "choice_map": choices.DWELLING_FIELDS,
    },
    {
        "key": "utilities",
        "label": "Utilities",
        "tone": "eligibility",
        "model": Utilities,
        "entity": "household",
        "choice_map": choices.UTILITIES_FIELDS,
    },
    {
        "key": "livelihood",
        "label": "Livelihood & agriculture",
        "tone": "quality",
        "model": Livelihood,
        "entity": "household",
        "choice_map": choices.LIVELIHOOD_FIELDS,
    },
    {
        "key": "food_security",
        "label": "Food security",
        "tone": "quality",
        "model": FoodSecurity,
        "entity": "household",
        "choice_map": choices.FOOD_SECURITY_FIELDS,
    },
    {
        "key": "food_consumption",
        "label": "Food consumption",
        "tone": "quality",
        "model": FoodConsumption,
        "entity": "household",
        "choice_map": choices.FOOD_CONSUMPTION_FIELDS,
    },
]


PMT_RELEVANT_MODELS = {
    "dwelling",
    "utilities",
    "livelihood",
    "food_security",
    "food_consumption",
    "education",
    "employment",
    "health",
    "disability",
}


def _label_for(field: models.Field) -> str:
    return str(field.verbose_name or field.name).replace("_", " ").title()


def _constraints_for(field: models.Field) -> dict:
    if isinstance(field, (models.PositiveSmallIntegerField, models.PositiveIntegerField)):
        return {"min": 0, "step": 1}
    if isinstance(field, models.IntegerField):
        return {"step": 1}
    if isinstance(field, models.DecimalField):
        return {"step": float(10 ** -field.decimal_places)}
    if isinstance(field, models.DateField):
        return {"max_today": True}
    return {}


def _type_for(field: models.Field, choice_map: dict) -> str:
    if field.name in choice_map:
        return "select"
    if isinstance(field, models.ForeignKey) and field.remote_field.model is GeographicUnit:
        return "geo"
    if isinstance(field, models.BooleanField):
        return "boolean"
    if isinstance(field, models.DateField):
        return "date"
    if isinstance(
        field,
        (
            models.IntegerField,
            models.PositiveIntegerField,
            models.PositiveSmallIntegerField,
            models.DecimalField,
            models.FloatField,
        ),
    ):
        return "number"
    return "text"


def _editable_fields(model: type[models.Model]):
    for field in model._meta.get_fields():
        if not getattr(field, "concrete", False):
            continue
        if field.auto_created or field.name in EXCLUDED_FIELDS:
            continue
        yield field


def _serialise_model_field(section: dict, field: models.Field) -> dict:
    choice_map = section["choice_map"]
    field_type = _type_for(field, choice_map)
    out = {
        "key": field.name,
        "field_id": f"{section['key']}.{field.name}",
        "model": section["model"]._meta.label,
        "model_path": f"{section['model'].__name__}.{field.name}",
        "label": _label_for(field),
        "questionnaire_section": QUESTIONNAIRE_SECTIONS.get(section["key"], ""),
        "type": field_type,
        "pmt": section["key"] in PMT_RELEVANT_MODELS,
        "entity": section["entity"],
    }
    if field.name in choice_map:
        list_name, kind = choice_map[field.name]
        out["choice_list"] = list_name
        out["choice_kind"] = kind
    if field_type == "geo":
        out["options_source"] = (
            "/api/v1/reference-data/geographic-units/"
            f"?level={field.name}&status=active&page_size=500"
        )
    constraints = _constraints_for(field)
    if constraints:
        out["constraints"] = constraints
    return out


@lru_cache(maxsize=1)
def categories() -> list[dict]:
    built = []
    for section in CATALOG_MODELS:
        fields = [_serialise_model_field(section, f) for f in _editable_fields(section["model"])]
        if not fields:
            continue
        built.append({
            "key": section["key"],
            "label": section["label"],
            "tone": section["tone"],
            "model": section["model"]._meta.label,
            "entity": section["entity"],
            "questionnaire_section": QUESTIONNAIRE_SECTIONS.get(section["key"], ""),
            "fields": fields,
        })
    return built


def category_keys() -> set[str]:
    return {c["key"] for c in categories()}


def field_keys_by_category() -> dict[str, set[str]]:
    return {c["key"]: {f["key"] for f in c["fields"]} for c in categories()}


def field_meta(category: str, field: str) -> dict | None:
    for c in categories():
        if c["key"] != category:
            continue
        for f in c["fields"]:
            if f["key"] == field:
                return f
    return None


def is_pmt_relevant(category: str, field: str) -> bool:
    return bool((field_meta(category, field) or {}).get("pmt", False))


def validate_row(category: str, field: str) -> None:
    pairs = field_keys_by_category()
    if category not in pairs:
        raise ValueError(f"unknown category {category!r}")
    if field not in pairs[category]:
        raise ValueError(f"unknown field {field!r} for category {category!r}")


def field_entity(category: str, field: str) -> str:
    return (field_meta(category, field) or {}).get("entity", "household")


def member_field_pairs() -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for c in categories():
        for f in c["fields"]:
            if f.get("entity") == "member":
                out.add((c["key"], f["key"]))
    return out


# Backwards-compatible public name used by api/tests. It is backend-owned
# and generated from model metadata, not copied from JSX.
CATEGORIES = categories()
