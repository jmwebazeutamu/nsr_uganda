"""REF-DATA models.

Sprint 0 scope: GeographicUnit only. Choice-list, FormVersion, PMTModelVersion
land in later stories.

References:
- SAD §5.1 (GeographicUnit), §5.4 (Reference data versioning)
- ADR-0002 (internal BIGINT pk; codes are external but UBOS-owned)
"""

from __future__ import annotations

from django.db import models


class GeographicUnit(models.Model):
    """UBOS administrative hierarchy, versioned for splits and 2026 review."""

    class Level(models.TextChoices):
        REGION = "region"
        SUB_REGION = "sub_region"
        DISTRICT = "district"
        COUNTY = "county"
        SUB_COUNTY = "sub_county"
        PARISH = "parish"
        VILLAGE = "village"

    class Status(models.TextChoices):
        ACTIVE = "active"
        SUPERSEDED = "superseded"
        RETIRED = "retired"

    level = models.CharField(max_length=16, choices=Level.choices)
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=128)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["level", "code", "effective_from"], name="geounit_code_per_level_per_version"
            ),
        ]
        indexes = [
            models.Index(fields=["level", "status"]),
            models.Index(fields=["parent"]),
        ]
        verbose_name = "Geographic unit"
        verbose_name_plural = "Geographic units"

    def __str__(self) -> str:
        return f"{self.get_level_display()}:{self.code} {self.name}"
