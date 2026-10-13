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
from nsr_mis.common.fields import EncryptedBinaryField, ULIDField


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


# GrmReferenceSequence moved to reference_data.ReferenceSequence in
# migration 0012 — UPD, DRS and REF need the same counter, and four
# copies of it would drift.

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
    # Who complained, in the two terms a GRM is reported on.
    #
    # Disaggregating grievances by sex and age is what shows whether the
    # channel reaches women and whether older people can use it at all,
    # and neither question can be asked of a column that does not exist.
    # STAAC's intake asks both and sends them; before this they were
    # dropped on arrival.
    #
    # `reporter_gender` holds a code from the `sex` ChoiceList — the
    # same vocabulary and the same width as `Member.sex`, so one list
    # answers "what are the options" for both and a count can span them.
    # It is NOT free text and NOT another system's word for the same
    # thing: `apps.grievance.intake.resolve_gender` translates an
    # external value through a versioned binding, and `open_grievance`
    # refuses a code the list does not carry, so nothing untranslated
    # can reach the column.
    #
    # `reporter_age_years` is years, matching `Member.age_years`. There
    # is no ceiling here on purpose: the registry's implausible-age
    # threshold is the DQA rule AC-MEMBER-AGE-MAX, which applies to
    # members and flags rather than refuses, and restating 120 in this
    # app would be a second copy of a number that is already owned.
    reporter_gender = models.CharField(max_length=32, blank=True)
    reporter_age_years = models.PositiveSmallIntegerField(null=True, blank=True)

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
    # Where the case came from, when it is not this registry.
    #
    # A grievance reaching NSR from STAAC's GRM already has a tracking
    # number the complainant was read back before they hung up. With
    # nowhere to put it that number is unanswerable here: an officer
    # asked "what happened to C-26-057528-8" has nothing to look it up
    # by, and a resend of the same case is indistinguishable from a new
    # one.
    #
    # Blank for a case opened in NSR itself, which is most of them, so
    # the pair also says plainly which cases are ours.
    source_system = models.CharField(max_length=32, blank=True, db_index=True)
    external_reference = models.CharField(max_length=64, blank=True, db_index=True)
    # When the complainant reported it, which is not when we received
    # it. The SLA runs from this where it is known: time a case spent
    # between the two systems is time the complainant has already
    # waited, and starting the clock at ingestion would hand every
    # transferred case a fresh deadline it had not earned.
    reported_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Grievance"
        constraints = [
            # One case per external reference per system. A retry or a
            # duplicate push must find the case it already created
            # rather than opening a second one against the same
            # tracking number.
            models.UniqueConstraint(
                fields=["source_system", "external_reference"],
                condition=models.Q(external_reference__gt=""),
                name="grievance_external_reference_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "tier"]),
            models.Index(fields=["category", "status"]),
            models.Index(fields=["sla_deadline"]),
        ]

    def __str__(self) -> str:
        return f"Grievance {self.reference or self.id} [{self.tier}/{self.status}]"

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


class GrievanceAttachment(models.Model):
    """A document filed against a grievance.

    The complaint that arrives with a photograph of the posted
    beneficiary list, or the scan of the letter it was written on, is
    the evidence the case turns on. A grievance could hold a note and a
    task and nothing else, so a document sent with one had nowhere to
    go: STAAC's intake payload carries an `attachments` array and this
    registry had no column for it, which means a case transferred with
    its evidence would have arrived without it and nobody would have
    been told.

    The bytes are not here. They go to the registry's content-addressed
    blob store — `apps.update_workflow.evidence_storage`, reached
    through `get_evidence_storage()` — and this row holds the SHA-256
    that addresses them. Two consequences worth knowing:

    * the same file attached twice is one blob, and
      `(grievance, sha256)` is unique, so a resend of a case cannot
      duplicate its evidence;
    * the digest is the integrity check. A stored blob that no longer
      hashes to its row's `sha256` is a tampered or corrupt file, and
      that is checkable without a second checksum column.

    That store lives in `update_workflow` because change requests
    needed it first, and `data_requests.storage` is a second copy of
    the same three backends. Importing it rather than writing a third
    is the lesser wrong; the store wants a shared home, which is a
    dependency to report, not something to fix from here.
    """

    id = ULIDField(primary_key=True)
    grievance = models.ForeignKey(
        "Grievance", on_delete=models.CASCADE, related_name="attachments",
    )

    # What it was called where it came from, for an operator who has to
    # recognise it. Display only — nothing opens a file by this name,
    # because the store is keyed by digest.
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128)
    size_bytes = models.PositiveIntegerField()
    # The content address. Hex, lower case, 64 characters.
    sha256 = models.CharField(max_length=64, db_index=True)

    # The sending system's own id for this file, where there is one, so
    # a partner asking "did you get attachment 7 of C-26-057528-8" can
    # be answered. Blank for a document uploaded here.
    external_reference = models.CharField(max_length=128, blank=True)

    uploaded_by = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Grievance attachment"
        constraints = [
            # One row per distinct file per case. A retried transfer
            # re-sends the same bytes; it must find the attachment it
            # already created.
            models.UniqueConstraint(
                fields=["grievance", "sha256"],
                name="grievance_attachment_unique_per_case",
            ),
        ]
        indexes = [models.Index(fields=["grievance", "created_at"])]
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"{self.filename} on grievance {self.grievance_id}"


