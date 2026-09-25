"""GRM models — grievance case with 4-tier escalation.

Sprint 2 scope: L1 (Parish Chief) and L2 (CDO) intake + manual
escalation to L3 (District) and L4 (NSR Unit) per SAD §11.1 MVP. The
GRM ↔ UPD linkage (a grievance that resolves to a data correction
opens a linked UPD ChangeRequest) is modelled via linked_change_request_id;
the workflow that auto-opens the UPD is a Sprint 2.5 follow-up.

References:
- SAD §5.1 Grievance entity, §11.1 MVP scope
- ADR-0002 (Grievance.id is ULID — citizen-facing reference code)
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import ULIDField


class Category(models.TextChoices):
    DATA_CORRECTION = "data_correction"
    EXCLUSION_ERROR = "exclusion_error"
    INCLUSION_ERROR = "inclusion_error"
    PROGRAMME_ISSUE = "programme_issue"
    OPERATOR_CONDUCT = "operator_conduct"
    OTHER = "other"


class Tier(models.TextChoices):
    L1_PARISH_CHIEF = "l1_parish_chief"
    L2_CDO = "l2_cdo"
    L3_DISTRICT = "l3_district"
    L4_NSR_UNIT = "l4_nsr_unit"


class GrievanceStatus(models.TextChoices):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"


#: The statuses that mean the case is still somebody's work.
#:
#: Three places counted this and each spelled it out for itself: the
#: dashboard tile excluded RESOLVED and CLOSED, the workbench title
#: chip filtered the rows it had in the browser, and the sidebar badge
#: fetched 200 rows and filtered those. Three definitions of one idea,
#: and the badge's also capped at 200. This is the definition; adding a
#: sixth status is now one edit rather than a hunt.
ACTIVE_GRIEVANCE_STATUSES = (
    GrievanceStatus.OPEN,
    GrievanceStatus.IN_PROGRESS,
    GrievanceStatus.ESCALATED,
)


class TaskStatus(models.TextChoices):
    """US-S21-003 — GrievanceTask lifecycle. A task is a unit of
    follow-up work assigned to one operator. A grievance can carry
    many tasks (e.g., the L2 CDO assigns one to a parish chief and
    another to a partner liaison). The grievance can only be
    resolved when every task is CLOSED."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class GrmReferenceSequence(models.Model):
    """One row per year, holding the last case number issued.

    A running number needs somewhere to run from. `select_for_update`
    on this row serialises concurrent creates, and because the
    increment happens inside the creating transaction, a rollback
    releases the number rather than burning it — so the year's
    references stay contiguous, which is what makes them worth reading.

    Django's own sequences would be simpler and wrong: they are
    per-table, do not reset in January, and deliberately do not
    guarantee contiguity.
    """

    year = models.PositiveIntegerField(primary_key=True)
    last_number = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "GRM reference sequence"
        verbose_name_plural = "GRM reference sequences"
        ordering = ("-year",)

    def __str__(self) -> str:
        return f"{self.year}: {self.last_number} issued"


