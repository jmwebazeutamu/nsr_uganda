"""REF-DATA models.

Sprint 0 scope: GeographicUnit. Sprint 19 / US-116 adds ChoiceList +
ChoiceOption as the system-owned home for questionnaire code-lists
(income source, education level, disability type, shock type, etc.).

References:
- SAD §5.1 (GeographicUnit), §5.4 (Reference data versioning)
- ADR-0002 (internal BIGINT pk; codes are external but UBOS-owned)
- docs/stories/US-116-120_questionnaire_authoring.md (US-116 spec)
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


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
    # 48, not 32: village codes carry a dotted hierarchy + suffix and run to
    # 33 chars in the UBOS frame (SQLite silently truncated; Postgres rejects).
    code = models.CharField(max_length=48)
    name = models.CharField(max_length=128)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    # Denormalised counters maintained by the post-save signal /
    # nightly recompute task. Reading these is O(1) for the drill
    # endpoint, instead of N+1 counts per row.
    children_count_cached = models.PositiveIntegerField(default=0)
    households_count_cached = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["level", "code", "effective_from"], name="geounit_code_per_level_per_version"
            ),
            # Partial unique: at most one ACTIVE row per (level, code).
            # The default `geounit_code_per_level_per_version`
            # constraint already prevents collisions on
            # effective_from; this constraint adds the active-row
            # invariant relied on by replace_geographic_unit().
            models.UniqueConstraint(
                fields=["level", "code"],
                condition=models.Q(status="active"),
                name="geounit_one_active_per_code",
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

    # US-REF-026 / Audit 2026-05-21 §2 — bulk administrative
    # walks ("all households in this sub-region") had to climb
    # the FK chain ad-hoc. These helpers give a single canonical
    # entry point that returns a queryset suitable for chaining.
    #
    # The hierarchy is bounded at 7 levels (region → village), so
    # the iterative walk fires at most 7 queries. We deliberately
    # avoid a recursive CTE here to keep the implementation
    # backend-portable (SQLite + PostgreSQL) and to keep this app
    # free of raw SQL (CLAUDE.md: "No raw SQL outside
    # data_management and ingestion_hub").
    def get_descendants(self, *, include_self: bool = False):
        """Queryset of every GeographicUnit below self in the tree,
        regardless of depth. Returns a deterministic order
        (level then code). `include_self=True` prepends self."""
        ids: list = [self.id] if include_self else []
        current = [self.id]
        while current:
            children = list(
                GeographicUnit.objects
                .filter(parent_id__in=current)
                .values_list("id", flat=True),
            )
            if not children:
                break
            ids.extend(children)
            current = children
        return (
            GeographicUnit.objects
            .filter(id__in=ids)
            .order_by("level", "code")
        )

    def get_ancestors(self, *, include_self: bool = False):
        """Queryset of every GeographicUnit above self in the tree,
        ordered top-down (region first, immediate parent last)."""
        ids: list = [self.id] if include_self else []
        cur_parent_id = self.parent_id
        # Bounded at 7 levels; one query per step keeps the
        # implementation portable and easy to reason about.
        while cur_parent_id:
            ids.append(cur_parent_id)
            next_id = (
                GeographicUnit.objects
                .filter(id=cur_parent_id)
                .values_list("parent_id", flat=True)
                .first()
            )
            cur_parent_id = next_id
        return (
            GeographicUnit.objects
            .filter(id__in=ids)
            .order_by("level", "code")
        )


class ChoiceListStatus(models.TextChoices):
    """Lifecycle states for ChoiceList — mirror DqaRule (DAT-DQA pattern).

    DRAFT and PENDING_APPROVAL allow edits; once ACTIVE the list is
    immutable from the UI (option-level changes go through a new
    ChoiceList version). RETIRED keeps the list readable for
    historical records but disables it as a selectable list at
    intake time.
    """

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    RETIRED = "retired"
    REJECTED = "rejected"


class ChoiceList(models.Model):
    """One versioned code-list (US-116).

    `list_name` is the logical identifier (snake_case, stable across
    versions — e.g. `relationship`, `marital_status`). `version`
    increments on each approved revision; the (list_name, version)
    pair is unique. `effective_from`/`effective_to` plus `status`
    select which row is in force for an intake date.

    Audit fields mirror DqaRule: author + approved_by + approved_at
    with the author-cannot-approve constraint enforced at the
    service layer.
    """

    id = ULIDField(primary_key=True)
    list_name = models.CharField(max_length=64, db_index=True)
    version = models.PositiveIntegerField(default=1)
    description = models.TextField(blank=True)

    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=24, choices=ChoiceListStatus.choices,
        default=ChoiceListStatus.DRAFT,
    )
    author = models.CharField(max_length=64)
    approved_by = models.CharField(max_length=64, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approval_note = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)

    # When true, codes from this list are PII (e.g. disability_type)
    # and labels must be redacted in audit exports unless the caller
    # has a DPO scope. Surfaced in the admin console list view.
    is_pii_classified = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["list_name", "version"],
                name="choicelist_name_version_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "list_name"]),
        ]
        verbose_name = "Choice list"
        verbose_name_plural = "Choice lists"

    def __str__(self) -> str:
        return f"{self.list_name} v{self.version} [{self.status}]"


class ChoiceOption(models.Model):
    """One option within a ChoiceList version.

    `code` is what the questionnaire stores ("01", "11", "1") —
    chosen to match the legacy XLSForm `name` values so existing
    intake payloads keep working. `label` is the operator/respondent-
    facing display string. `parent_code` is set when the list is
    cascading (e.g. district → county); empty otherwise.

    Deprecation: a ChoiceOption can be `deprecated` (still readable
    for historical records but not selectable on new intakes). True
    deletion is intentionally not supported — past responses must
    remain interpretable.
    """

    class Status(models.TextChoices):
        ACTIVE = "active"
        DEPRECATED = "deprecated"

    id = ULIDField(primary_key=True)
    choice_list = models.ForeignKey(
        ChoiceList, on_delete=models.CASCADE, related_name="options",
    )
    code = models.CharField(max_length=32)
    label = models.CharField(max_length=256)
    language = models.CharField(max_length=8, default="en")
    parent_code = models.CharField(max_length=32, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # Same code can't appear twice within a single list
            # version for the same language. Different languages of
            # the same option live as separate rows with the same
            # code; the loader pairs them by (list, code).
            models.UniqueConstraint(
                fields=["choice_list", "code", "language"],
                name="choiceoption_unique_per_list_lang",
            ),
        ]
        indexes = [
            models.Index(fields=["choice_list", "status"]),
            models.Index(fields=["parent_code"]),
        ]
        ordering = ("choice_list", "sort_order", "code")
        verbose_name = "Choice option"
        verbose_name_plural = "Choice options"

    def __str__(self) -> str:
        return f"{self.choice_list.list_name}:{self.code} {self.label}"
