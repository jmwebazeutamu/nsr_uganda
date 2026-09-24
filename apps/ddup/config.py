"""Canonical DDUP model-configuration contract.

``DdupModelVersion.config`` is the sole persisted configuration for matching.
This module validates that it references the Questionnaire Authoring field
dictionary or the registry's declared system-derived fields.  It deliberately
contains no scoring defaults, weights, thresholds, or fallback field lists.
An incomplete active version is unusable rather than silently changing how
people are matched.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.data_management.models import Household, Member
from apps.intake.canonical_fields import DERIVED_FIELD_TRANSFORMS
from apps.intake.field_dictionary import build_field_dictionary


class DdupConfigurationError(ValueError):
    """A DDUP model cannot be used until its registry contract is complete."""


@dataclass(frozen=True)
class DdupConfiguration:
    schema: str
    tiers: dict[str, dict]


def registered_field_references() -> set[str]:
    """Return fields a DDUP model may name, from canonical contracts only."""
    dictionary = build_field_dictionary()
    refs = set(dictionary.fields)
    refs.update(DERIVED_FIELD_TRANSFORMS)
    refs.update(field.name for field in Member._meta.fields)
    refs.update(f"member.{field.name}" for field in Member._meta.fields)
    refs.update(f"household.{field.name}" for field in Household._meta.fields)
    return refs


def validate_ddup_configuration(config: object) -> DdupConfiguration:
    """Validate a draft/active DDUP model without supplying any values.

    The approved model provides every enabled tier's fields, methods, weights
    and thresholds.  This prevents a code release from altering matching
    policy when configuration is omitted.
    """
    if not isinstance(config, dict):
        raise DdupConfigurationError("DDUP configuration must be an object")
    schema = config.get("schema")
    if not isinstance(schema, str) or not schema:
        raise DdupConfigurationError("DDUP configuration requires a schema reference")
    tiers = config.get("tiers")
    if not isinstance(tiers, dict) or not tiers:
        raise DdupConfigurationError("DDUP configuration requires configured tiers")

    available = registered_field_references()
    validated: dict[str, dict] = {}
    for tier_id, tier in tiers.items():
        if not isinstance(tier_id, str) or not isinstance(tier, dict):
            raise DdupConfigurationError("each DDUP tier must be an object")
        if not isinstance(tier.get("enabled"), bool):
            raise DdupConfigurationError(f"tier {tier_id} requires enabled=true or false")
        if not tier["enabled"]:
            validated[tier_id] = tier
            continue
        fields = tier.get("fields")
        if not isinstance(fields, list) or not fields:
            raise DdupConfigurationError(f"enabled tier {tier_id} requires fields")
        unknown = [field for field in fields if field not in available]
        if unknown:
            raise DdupConfigurationError(
                f"tier {tier_id} references fields absent from the canonical registry: {unknown}",
            )
        method = tier.get("method")
        if not isinstance(method, str) or not method:
            raise DdupConfigurationError(f"enabled tier {tier_id} requires method")
        if method == "exact_hash":
            if not isinstance(tier.get("candidate_score"), (int, float)):
                raise DdupConfigurationError(
                    f"exact-hash tier {tier_id} requires candidate_score",
                )
            if not isinstance(tier.get("match_reason"), str) or not tier["match_reason"]:
                raise DdupConfigurationError(
                    f"exact-hash tier {tier_id} requires match_reason",
                )
        # Scores are policy, never fallbacks.  Exact-match tiers may use a
        # configured score; probabilistic tiers must provide the full model.
        if method == "weighted_similarity":
            features = tier.get("features")
            threshold = tier.get("review_threshold")
            block_field = tier.get("block_field")
            if not isinstance(features, list) or not features:
                raise DdupConfigurationError(
                    f"weighted tier {tier_id} requires features from the model config",
                )
            if not isinstance(threshold, (int, float)):
                raise DdupConfigurationError(
                    f"weighted tier {tier_id} requires review_threshold",
                )
            if block_field not in available:
                raise DdupConfigurationError(
                    f"weighted tier {tier_id} requires a registered block_field",
                )
            for feature in features:
                if not isinstance(feature, dict) or feature.get("field") not in available:
                    raise DdupConfigurationError(
                        f"weighted tier {tier_id} has an unregistered feature field",
                    )
                if not isinstance(feature.get("weight"), (int, float)):
                    raise DdupConfigurationError(
                        f"weighted tier {tier_id} feature requires weight",
                    )
                if not isinstance(feature.get("comparator"), str):
                    raise DdupConfigurationError(
                        f"weighted tier {tier_id} feature requires comparator",
                    )
        validated[tier_id] = tier
    return DdupConfiguration(schema=schema, tiers=validated)
