"""Model artifacts: checksum, vocabulary validation and the two scorers.

ADR-0045 D3 and D8. An artifact is plain JSON stored in the approved
AiModelVersion row. There is no pickle and no file path, so loading a model
cannot execute code.

D8: the vocabulary a model speaks is owned by the module it serves. A DDUP
ranker may only name features the active tier 3 config produces; a DQA
anomaly model may only name paths the DQA payload producer emits. Both are
read from the real producers here, never copied, because a name the
producer does not emit would score as a silent zero (the failure recorded
in the two-vocabularies note).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from types import SimpleNamespace

from .models import FeatureCode

AGGREGATIONS = ("value", "count", "max", "min", "mean")


class ArtifactError(ValueError):
    """The artifact is malformed or names something its producer does not."""


class ScoringError(ValueError):
    """The input cannot be scored (a named feature is absent)."""


def canonical_json(artifact: dict) -> str:
    return json.dumps(artifact, sort_keys=True, separators=(",", ":"), allow_nan=False)


def checksum(artifact: dict) -> str:
    return hashlib.sha256(canonical_json(artifact).encode("utf-8")).hexdigest()


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# --- vocabularies, read from the producers ---------------------------------


def ddup_feature_vocabulary() -> set[str]:
    """Feature names a DDUP pair carries: the active tier 3 config's fields,
    which are the keys of MatchPair.per_field_scores."""
    from apps.ddup.config import validate_ddup_configuration
    from apps.ddup.models import DdupModelVersion, ModelStatus

    active = DdupModelVersion.objects.filter(status=ModelStatus.ACTIVE).first()
    if active is None:
        raise ArtifactError("no active DDUP model version to validate feature names against")
    tier = validate_ddup_configuration(active.config).tiers.get("tier3") or {}
    names = {f["field"] for f in tier.get("features", [])}
    if not names:
        raise ArtifactError("the active DDUP model has no tier 3 features")
    return names


def dqa_payload_vocabulary() -> tuple[set[str], set[str]]:
    """(top-level keys, member keys) the DQA payload producer emits.

    Derived by running the real producer over a stub, not by listing keys
    here: the producer getattr()s every field with a None default, so the
    keys it emits are exactly the keys it knows.
    """
    from apps.dqa.pipeline import household_to_dqa_payload

    member = SimpleNamespace(id="x")
    household = SimpleNamespace(id="x", members=SimpleNamespace(all=lambda: [member]))
    payload = household_to_dqa_payload(household)
    return set(payload) - {"members"}, set(payload["members"][0])


# --- validation ------------------------------------------------------------


def validate_artifact(task: str, artifact: dict) -> None:
    if task == FeatureCode.DDUP_RANK:
        _validate_linear(artifact)
    elif task == FeatureCode.DQA_ANOMALY:
        _validate_robust_z(artifact)
    else:
        raise ArtifactError(f"unknown task {task!r}")


def _validate_linear(a: dict) -> None:
    if a.get("kind") != "linear":
        raise ArtifactError("ddup.rank requires kind=linear")
    features, weights = a.get("features"), a.get("weights")
    if not features or not isinstance(features, list) or len(features) != len(weights or []):
        raise ArtifactError("features and weights must be non-empty lists of equal length")
    if len(set(features)) != len(features):
        raise ArtifactError("duplicate feature names")
    if not all(_finite(w) for w in weights) or not _finite(a.get("intercept")):
        raise ArtifactError("weights and intercept must be finite numbers")
    unknown = sorted(set(features) - ddup_feature_vocabulary())
    if unknown:
        raise ArtifactError(f"features not carried by DDUP pairs: {unknown}")


def _validate_robust_z(a: dict) -> None:
    if a.get("kind") != "robust_z":
        raise ArtifactError("dqa.anomaly requires kind=robust_z")
    if not _finite(a.get("threshold")) or a["threshold"] <= 0:
        raise ArtifactError("threshold must be a positive number")
    feats = a.get("features")
    if not feats or not isinstance(feats, list):
        raise ArtifactError("features must be a non-empty list")
    top, member = dqa_payload_vocabulary()
    names = set()
    for f in feats:
        name, path, agg = f.get("name"), f.get("path", ""), f.get("agg")
        if not name or name in names:
            raise ArtifactError(f"feature name missing or duplicated: {name!r}")
        names.add(name)
        if agg not in AGGREGATIONS:
            raise ArtifactError(f"{name}: agg must be one of {AGGREGATIONS}")
        parts = path.split(".")
        if len(parts) == 3 and parts[0] == "members" and parts[1] == "*":
            ok = parts[2] in member and parts[2] != "id"
            if agg == "value":
                raise ArtifactError(f"{name}: a member path needs an aggregation")
        elif len(parts) == 1:
            ok = parts[0] in top
            if agg != "value":
                raise ArtifactError(f"{name}: a scalar path uses agg=value")
        else:
            ok = False
        if not ok:
            raise ArtifactError(f"{name}: path {path!r} is not in the DQA payload")
        if not _finite(f.get("median")) or not _finite(f.get("mad")) or f["mad"] <= 0:
            raise ArtifactError(f"{name}: median must be finite and mad positive")


# --- scorers ---------------------------------------------------------------


@dataclass(frozen=True)
class LinearScorer:
    features: tuple[str, ...]
    weights: tuple[float, ...]
    intercept: float

    @classmethod
    def from_artifact(cls, a: dict) -> LinearScorer:
        return cls(tuple(a["features"]), tuple(float(w) for w in a["weights"]), float(a["intercept"]))

    def score(self, values: dict) -> tuple[float, dict]:
        """Probability-like score in (0, 1) plus per-feature contributions.

        A missing feature raises. Scoring it as zero would be the silent
        wrong answer this module exists to avoid.
        """
        total = self.intercept
        contributions = {}
        for name, w in zip(self.features, self.weights, strict=True):
            if values.get(name) is None:
                raise ScoringError(f"feature {name!r} absent")
            c = w * float(values[name])
            contributions[name] = round(c, 6)
            total += c
        return 1.0 / (1.0 + math.exp(-total)), contributions


def _aggregate(payload: dict, path: str, agg: str):
    parts = path.split(".")
    if len(parts) == 1:
        v = payload.get(parts[0])
        return float(v) if _finite(v) else None
    vals = [m.get(parts[2]) for m in payload.get("members") or []]
    vals = [float(v) for v in vals if _finite(v)]
    if agg == "count":
        return float(len(vals))
    if not vals:
        return None
    return {"max": max(vals), "min": min(vals), "mean": sum(vals) / len(vals)}[agg]


@dataclass(frozen=True)
class RobustZScorer:
    threshold: float
    features: tuple[dict, ...]

    @classmethod
    def from_artifact(cls, a: dict) -> RobustZScorer:
        return cls(float(a["threshold"]), tuple(a["features"]))

    def score(self, payload: dict) -> tuple[float, dict] | None:
        """Largest absolute robust z across features, plus each feature's z.

        0.6745 is the constant that makes MAD comparable to a standard
        deviation under normality; it is a property of the statistic, not
        a tunable. Features absent from the payload are skipped; if none
        can be computed the household is unscorable (None).
        """
        zs = {}
        for f in self.features:
            v = _aggregate(payload, f["path"], f["agg"])
            if v is None:
                continue
            zs[f["name"]] = round(0.6745 * (v - f["median"]) / f["mad"], 4)
        if not zs:
            return None
        return max(abs(z) for z in zs.values()), zs
