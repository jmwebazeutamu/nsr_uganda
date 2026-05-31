"""INT models — Submission and FormVersion.

Sprint 2 scope: enough to make Web on-demand intake (US-005, US-006) and
the CAPI submission contract real. The CAPI runtime decision (ADR-0004)
remains open — this module is intentionally runtime-agnostic on the
client side.

References:
- SAD §4.1, §5.1 Submission and FormVersion
- SAD §11.1 MVP Release 1 INT scope
- ADR-0002 (Submission.id is ULID — externally referenced)
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


class Channel(models.TextChoices):
    CAPI = "capi"
    WEB = "web"
    USSD = "ussd"
    BULK = "bulk"
    PARTNER_MIS = "partner_mis"


class SubmissionResult(models.TextChoices):
    COMPLETED = "completed"
    REFUSED = "refused"
    NOT_AT_HOME = "not_at_home"
    PARTIAL = "partial"
    OTHER = "other"
    # US-CONSENT-03 — registration consent refused at intake; the submission is
    # recorded but never promoted (no registry Household/Member is created).
    DECLINED_CONSENT = "declined_consent"


class SubmissionState(models.TextChoices):
    PENDING_QA = "pending_qa"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class FormStatus(models.TextChoices):
    """Lifecycle states for FormVersion (US-117 — same dual-approval
    pattern as DqaRule / ChoiceList). is_active is kept as the
    legacy boolean for backward compat; status is the source of
    truth going forward."""

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    RETIRED = "retired"
    REJECTED = "rejected"


class FormVersion(models.Model):
    """Versioned questionnaire definition. Sprint 2 stored a JSON
    schema blob; Sprint 19 (US-117) adds first-class FormSection /
    FormQuestion / FormSkipLogic / FormConstraint children so the
    questionnaire is editable, not just rendered from JSON. The
    `schema` JSONField is now the OUTPUT (XLSForm export) — when
    children exist they're the source of truth, schema is recomputed."""

    id = ULIDField(primary_key=True)
    version = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    schema = models.JSONField(default=dict)
    is_active = models.BooleanField(default=False)

    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    # US-117 lifecycle fields — mirror DqaRule/ChoiceList.
    status = models.CharField(
        max_length=24, choices=FormStatus.choices,
        default=FormStatus.DRAFT,
    )
    author = models.CharField(max_length=64, blank=True)
    approved_by = models.CharField(max_length=64, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approval_note = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)

    # When this FormVersion has been pushed up to Kobo, the upstream
    # asset uid lives here. Re-publishing routes through the same
    # uid so the form's submission history stays attached (Kobo
    # creates a new VERSION of the same asset rather than a new
    # asset). Empty when never published, or when the publish is
    # for a different Kobo instance.
    kobo_asset_uid = models.CharField(max_length=32, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Form version"
        indexes = [
            models.Index(fields=["is_active", "effective_from"]),
            models.Index(fields=["status", "version"]),
        ]

    def __str__(self) -> str:
        return f"FormVersion {self.name} v{self.version}"


class QuestionType(models.TextChoices):
    """XLSForm-compatible question types (US-117). Mirrors the type
    column in the legacy XLSForm script so an export round-trip is
    lossless. begin_/end_ pairs are structural — they don't carry a
    value, just demarcate groups + repeats."""

    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    TIME = "time"
    DATETIME = "dateTime"
    SELECT_ONE = "select_one"
    SELECT_MULTIPLE = "select_multiple"
    GEOPOINT = "geopoint"
    GEOTRACE = "geotrace"
    GEOSHAPE = "geoshape"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    BARCODE = "barcode"
    CALCULATE = "calculate"
    NOTE = "note"
    ACKNOWLEDGE = "acknowledge"
    HIDDEN = "hidden"
    RANGE = "range"
    RANK = "rank"
    # XLSForm metadata types — the legacy script emits these at the
    # top of the survey sheet. Stored on a "_meta" FormSection so the
    # round-trip is lossless; the exporter ALSO auto-prepends them at
    # render time if absent, so fresh-authored forms are still valid.
    START = "start"
    END = "end"
    TODAY = "today"
    DEVICEID = "deviceid"
    USERNAME = "username"
    PHONENUMBER = "phonenumber"
    BEGIN_REPEAT = "begin_repeat"
    END_REPEAT = "end_repeat"
    BEGIN_GROUP = "begin_group"
    END_GROUP = "end_group"


class FormSection(models.Model):
    """Top-level section of a FormVersion (US-117).

    Sections match the questionnaire's letter-coded blocks: A
    Identification, B Survey status, C Roster, D Health, etc. `code`
    is the legacy letter (`A`, `B`, …); `name` is the snake_case
    handle the XLSForm export uses; `label` is the operator-facing
    title."""

    id = ULIDField(primary_key=True)
    form_version = models.ForeignKey(
        FormVersion, on_delete=models.CASCADE, related_name="sections",
    )
    code = models.CharField(max_length=16)
    name = models.CharField(max_length=64)
    label = models.CharField(max_length=256)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    # When non-empty, the section is exported as a begin_repeat /
    # end_repeat block (with this value in the repeat_count column).
    # When empty (default), the section is a begin_group / end_group
    # wrapper. XLSForm allows the value to be a static integer or an
    # XPath reference (e.g. "${hh_size}"); stored verbatim.
    repeat_count = models.CharField(max_length=64, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Form section"
        constraints = [
            models.UniqueConstraint(
                fields=["form_version", "code"],
                name="formsection_unique_per_version",
            ),
            models.UniqueConstraint(
                fields=["form_version", "name"],
                name="formsection_name_unique_per_version",
            ),
        ]
        ordering = ("form_version", "order", "code")

    def __str__(self) -> str:
        return f"{self.form_version.name} v{self.form_version.version} {self.code}: {self.label}"


class FormQuestion(models.Model):
    """One question within a section (US-117).

    `name` is snake_case (the XLSForm `name` column); the
    questionnaire stores responses against this key. `label` is the
    operator/respondent-facing prompt. `type` follows QuestionType
    (XLSForm-compatible). `choice_list_ref` is required when type
    is select_one / select_multiple — references the ChoiceList
    catalogue authored in US-116.

    `relevant_expression` (skip-logic) and `constraint_expression`
    (value validation) accept XLSForm-style XPath strings; the JSON-
    DSL twin used by the DQA engine (apps.dqa.engine) is stored on
    FormSkipLogic / FormConstraint when richer authoring is needed."""

    id = ULIDField(primary_key=True)
    section = models.ForeignKey(
        FormSection, on_delete=models.CASCADE, related_name="questions",
    )
    name = models.CharField(max_length=64)
    label = models.CharField(max_length=512)
    hint = models.CharField(max_length=512, blank=True)
    type = models.CharField(max_length=24, choices=QuestionType.choices)
    choice_list_ref = models.ForeignKey(
        "reference_data.ChoiceList",
        on_delete=models.PROTECT, null=True, blank=True,
        related_name="referenced_by_questions",
    )
    required = models.BooleanField(default=False)
    relevant_expression = models.CharField(max_length=512, blank=True)
    constraint_expression = models.CharField(max_length=512, blank=True)
    constraint_message = models.CharField(max_length=256, blank=True)
    appearance = models.CharField(max_length=64, blank=True)
    repeat_count = models.CharField(max_length=64, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    # XLSForm `calculation` cell. Required for type='calculate'; for
    # every other type it's typically blank but XLSForm allows a
    # calculation to ride on a regular field too (the engine evaluates
    # it on every recompute). Kobo rejects calculate rows without a
    # non-empty calculation — see US-S21-006.
    calculation = models.CharField(max_length=512, blank=True)
    order_in_section = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Form question"
        constraints = [
            # name must be unique within a FormVersion (not just a
            # section) because XLSForm uses it as a global response
            # key. The join goes via section.form_version.
            models.UniqueConstraint(
                fields=["section", "name"],
                name="formquestion_name_unique_per_section",
            ),
        ]
        ordering = ("section", "order_in_section", "name")

    def __str__(self) -> str:
        return f"{self.section.code}.{self.name} ({self.type})"


class FormSkipLogic(models.Model):
    """Structured skip-logic record (US-117).

    A FormQuestion can carry a raw `relevant_expression` (XPath
    string for XLSForm export) and / or an entry here with a richer
    JSON-DSL twin the DQA engine can evaluate in-process. The XPath
    is the export format; the DSL is the source of truth when
    authored through the Rule Editor UI (US-117b)."""

    id = ULIDField(primary_key=True)
    question = models.ForeignKey(
        FormQuestion, on_delete=models.CASCADE, related_name="skip_logic",
    )
    dsl = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Form skip-logic"
        verbose_name_plural = "Form skip-logic"

    def __str__(self) -> str:
        return f"skip_logic for {self.question.name}"


class FormConstraint(models.Model):
    """Structured constraint record (US-117). Mirrors FormSkipLogic;
    captures the JSON-DSL twin of an XLSForm `constraint` so the
    DQA engine can evaluate it server-side without re-parsing
    XPath."""

    id = ULIDField(primary_key=True)
    question = models.ForeignKey(
        FormQuestion, on_delete=models.CASCADE, related_name="constraints",
    )
    dsl = models.JSONField(default=dict, blank=True)
    message = models.CharField(max_length=256, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Form constraint"

    def __str__(self) -> str:
        return f"constraint on {self.question.name}"


class Submission(models.Model):
    """Single intake event. One Submission ↔ one DIH StageRecord ↔
    (after promotion) one Household. ULID id per ADR-0002 with channel
    prefix in display per SAD §5.2."""

    id = ULIDField(primary_key=True)

    channel = models.CharField(max_length=16, choices=Channel.choices)
    form_version = models.ForeignKey(
        FormVersion, on_delete=models.PROTECT, related_name="submissions",
    )

    # Enumerator / supervisor identifiers — strings for now, FKs once
    # the User catalogue from US-S2-002 (Keycloak) lands.
    enumerator = models.CharField(max_length=64)
    supervisor = models.CharField(max_length=64, blank=True)

    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_accuracy_m = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    result = models.CharField(max_length=24, choices=SubmissionResult.choices)
    state = models.CharField(
        max_length=24, choices=SubmissionState.choices, default=SubmissionState.PENDING_QA,
    )

    # Pointer to the DIH side of the pipeline. Populated by
    # apps.intake.services.submit_intake immediately on submission.
    stage_record_id = models.CharField(max_length=26, blank=True, db_index=True)
    provisional_registry_id = models.CharField(max_length=26, blank=True, db_index=True)

    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Submission"
        indexes = [
            models.Index(fields=["channel", "-created_at"]),
            models.Index(fields=["state"]),
            models.Index(fields=["enumerator"]),
        ]

    def __str__(self) -> str:
        return f"Submission {self.id} [{self.channel}/{self.state}]"