class StaacCredential(models.Model):
    """How this registry reaches STAAC's partner API, and with what.

    One row per environment. The token is the bearer credential STAAC
    issues once and then keeps only a SHA-256 digest of; it is held
    the way this registry already holds a third-party token — an
    encrypted column, decrypted in one place — rather than in settings
    or the environment, because ADR-0007 settled that and because a
    secret in a settings file is a secret in a backup.

    The cursor lives here rather than in its own table because it
    belongs to the credential, not to the registry: STAAC signs it
    with its own key, so rotating that key or issuing a new credential
    invalidates it, and a cursor that outlived its credential would be
    a silent resume from nowhere. `partner_views` signs cursors with
    no max age, so the only thing that expires them IS a key change —
    which is exactly why the pull treats a rejected cursor as "start
    again from the beginning" rather than an error.
    """

    id = ULIDField(primary_key=True)

    #: Environment label, so sandbox and production cannot be
    #: confused for one another in a log or an admin list.
    environment = models.CharField(max_length=32, unique=True)
    base_url = models.URLField(max_length=255)
    token_encrypted = EncryptedBinaryField()

    #: The opaque `next_cursor` STAAC last handed back, persisted only
    #: after every record on its page was stored. A half-stored page
    #: must be re-read, not skipped.
    cursor = models.TextField(blank=True)
    last_pulled_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "STAAC credential"

    def __str__(self) -> str:
        return f"STAAC {self.environment} ({self.base_url})"


class HeldReason(models.TextChoices):
    """Why a snapshot is held, as a value rather than a sentence.

    `intake.UnmappedCategoryError` already separates "we have never heard
    of this code" from "we know it and nobody has decided what it
    means here" — its own docstring calls them "different problems
    with different owners" — and the first version of this flattened
    both into English prose. That made the only question an operator
    actually asks ("which codes are blocking cases, and how many
    each") answerable only by reading sentences one at a time.

    `outcome_detail` keeps the sentence. This makes it countable.
    """

    UNKNOWN_CATEGORY = "unknown_category", "Category not in the registered list"
    UNBOUND_CATEGORY = "unbound_category", "Category registered, no approved binding"
    UNRESOLVED_PLACE = "unresolved_place", "Place names no GeographicUnit"
    UNVERIFIED_AGREEMENT = "unverified_agreement", "No data-provision agreement covers it"
    REFUSED = "refused", "Refused for another reason"


class HandoverOutcome(models.TextChoices):
    """What became of a snapshot this registry retrieved."""

    FILED = "filed", "Filed as a grievance"
    #: Retrieved, stored, and NOT filed — the registry could not
    #: classify or place it. Held rather than dropped: the complaint
    #: is real and the obstacle is configuration.
    HELD = "held", "Held — needs configuration before it can be filed"
    # There is deliberately no WITHDRAWN. STAAC withdraws a handover
    # by dropping it out of the collection, so a pull cannot observe
    # the withdrawal — only its absence, which is what the spec's
    # reconciliation step exists to detect and which this registry
    # does not do yet. A member no code path can write is a state the
    # enum advertises and the system cannot reach; better to have the
    # gap visible here than a value nothing will ever set.


