"""MetadataCatalog — read-side wrapper that scopes the catalogue to
the requesting user and adds the in-memory cache the NFR target
(catalogue browse P95 < 500 ms) needs.

The cache lives at module scope and is invalidated by
metadata_loader.refresh() — it bumps the version counter so the next
read repopulates.

ABAC scoping uses apps.security.abac.scope_q_for_field on the
Dataset.sub_region_code column. Datasets without a sub-region tag are
nationally visible (the common case).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from django.db.models import Q

from apps.security.abac import scope_q_for_field


@dataclass(frozen=True)
class CachedCatalogue:
    version: int
    datasets: tuple
    variables: tuple


class MetadataCatalog:
    _lock = threading.Lock()
    _cache: CachedCatalogue | None = None
    _version = 0

    @classmethod
    def bump_version(cls) -> None:
        with cls._lock:
            cls._version += 1
            cls._cache = None

    @classmethod
    def _populate(cls) -> CachedCatalogue:
        # Lazy import to avoid circular import at startup.
        from .models import Dataset, Variable
        with cls._lock:
            if cls._cache and cls._cache.version == cls._version:
                return cls._cache
            datasets = tuple(
                Dataset.objects.select_related(
                    "privacy_class", "refresh_cadence",
                ).all().order_by("code")
            )
            variables = tuple(
                Variable.objects.select_related(
                    "privacy_class", "dataset",
                ).all().order_by("dataset__code", "code")
            )
            cls._cache = CachedCatalogue(
                version=cls._version,
                datasets=datasets,
                variables=variables,
            )
            return cls._cache

    @classmethod
    def list_datasets(cls, user=None):
        cached = cls._populate()
        if user is None:
            return list(cached.datasets)
        q = scope_q_for_field(user, "sub_region_code")
        # Dataset.sub_region_code may be empty → nationally visible.
        from .models import Dataset
        return list(
            Dataset.objects
            .filter(Q(sub_region_code="") | q)
            .select_related("privacy_class", "refresh_cadence")
            .order_by("code")
        )

    @classmethod
    def list_variables(cls, *, dataset_code: str | None = None,
                       include_inactive: bool = False,
                       privacy_class: str | None = None,
                       q: str | None = None,
                       has_completeness_baseline: bool | None = None):
        from .models import Variable, VariableStatus
        qs = Variable.objects.select_related(
            "dataset", "privacy_class",
        )
        if dataset_code:
            qs = qs.filter(dataset__code=dataset_code)
        if not include_inactive:
            qs = qs.filter(status=VariableStatus.ACTIVE)
        if privacy_class:
            qs = qs.filter(privacy_class__code=privacy_class)
        if has_completeness_baseline is not None:
            qs = qs.filter(has_completeness_baseline=has_completeness_baseline)
        if q:
            qs = qs.filter(
                Q(label__icontains=q)
                | Q(code__icontains=q)
                | Q(description__icontains=q),
            )
        return list(qs.order_by("dataset__code", "code"))

    @classmethod
    def get_dataset(cls, dataset_id: str):
        from .models import Dataset
        return (
            Dataset.objects
            .select_related("privacy_class", "refresh_cadence")
            .filter(id=dataset_id)
            .first()
        )

    @classmethod
    def get_variable(cls, variable_id: str):
        from .models import Variable
        return (
            Variable.objects
            .select_related("dataset", "privacy_class")
            .filter(id=variable_id)
            .first()
        )

    @classmethod
    def list_privacy_classes(cls):
        from .models import PrivacyClass
        return list(PrivacyClass.objects.all().order_by("k_floor"))


def invalidate() -> None:
    """Public hook called by metadata_loader.refresh() at the end of
    every successful upsert pass."""
    MetadataCatalog.bump_version()