class Grievance(models.Model):
    id = ULIDField(primary_key=True)

    #: The case number people use — "GRM-2026-0001".
    #:
    #: The ULID above stays the key and stays in the URLs. It is simply
    #: not something a Parish Chief can read back to a citizen over the
    #: phone: 26 characters, no grouping, and nothing in the string to
    #: tell you when a character has been dropped.
    #:
    #: Blank only for a row mid-creation; assign() fills it in save().
    #: See apps/grievance/reference.py for why it is random rather than
    #: a running number.
    reference = models.CharField(max_length=16, unique=True, blank=True)

    category = models.CharField(max_length=32, choices=Category.choices)
    sub_category = models.CharField(max_length=64, blank=True)
    description = models.TextField()

    # Subject of the grievance. household_id is the citizen-facing
    # Registry ID; member_id (optional) points at a specific Member.
    household_id = models.CharField(max_length=26, blank=True, db_index=True)
    member_id = models.CharField(max_length=26, blank=True)

    # The household's geography, copied on create.
    #
    # Column names match Household's denormalised set exactly, because
    # apps.security.abac derives its level map from
    # Household.GEO_CODE_FIELDS — so `scope_q_for_field(user,
    # "sub_region_code")` filters a Grievance queryset with no special
    # case, and a district-scoped operator sees district grievances
    # without anyone writing a second scope rule.
    #
    # Blank when the grievance is not about a household (operator
    # conduct, a programme complaint). Those are visible to whoever can
    # see grievances at all, not to a geographic scope — a complaint
    # about an enumerator belongs to nobody's district.
    region_code = models.CharField(max_length=48, blank=True, db_index=True)
    sub_region_code = models.CharField(max_length=48, blank=True, db_index=True)
    district_code = models.CharField(max_length=48, blank=True, db_index=True)
    county_code = models.CharField(max_length=48, blank=True)
    sub_county_code = models.CharField(max_length=48, blank=True, db_index=True)
    parish_code = models.CharField(max_length=48, blank=True, db_index=True)
    village_code = models.CharField(max_length=48, blank=True)

    # Reporter — usually the head of household or a witness. Phone is
    # E.164 per AC-PHONE-FORMAT; full identification is optional.
    reporter_name = models.CharField(max_length=128, blank=True)
    reporter_phone = models.CharField(max_length=20, blank=True)
    reporter_relationship = models.CharField(max_length=32, blank=True)

    tier = models.CharField(max_length=24, choices=Tier.choices, default=Tier.L1_PARISH_CHIEF)
    status = models.CharField(
        max_length=24, choices=GrievanceStatus.choices, default=GrievanceStatus.OPEN,
    )

    # Assigned operator — string for now until Keycloak (US-S2-002) lands.
    assigned_to = models.CharField(max_length=64, blank=True)

    opened_at = models.DateTimeField(auto_now_add=True)

    # When the CURRENT tier's clock started.
    #
    # The SLA window was always measured from opened_at, so escalating
    # an already-breached L1 case produced an L2 deadline that was
    # itself already in the past — a tier that never had its own 48
    # hours. Each tier gets its window from the moment it receives the
    # case; null means the case is still at the tier it was opened at,
    # where opened_at is that moment.
    tier_started_at = models.DateTimeField(null=True, blank=True)
    sla_deadline = models.DateTimeField(null=True, blank=True)

    # Set by the SLA sweep when an L4 case breaches: there is no tier
    # above it to escalate to, so it is flagged for the NSR unit
    # instead of being escalated in a loop.
    sla_breach_flagged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    resolution_narrative = models.TextField(blank=True)
    # US-S21-005 — actor + narrative pair on each lifecycle close-out.
    # resolved_by + resolution_narrative explain WHY a grievance moved
    # to RESOLVED. closing_narrative + closed_by capture the same for
    # the CLOSED transition (the 30-day grace expiry, reporter
    # confirmation, etc.). All blank by default; populated by the
    # service-layer transitions only.
    resolved_by = models.CharField(max_length=64, blank=True)
    closing_narrative = models.TextField(blank=True)
    closed_by = models.CharField(max_length=64, blank=True)

    # GRM → UPD linkage. Populated when a grievance produces a data
    # correction. The actual auto-open workflow is a Sprint 2.5 story.
    linked_change_request_id = models.CharField(max_length=26, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Grievance"
        indexes = [
            models.Index(fields=["status", "tier"]),
            models.Index(fields=["category", "status"]),
            models.Index(fields=["sla_deadline"]),
        ]

    def save(self, *args, **kwargs):
        if not self.reference:
            from .reference import assign
            # Inside whatever transaction is writing this row, so the
            # select_for_update in assign() actually serialises and a
            # rollback gives the number back.
            self.reference = assign(self)
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = [*update_fields, "reference"]
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Grievance {self.reference or self.id} [{self.tier}/{self.status}]"


class CommentKind(models.TextChoices):
    """What put an entry on a grievance's thread.

    A plain NOTE is someone writing on the case. TASK_CLOSED is the
    note the closer had to give to close a task — it lives here rather
    than on GrievanceTask so the grievance has ONE timeline instead of
    a thread plus a set of closing notes filed somewhere else.
    """

    NOTE = "note"
    TASK_CLOSED = "task_closed"


class GrievanceComment(models.Model):
    """A dated note on a grievance, written as the case moves.

    A grievance used to carry no running record at all: the narrative
    captured at intake, then `resolution_narrative` at the end. Weeks of
    work in between — a visit made, a phone call, a document still
    missing — had nowhere to go, so the resolution had to summarise from
    memory, or not at all.

    Comments are append-only. There is no edit and no delete, because
    the value of the thread is that it says what was known at the time;
    a correction is another comment. That is also what keeps it
    consistent with the audit chain.
    """

    id = ULIDField(primary_key=True)
    grievance = models.ForeignKey(
        Grievance, on_delete=models.CASCADE, related_name="comments",
    )
    # Set when this entry is a task's closing note, so the thread can
    # show what it refers to.
    task = models.ForeignKey(
        "GrievanceTask", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="closing_comments",
    )
    kind = models.CharField(
        max_length=16, choices=CommentKind.choices, default=CommentKind.NOTE,
    )
    body = models.TextField()
    author = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Grievance comment"
        ordering = ("created_at",)
        indexes = [
            models.Index(fields=["grievance", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Comment on {self.grievance_id} by {self.author}"


class GrievanceTask(models.Model):
    """US-S21-003 — a unit of follow-up work attached to a grievance.

    Operators in the GRM Officer role create tasks and assign them to
    specific people; the assignee transitions the task open→in_progress
    →closed. A grievance can only be resolved when ALL its tasks are
    CLOSED — the service-layer guard in apps.grievance.services.resolve
    enforces this.
    """

    id = ULIDField(primary_key=True)
    grievance = models.ForeignKey(
        Grievance, on_delete=models.CASCADE, related_name="tasks",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    # Operator username the task is assigned to. String until the
    # Keycloak user catalogue (US-S2-002) lands.
    assigned_to = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=16, choices=TaskStatus.choices, default=TaskStatus.OPEN,
    )
    created_by = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name = "Grievance task"
        indexes = [
            models.Index(fields=["grievance", "status"]),
            models.Index(fields=["assigned_to", "status"]),
        ]
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"Task {self.id} on {self.grievance_id} [{self.status}]"


class GrmTierRule(models.Model):
    """Who owns a grievance at each tier, and for how long.

    Both halves of this were hardcoded, in two places. `SLA_BY_TIER` in
    services.py held 24/48/72/168 hours as a module constant, and the
    role that a tier belongs to existed only inside the Tier enum's own
    value strings — "l2_cdo" is a role name spelled into an identifier,
    which nothing could read as configuration.

    That mattered once assignment had to check it. Refusing to assign a
    case to someone whose role does not carry that tier is a policy
    decision; policy in a Python constant means rebalancing the ladder
    needs a deploy, and the operations team cannot see what the rule
    currently is. Same reasoning, and the same shape, as
    UpdRoutingRule (UPD-O-01).

    Seeded from SAD §5.1, which names the ladder: "tier (L1 Parish
    Chief / L2 CDO / L3 District / L4 NSR Unit)", with the role codes
    taken from the ADR-0028 catalogue in apps/security/roles.py. The
    SLA hours are the ones the service already used.

    There is no code fallback. An active row per tier is required, so a
    half-configured ladder fails loudly rather than quietly reverting
    to whatever a constant last said.
    """

    tier = models.CharField(max_length=24, choices=Tier.choices)
    #: Role code from apps.security.roles.ROLES whose holders carry
    #: cases at this tier.
    required_role = models.CharField(max_length=32)
    sla_hours = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "GRM tier rule"
        verbose_name_plural = "GRM tier rules"
        constraints = [
            models.UniqueConstraint(
                fields=["tier"],
                condition=models.Q(is_active=True),
                name="grm_tier_unique_active",
            ),
        ]
        indexes = [models.Index(fields=["tier", "is_active"])]
        ordering = ("tier",)

    def __str__(self) -> str:
        return f"{self.tier} -> {self.required_role} ({self.sla_hours}h)"