class StaacHandover(models.Model):
    """One retrieved snapshot, exactly as STAAC sent it.

    This is the immutable landing `docs/ssot_register.md` requires of
    anything entering the registry from outside: what arrived, when,
    under which agreement, and what this registry made of it. The
    Grievance is the interpretation; this row is the evidence, and the
    two are deliberately separate so a mapping corrected next month
    can be re-applied to what was actually received rather than to a
    reconstruction of it.

    Why `(handover_id, exchange_version)` and not the tracking number
    ------------------------------------------------------------------
    The partner contract names that pair as the idempotency key, and
    the two halves answer different questions. `handover_id` is this
    delivery; `exchange_version` increments when STAAC withdraws and
    re-offers the same case. So a second version is a second SNAPSHOT
    of one case, not a second complaint — which is why the unique key
    is here and `Grievance.external_reference` stays the tracking
    number the complainant was read back. Several rows here can point
    at one Grievance; that is the correct shape, not a leak.
    """

    id = ULIDField(primary_key=True)

    handover_id = models.UUIDField(db_index=True)
    exchange_version = models.PositiveIntegerField()

    #: STAAC's case number, kept for the officer asked "what happened
    #: to C-26-057528-8". Not a key here — the pair above is.
    tracking_number = models.CharField(max_length=64, blank=True, db_index=True)

    #: Exactly what the detail endpoint returned, held in the
    #: registry's one landing table rather than a column of this one.
    #:
    #: `RawLanding` is append-only (AC-DIH-LANDING-IMMUTABLE) and FKs
    #: to the ConnectorRun that fetched it, so "what arrived, in which
    #: run, from which source" has one answer for every external
    #: payload the registry receives. A JSON column here was a second
    #: landing table whose only justification was that RawLanding
    #: needed a ConnectorRun; the run now exists, so the
    #: justification does not.
    raw_landing = models.OneToOneField(
        "ingestion_hub.RawLanding", on_delete=models.PROTECT,
        related_name="staac_handover",
    )

    #: The approved disclosure list STAAC sent with it. Stored because
    #: the spec makes it the audit record of what STAAC was permitted
    #: to release for THIS handover — not a property of the agreement
    #: in general, and not re-derivable later.
    fields_manifest = models.JSONField(default=list)
    agreement_reference = models.CharField(max_length=128, blank=True)
    agreement_version = models.CharField(max_length=32, blank=True)

    #: Retrieval provenance. The ETag lets a re-read be conditional;
    #: the correlation id is what STAAC's support can trace a dispute
    #: by, and is worthless if we do not keep it.
    etag = models.CharField(max_length=128, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True)
    retrieved_at = models.DateTimeField()

    outcome = models.CharField(
        max_length=16, choices=HandoverOutcome.choices,
        default=HandoverOutcome.HELD, db_index=True,
    )
    #: Why it is held. The kind is what an admin filters and counts
    #: on; the code is the thing somebody has to go and bind; the
    #: detail is the sentence for whoever reads one case.
    held_reason = models.CharField(
        max_length=32, choices=HeldReason.choices, blank=True, db_index=True,
    )
    held_choice_list = models.CharField(max_length=64, blank=True)
    held_source_code = models.CharField(max_length=128, blank=True)
    outcome_detail = models.TextField(blank=True)
    grievance = models.ForeignKey(
        "Grievance", on_delete=models.PROTECT, null=True, blank=True,
        related_name="staac_handovers",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "STAAC handover"
        constraints = [
            models.UniqueConstraint(
                fields=["handover_id", "exchange_version"],
                name="staac_handover_idempotency",
            ),
        ]
        indexes = [
            models.Index(fields=["outcome", "retrieved_at"]),
            models.Index(fields=["held_reason", "held_source_code"]),
        ]
        ordering = ("-retrieved_at",)

    def __str__(self) -> str:
        return (
            f"{self.tracking_number or self.handover_id} "
            f"v{self.exchange_version} [{self.outcome}]"
        )


    @property
    def snapshot(self) -> dict:
        """What STAAC sent, read from the landing that holds it."""
        return self.raw_landing.payload if self.raw_landing_id else {}

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
