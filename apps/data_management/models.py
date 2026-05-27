"""DAT models — Household and Member with paired version tables.

Sprint 0 scope:
- Household, Member (current state)
- HouseholdVersion, MemberVersion (paired, effective-from/to)

Out of scope here (separate stories): Relationship, Health, Education,
Employment, Dwelling, Utilities, AssetOwnership, FoodConsumption, Shock,
CopingStrategy, Consent, Submission, ChangeRequest.

References:
- SAD §5.1 (entity field lists), §5.2 (identifiers), §5.3 (versioning),
  §5.5 (indexing and sub-region partitioning)
- ADR-0002 (Registry ID and Person ID are ULIDs; NIN encrypted + hashed)
- ADR-0003 (migrations reversible through Sprint 5; audit/version row drops forbidden)

GPS columns are stored as decimal lat/lng/accuracy for Sprint 0. PostGIS
PointField + GIST index land in a follow-up migration once Postgres+PostGIS
+ GEOS/GDAL are wired into local dev (Docker compose).
"""

from __future__ import annotations

from django.db import models
from nsr_mis.common.fields import EncryptedBinaryField, ULIDField

# NOTE: Coded fields on Household and Member are plain CharField and
# resolve through apps/reference_data/services.py against the
# ChoiceList catalogue (ADR-0010). TextChoices enums were removed in
# US-S22-005c; the migration maps old enum values to ChoiceOption
# codes ("M" -> "1", "rural" -> "2", "has_card" -> "1", etc.).


class Household(models.Model):
    """Current-state household record. id is the Registry ID (ULID)."""

    id = ULIDField(primary_key=True)

    # Head pointer — nullable because Member rows are created after Household,
    # then we update this. ChangeRequest workflow enforces head-one rule (DQA AC-HEAD-ONE).
    head_member = models.ForeignKey(
        "Member",
        on_delete=models.PROTECT,
        related_name="head_of_household",
        null=True,
        blank=True,
    )

    # Geographic FKs — UBOS hierarchy. All point at the same GeographicUnit table.
    region = models.ForeignKey(
        "reference_data.GeographicUnit", on_delete=models.PROTECT,
        related_name="households_in_region",
    )
    sub_region = models.ForeignKey(
        "reference_data.GeographicUnit", on_delete=models.PROTECT,
        related_name="households_in_sub_region", db_index=True,
    )
    district = models.ForeignKey(
        "reference_data.GeographicUnit", on_delete=models.PROTECT,
        related_name="households_in_district",
    )
    county = models.ForeignKey(
        "reference_data.GeographicUnit", on_delete=models.PROTECT,
        related_name="households_in_county",
    )
    sub_county = models.ForeignKey(
        "reference_data.GeographicUnit", on_delete=models.PROTECT,
        related_name="households_in_sub_county",
    )
    parish = models.ForeignKey(
        "reference_data.GeographicUnit", on_delete=models.PROTECT,
        related_name="households_in_parish",
    )
    # Village is OPTIONAL — the UBOS frame doesn't carry village rows
    # for every parish (only ~19 of 10,872 are seeded), and field
    # ops report village often unknown at parish-walk-in capture time.
    # Parish is the lowest mandatory level.
    village = models.ForeignKey(
        "reference_data.GeographicUnit", on_delete=models.PROTECT,
        related_name="households_in_village",
        null=True, blank=True,
    )

    urban_rural = models.CharField(max_length=32, blank=True)
    enumeration_area = models.CharField(max_length=32, blank=True)
    household_number = models.CharField(max_length=32, blank=True)

    # US-S11-044 — operator-reported household size, captured at intake
    # via canonical_payload.interview.hh_size. Promotion copies it
    # across; AC-MEMBER-COUNT-MATCH reads this and compares against
    # the actual member roster length. Nullable for historical rows
    # captured before this field existed.
    reported_household_size = models.PositiveIntegerField(null=True, blank=True)

    address_narrative = models.TextField(blank=True)

    # GPS — decimal placeholders; upgrades to PostGIS PointField in a follow-up.
    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_accuracy_m = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    # DEPRECATED (US-S22-DE): redundant with Dwelling.tenure. Promotion writes
    # both for one release; consumers should read via household.dwelling.tenure
    # going forward. Removed by US-S22-DE-15 after the deprecation window closes.
    dwelling_tenure = models.CharField(max_length=32, blank=True)
    residence_status = models.CharField(max_length=32, blank=True)

    current_pmt_score = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    current_vulnerability_band = models.CharField(max_length=16, blank=True)
    current_consent_state = models.CharField(max_length=16, blank=True)
    current_intake_source = models.CharField(max_length=16, blank=True)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # Denormalised partition key per ADR-0005. Mirrors sub_region.code; auto-
    # populated in save(). Indexed so it can serve admin filters today, then
    # become the LIST partition key during the Sprint 2 cut-over.
    sub_region_code = models.CharField(max_length=32, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Household"
        verbose_name_plural = "Households"
        indexes = [
            models.Index(fields=["village"]),
            models.Index(fields=["parish"]),
            models.Index(fields=["is_deleted", "updated_at"]),
            # Pre-partition shape: post cut-over, this index is rewritten by
            # the partition routing per ADR-0005.
            models.Index(fields=["sub_region_code", "id"]),
        ]

    def __str__(self) -> str:
        return f"Household {self.id}"

    def save(self, *args, **kwargs):
        # Keep sub_region_code in lockstep with sub_region.code (ADR-0005).
        if self.sub_region_id and not self.sub_region_code:
            self.sub_region_code = self.sub_region.code
        super().save(*args, **kwargs)

    def clean(self):
        # US-FIX-001 — head-member invariant. If `head_member` is set
        # then its `relationship_to_head` MUST be "01" (the
        # ChoiceOption code for "Head" on the seeded `relationship`
        # list). Audit_2026-05-21 §4 flagged this divergence in the
        # dev fixture; the registry's promote path now enforces the
        # code at write time, and this `clean()` guards any other
        # path (admin, shells, future writers) so the invariant is
        # also a model-level fact.
        super().clean()
        if self.head_member_id and self.head_member.relationship_to_head not in ("", "01"):
            from django.core.exceptions import ValidationError
            raise ValidationError({
                "head_member": (
                    f"head_member.relationship_to_head must be '01' (Head); "
                    f"got {self.head_member.relationship_to_head!r}."
                ),
            })


class Member(models.Model):
    """Current-state member record. id is the Person ID (ULID)."""

    id = ULIDField(primary_key=True)
    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="members"
    )

    line_number = models.PositiveSmallIntegerField()

    surname = models.CharField(max_length=64)
    first_name = models.CharField(max_length=64)
    other_name = models.CharField(max_length=64, blank=True)

    relationship_to_head = models.CharField(max_length=32)
    sex = models.CharField(max_length=32)
    date_of_birth = models.DateField(null=True, blank=True)
    age_years = models.PositiveSmallIntegerField(null=True, blank=True)

    marital_status = models.CharField(max_length=32, blank=True)
    nationality = models.CharField(max_length=32, blank=True)
    residency_status = models.CharField(max_length=32, blank=True)
    birth_certificate_status = models.CharField(max_length=32, blank=True)

    # NIN trio per ADR-0002. nin_value is encrypted; nin_hash is the join key;
    # nin_last4 is the masked display value.
    nin_status = models.CharField(max_length=32, blank=True, default="8")
    nin_value = EncryptedBinaryField(null=True, blank=True)
    nin_hash = models.BinaryField(max_length=32, null=True, blank=True)
    nin_last4 = models.CharField(max_length=4, blank=True)

    telephone_1 = models.CharField(max_length=20, blank=True)
    telephone_2 = models.CharField(max_length=20, blank=True)
    telephone_in_name_flag = models.BooleanField(default=False)
    mobile_money_flag = models.BooleanField(default=False)

    mother_alive_flag = models.BooleanField(null=True, blank=True)
    father_alive_flag = models.BooleanField(null=True, blank=True)
    mother_line_number = models.PositiveSmallIntegerField(null=True, blank=True)
    father_line_number = models.PositiveSmallIntegerField(null=True, blank=True)

    # US-S11-044 — AC-ORPHAN-FLAG reads this. Captured by CAPI when
    # both parents are marked deceased and the member is under 18.
    # Nullable for backwards compatibility with historical rows;
    # the DQA rule fires only when both parent flags are explicitly
    # False (i.e. data was captured for both axes).
    orphan_flag = models.BooleanField(null=True, blank=True)

    identification_documents = models.JSONField(default=list, blank=True)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    merged_into = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="merged_aliases"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Denormalised partition key inherited from the household (ADR-0005).
    sub_region_code = models.CharField(max_length=32, blank=True, db_index=True)

    class Meta:
        verbose_name = "Member"
        verbose_name_plural = "Members"
        constraints = [
            models.UniqueConstraint(fields=["household", "line_number"], name="member_line_unique_per_household"),
        ]
        indexes = [
            models.Index(fields=["household"]),
            models.Index(fields=["nin_hash"]),
            models.Index(fields=["telephone_1"]),
            models.Index(fields=["surname", "first_name"]),
            models.Index(fields=["sub_region_code", "id"]),
        ]

    def __str__(self) -> str:
        return f"{self.surname} {self.first_name} ({self.id})"

    def save(self, *args, **kwargs):
        # Inherit the partition key from the parent household (ADR-0005).
        if self.household_id and not self.sub_region_code:
            self.sub_region_code = self.household.sub_region_code
        super().save(*args, **kwargs)


# --- Versioning -------------------------------------------------------------
#
# Paired _Version tables per SAD §5.3. Each row records the state as-of a
# (effective_from, effective_to) window. effective_to IS NULL identifies the
# current row. The change-request FK is intentionally a CharField pointer
# for Sprint 0 because the ChangeRequest model lives in apps.update_workflow
# and is not yet built — we record the ULID without enforcing the FK so the
# audit chain is intact from day one.

class _VersionBase(models.Model):
    version_number = models.PositiveIntegerField()
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)
    change_request_id = models.CharField(max_length=26, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=64, blank=True)

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{self.__class__.__name__} v{self.version_number}"


class HouseholdVersion(_VersionBase):
    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="versions"
    )

    # Mirror of the head pointer plus the mutable Household fields. Geographic
    # FKs and identity fields that don't change are not snapshotted.
    head_member_id = models.CharField(max_length=26, blank=True)
    urban_rural = models.CharField(max_length=16, blank=True)
    address_narrative = models.TextField(blank=True)
    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_accuracy_m = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    dwelling_tenure = models.CharField(max_length=32, blank=True)
    residence_status = models.CharField(max_length=32, blank=True)
    current_pmt_score = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    current_vulnerability_band = models.CharField(max_length=16, blank=True)

    class Meta:
        verbose_name = "Household version"
        verbose_name_plural = "Household versions"
        constraints = [
            models.UniqueConstraint(
                fields=["household", "version_number"], name="household_version_number_unique"
            ),
        ]
        indexes = [
            models.Index(fields=["household", "effective_from"]),
            models.Index(fields=["household", "effective_to"]),
        ]

    def __str__(self) -> str:
        return f"HouseholdVersion {self.household_id} v{self.version_number}"


class MemberVersion(_VersionBase):
    member = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="versions"
    )

    # Mirror of mutable Member fields per SAD §5.1 (Member entity).
    surname = models.CharField(max_length=64, blank=True)
    first_name = models.CharField(max_length=64, blank=True)
    other_name = models.CharField(max_length=64, blank=True)
    relationship_to_head = models.CharField(max_length=32, blank=True)
    marital_status = models.CharField(max_length=32, blank=True)
    nationality = models.CharField(max_length=32, blank=True)
    residency_status = models.CharField(max_length=32, blank=True)
    birth_certificate_status = models.CharField(max_length=32, blank=True)
    nin_status = models.CharField(max_length=16, blank=True)
    nin_hash = models.BinaryField(max_length=32, null=True, blank=True)
    nin_last4 = models.CharField(max_length=4, blank=True)
    telephone_1 = models.CharField(max_length=20, blank=True)
    telephone_2 = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = "Member version"
        verbose_name_plural = "Member versions"
        constraints = [
            models.UniqueConstraint(
                fields=["member", "version_number"], name="member_version_number_unique"
            ),
        ]
        indexes = [
            models.Index(fields=["member", "effective_from"]),
            models.Index(fields=["member", "effective_to"]),
        ]

    def __str__(self) -> str:
        return f"MemberVersion {self.member_id} v{self.version_number}"


# ===========================================================================
# Detail entities (US-S22-DE-01) — per-Household / per-Member typed columns
# from questionnaire sections C16–L02. See ADR-0019 (separate tables vs
# JSONField), ADR-0020 (repeat-group child tables), ADR-0021 (sensitive
# health encryption), ADR-0022 (FIES + FCS computed columns).
# ===========================================================================


class _DetailBase(models.Model):
    """Common columns for every detail entity:
    ULID id, sub_region_code denorm for partition routing (ADR-0005),
    soft-delete + timestamps."""

    id = ULIDField(primary_key=True)
    sub_region_code = models.CharField(max_length=32, blank=True, db_index=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{self.__class__.__name__} {self.id}"


# --- Per-Household one-to-one entities -----------------------------------


class Dwelling(_DetailBase):
    """Household questionnaire section G1–G7."""

    household = models.OneToOneField(
        Household, on_delete=models.PROTECT, related_name="dwelling",
    )
    tenure = models.CharField(max_length=32, blank=True)
    dwelling_type = models.CharField(max_length=32, blank=True)
    total_rooms = models.PositiveSmallIntegerField(null=True, blank=True)
    sleeping_rooms = models.PositiveSmallIntegerField(null=True, blank=True)
    roof_material = models.CharField(max_length=32, blank=True)
    wall_material = models.CharField(max_length=32, blank=True)
    floor_material = models.CharField(max_length=32, blank=True)

    def save(self, *args, **kwargs):
        if self.household_id and not self.sub_region_code:
            self.sub_region_code = self.household.sub_region_code
        super().save(*args, **kwargs)


class DwellingVersion(_VersionBase):
    dwelling = models.ForeignKey(Dwelling, on_delete=models.PROTECT, related_name="versions")
    tenure = models.CharField(max_length=32, blank=True)
    dwelling_type = models.CharField(max_length=32, blank=True)
    total_rooms = models.PositiveSmallIntegerField(null=True, blank=True)
    sleeping_rooms = models.PositiveSmallIntegerField(null=True, blank=True)
    roof_material = models.CharField(max_length=32, blank=True)
    wall_material = models.CharField(max_length=32, blank=True)
    floor_material = models.CharField(max_length=32, blank=True)

    class Meta:
        verbose_name = "Dwelling version"
        constraints = [
            models.UniqueConstraint(fields=["dwelling", "version_number"], name="dwelling_version_unique"),
        ]


class Utilities(_DetailBase):
    """Household questionnaire section G8–G14."""

    household = models.OneToOneField(
        Household, on_delete=models.PROTECT, related_name="utilities",
    )
    cooking_fuel = models.CharField(max_length=32, blank=True)
    lighting_energy = models.CharField(max_length=32, blank=True)
    drinking_water_source = models.CharField(max_length=32, blank=True)
    toilet_facility = models.CharField(max_length=32, blank=True)
    toilet_shared = models.BooleanField(null=True, blank=True)
    households_sharing_toilet = models.PositiveSmallIntegerField(null=True, blank=True)
    waste_disposal = models.CharField(max_length=32, blank=True)

    def save(self, *args, **kwargs):
        if self.household_id and not self.sub_region_code:
            self.sub_region_code = self.household.sub_region_code
        # G13 cap per questionnaire — at most 10 households share one toilet.
        if self.households_sharing_toilet is not None:
            self.households_sharing_toilet = min(self.households_sharing_toilet, 10)
        super().save(*args, **kwargs)


class UtilitiesVersion(_VersionBase):
    utilities = models.ForeignKey(Utilities, on_delete=models.PROTECT, related_name="versions")
    cooking_fuel = models.CharField(max_length=32, blank=True)
    lighting_energy = models.CharField(max_length=32, blank=True)
    drinking_water_source = models.CharField(max_length=32, blank=True)
    toilet_facility = models.CharField(max_length=32, blank=True)
    toilet_shared = models.BooleanField(null=True, blank=True)
    households_sharing_toilet = models.PositiveSmallIntegerField(null=True, blank=True)
    waste_disposal = models.CharField(max_length=32, blank=True)

    class Meta:
        verbose_name = "Utilities version"
        constraints = [
            models.UniqueConstraint(fields=["utilities", "version_number"], name="utilities_version_unique"),
        ]


class Livelihood(_DetailBase):
    """Household sections G16, H1–H8."""

    household = models.OneToOneField(
        Household, on_delete=models.PROTECT, related_name="livelihood",
    )
    main_livelihood = models.CharField(max_length=32, blank=True)
    crop_production_zone = models.CharField(max_length=32, blank=True)
    livestock_zone = models.CharField(max_length=32, blank=True)
    agricultural_purpose = models.CharField(max_length=32, blank=True)
    land_ownership = models.CharField(max_length=32, blank=True)
    land_hectares = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    land_title = models.CharField(max_length=32, blank=True)

    def save(self, *args, **kwargs):
        if self.household_id and not self.sub_region_code:
            self.sub_region_code = self.household.sub_region_code
        super().save(*args, **kwargs)


class LivelihoodVersion(_VersionBase):
    livelihood = models.ForeignKey(Livelihood, on_delete=models.PROTECT, related_name="versions")
    main_livelihood = models.CharField(max_length=32, blank=True)
    crop_production_zone = models.CharField(max_length=32, blank=True)
    livestock_zone = models.CharField(max_length=32, blank=True)
    agricultural_purpose = models.CharField(max_length=32, blank=True)
    land_ownership = models.CharField(max_length=32, blank=True)
    land_hectares = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    land_title = models.CharField(max_length=32, blank=True)

    class Meta:
        verbose_name = "Livelihood version"
        constraints = [
            models.UniqueConstraint(fields=["livelihood", "version_number"], name="livelihood_version_unique"),
        ]


class FoodSecurity(_DetailBase):
    """FIES — section I1–I8. fies_raw_score is computed on save
    (ADR-0022): sum of yes-coded responses (`"1"`), 0–8."""

    household = models.OneToOneField(
        Household, on_delete=models.PROTECT, related_name="food_security",
    )
    worried_food = models.CharField(max_length=4, blank=True)
    unhealthy_food = models.CharField(max_length=4, blank=True)
    limited_variety = models.CharField(max_length=4, blank=True)
    skipped_meal = models.CharField(max_length=4, blank=True)
    ate_less = models.CharField(max_length=4, blank=True)
    ran_out_food = models.CharField(max_length=4, blank=True)
    hungry_no_eat = models.CharField(max_length=4, blank=True)
    whole_day_no_eat = models.CharField(max_length=4, blank=True)
    fies_raw_score = models.PositiveSmallIntegerField(default=0)

    def save(self, *args, **kwargs):
        if self.household_id and not self.sub_region_code:
            self.sub_region_code = self.household.sub_region_code
        # FIES coding: "1" affirmative, anything else not.
        self.fies_raw_score = sum(
            1 for v in (
                self.worried_food, self.unhealthy_food, self.limited_variety,
                self.skipped_meal, self.ate_less, self.ran_out_food,
                self.hungry_no_eat, self.whole_day_no_eat,
            ) if (v or "").strip() == "1"
        )
        super().save(*args, **kwargs)


class FoodSecurityVersion(_VersionBase):
    food_security = models.ForeignKey(FoodSecurity, on_delete=models.PROTECT, related_name="versions")
    worried_food = models.CharField(max_length=4, blank=True)
    unhealthy_food = models.CharField(max_length=4, blank=True)
    limited_variety = models.CharField(max_length=4, blank=True)
    skipped_meal = models.CharField(max_length=4, blank=True)
    ate_less = models.CharField(max_length=4, blank=True)
    ran_out_food = models.CharField(max_length=4, blank=True)
    hungry_no_eat = models.CharField(max_length=4, blank=True)
    whole_day_no_eat = models.CharField(max_length=4, blank=True)
    fies_raw_score = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Food security version"
        constraints = [
            models.UniqueConstraint(fields=["food_security", "version_number"], name="food_security_version_unique"),
        ]


# WFP Food Consumption Score weights — multiplied by days_last_7 per group
# and summed for the household's fcs_score (0–112). See ADR-0022.
_FCS_WEIGHTS = {
    "staples":    2.0,
    "pulses":     3.0,
    "dairy":      4.0,
    "meat":       4.0,
    "vegetables": 1.0,
    "fruits":     1.0,
    "oils":       0.5,
    "sugar":      0.5,
    "condiments": 0.0,
}


class FoodConsumption(_DetailBase):
    """FCS — section I9–I17. fcs_score is the WFP-weighted total,
    computed on save (ADR-0022)."""

    household = models.OneToOneField(
        Household, on_delete=models.PROTECT, related_name="food_consumption",
    )
    staples_days = models.PositiveSmallIntegerField(default=0)
    pulses_days = models.PositiveSmallIntegerField(default=0)
    dairy_days = models.PositiveSmallIntegerField(default=0)
    meat_days = models.PositiveSmallIntegerField(default=0)
    vegetables_days = models.PositiveSmallIntegerField(default=0)
    fruits_days = models.PositiveSmallIntegerField(default=0)
    oils_days = models.PositiveSmallIntegerField(default=0)
    sugar_days = models.PositiveSmallIntegerField(default=0)
    condiments_days = models.PositiveSmallIntegerField(default=0)
    staples_source = models.CharField(max_length=32, blank=True)
    pulses_source = models.CharField(max_length=32, blank=True)
    dairy_source = models.CharField(max_length=32, blank=True)
    meat_source = models.CharField(max_length=32, blank=True)
    vegetables_source = models.CharField(max_length=32, blank=True)
    fruits_source = models.CharField(max_length=32, blank=True)
    oils_source = models.CharField(max_length=32, blank=True)
    sugar_source = models.CharField(max_length=32, blank=True)
    condiments_source = models.CharField(max_length=32, blank=True)
    fcs_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    def save(self, *args, **kwargs):
        if self.household_id and not self.sub_region_code:
            self.sub_region_code = self.household.sub_region_code
        days = {
            "staples":    min(self.staples_days or 0, 7),
            "pulses":     min(self.pulses_days or 0, 7),
            "dairy":      min(self.dairy_days or 0, 7),
            "meat":       min(self.meat_days or 0, 7),
            "vegetables": min(self.vegetables_days or 0, 7),
            "fruits":     min(self.fruits_days or 0, 7),
            "oils":       min(self.oils_days or 0, 7),
            "sugar":      min(self.sugar_days or 0, 7),
            "condiments": min(self.condiments_days or 0, 7),
        }
        self.fcs_score = sum(days[g] * _FCS_WEIGHTS[g] for g in days)
        super().save(*args, **kwargs)


class FoodConsumptionVersion(_VersionBase):
    food_consumption = models.ForeignKey(FoodConsumption, on_delete=models.PROTECT, related_name="versions")
    staples_days = models.PositiveSmallIntegerField(default=0)
    pulses_days = models.PositiveSmallIntegerField(default=0)
    dairy_days = models.PositiveSmallIntegerField(default=0)
    meat_days = models.PositiveSmallIntegerField(default=0)
    vegetables_days = models.PositiveSmallIntegerField(default=0)
    fruits_days = models.PositiveSmallIntegerField(default=0)
    oils_days = models.PositiveSmallIntegerField(default=0)
    sugar_days = models.PositiveSmallIntegerField(default=0)
    condiments_days = models.PositiveSmallIntegerField(default=0)
    staples_source = models.CharField(max_length=32, blank=True)
    pulses_source = models.CharField(max_length=32, blank=True)
    dairy_source = models.CharField(max_length=32, blank=True)
    meat_source = models.CharField(max_length=32, blank=True)
    vegetables_source = models.CharField(max_length=32, blank=True)
    fruits_source = models.CharField(max_length=32, blank=True)
    oils_source = models.CharField(max_length=32, blank=True)
    sugar_source = models.CharField(max_length=32, blank=True)
    condiments_source = models.CharField(max_length=32, blank=True)
    fcs_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Food consumption version"
        constraints = [
            models.UniqueConstraint(
                fields=["food_consumption", "version_number"],
                name="food_consumption_version_unique",
            ),
        ]


# --- Per-Household repeat-group entities ---------------------------------


class AssetOwnership(_DetailBase):
    """Section G15. One row per asset type per household. count capped at 9."""

    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="assets",
    )
    asset_type = models.CharField(max_length=32)
    count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["household", "asset_type"],
                name="asset_owner_unique_per_household",
                condition=models.Q(is_deleted=False),
            ),
        ]
        indexes = [models.Index(fields=["sub_region_code", "asset_type"])]

    def save(self, *args, **kwargs):
        if self.household_id and not self.sub_region_code:
            self.sub_region_code = self.household.sub_region_code
        self.count = min(self.count or 0, 9)
        super().save(*args, **kwargs)


class AssetOwnershipVersion(_VersionBase):
    asset = models.ForeignKey(AssetOwnership, on_delete=models.PROTECT, related_name="versions")
    asset_type = models.CharField(max_length=32, blank=True)
    count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Asset version"
        constraints = [
            models.UniqueConstraint(fields=["asset", "version_number"], name="asset_version_unique"),
        ]


class Crop(_DetailBase):
    """Sections H3, H5 — one row per crop per household."""

    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="crops",
    )
    crop_name = models.CharField(max_length=32)
    rank_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["household", "crop_name"],
                name="crop_unique_per_household",
                condition=models.Q(is_deleted=False),
            ),
        ]
        indexes = [models.Index(fields=["sub_region_code", "crop_name"])]

    def save(self, *args, **kwargs):
        if self.household_id and not self.sub_region_code:
            self.sub_region_code = self.household.sub_region_code
        super().save(*args, **kwargs)


class CropVersion(_VersionBase):
    crop = models.ForeignKey(Crop, on_delete=models.PROTECT, related_name="versions")
    crop_name = models.CharField(max_length=32, blank=True)
    rank_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Crop version"
        constraints = [
            models.UniqueConstraint(fields=["crop", "version_number"], name="crop_version_unique"),
        ]


class Livestock(_DetailBase):
    """Section H3 a–h — one row per livestock type per household."""

    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="livestock",
    )
    livestock_type = models.CharField(max_length=32)
    count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["household", "livestock_type"],
                name="livestock_unique_per_household",
                condition=models.Q(is_deleted=False),
            ),
        ]
        indexes = [models.Index(fields=["sub_region_code", "livestock_type"])]

    def save(self, *args, **kwargs):
        if self.household_id and not self.sub_region_code:
            self.sub_region_code = self.household.sub_region_code
        super().save(*args, **kwargs)


class LivestockVersion(_VersionBase):
    livestock = models.ForeignKey(Livestock, on_delete=models.PROTECT, related_name="versions")
    livestock_type = models.CharField(max_length=32, blank=True)
    count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Livestock version"
        constraints = [
            models.UniqueConstraint(fields=["livestock", "version_number"], name="livestock_version_unique"),
        ]


class Shock(_DetailBase):
    """Sections K01–K04 — one row per shock event affecting the household."""

    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="shocks",
    )
    shock_type = models.CharField(max_length=32)
    livelihoods_affected = models.JSONField(default=list, blank=True)
    severity = models.CharField(max_length=32, blank=True)
    crops_severity_score = models.PositiveSmallIntegerField(null=True, blank=True)
    livestock_severity_score = models.PositiveSmallIntegerField(null=True, blank=True)
    labour_severity_score = models.PositiveSmallIntegerField(null=True, blank=True)
    other_severity_score = models.PositiveSmallIntegerField(null=True, blank=True)
    event_date = models.DateField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["household", "event_date"]),
            models.Index(fields=["sub_region_code", "shock_type"]),
        ]

    def save(self, *args, **kwargs):
        if self.household_id and not self.sub_region_code:
            self.sub_region_code = self.household.sub_region_code
        super().save(*args, **kwargs)


class ShockVersion(_VersionBase):
    shock = models.ForeignKey(Shock, on_delete=models.PROTECT, related_name="versions")
    shock_type = models.CharField(max_length=32, blank=True)
    livelihoods_affected = models.JSONField(default=list, blank=True)
    severity = models.CharField(max_length=32, blank=True)
    crops_severity_score = models.PositiveSmallIntegerField(null=True, blank=True)
    livestock_severity_score = models.PositiveSmallIntegerField(null=True, blank=True)
    labour_severity_score = models.PositiveSmallIntegerField(null=True, blank=True)
    other_severity_score = models.PositiveSmallIntegerField(null=True, blank=True)
    event_date = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Shock version"
        constraints = [
            models.UniqueConstraint(fields=["shock", "version_number"], name="shock_version_unique"),
        ]


class CopingStrategy(_DetailBase):
    """Sections L01 and L02. category distinguishes livelihood-coping
    (L01) from food-coping (L02). strategy_type is a code from the
    combined `coping_strategy_type` ChoiceList covering L01a–i and
    L02a–i."""

    household = models.ForeignKey(
        Household, on_delete=models.PROTECT, related_name="coping_strategies",
    )
    strategy_type = models.CharField(max_length=32)
    category = models.CharField(max_length=16)
    frequency = models.CharField(max_length=32, blank=True)
    used_flag = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["household", "strategy_type", "category"],
                name="coping_unique_per_household_strategy",
                condition=models.Q(is_deleted=False),
            ),
        ]
        indexes = [models.Index(fields=["sub_region_code", "category"])]

    def save(self, *args, **kwargs):
        if self.household_id and not self.sub_region_code:
            self.sub_region_code = self.household.sub_region_code
        super().save(*args, **kwargs)


class CopingStrategyVersion(_VersionBase):
    coping = models.ForeignKey(CopingStrategy, on_delete=models.PROTECT, related_name="versions")
    strategy_type = models.CharField(max_length=32, blank=True)
    category = models.CharField(max_length=16, blank=True)
    frequency = models.CharField(max_length=32, blank=True)
    used_flag = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Coping strategy version"
        constraints = [
            models.UniqueConstraint(fields=["coping", "version_number"], name="coping_version_unique"),
        ]


# --- Per-Member one-to-one entities --------------------------------------


class Health(_DetailBase):
    """Section D1–D2 (Members 2+ yrs). chronic_illness_types_encrypted
    is the JSON-serialized list of chronic-illness codes, stored
    encrypted (ADR-0021) because the list may include HIV/TB codes
    (DPPA 2019 special category data)."""

    member = models.OneToOneField(
        Member, on_delete=models.PROTECT, related_name="health",
    )
    chronic_illness_flag = models.CharField(max_length=8, blank=True)
    chronic_illness_types_encrypted = EncryptedBinaryField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.member_id and not self.sub_region_code:
            self.sub_region_code = self.member.sub_region_code
        super().save(*args, **kwargs)

    def get_chronic_illness_types(self) -> list[str]:
        """Decode the encrypted JSON list. Returns [] when empty or unreadable."""
        if not self.chronic_illness_types_encrypted:
            return []
        try:
            import json
            data = self.chronic_illness_types_encrypted
            if isinstance(data, (bytes, bytearray, memoryview)):
                return list(json.loads(bytes(data).decode("utf-8")))
            return list(data) if isinstance(data, list) else []
        except (ValueError, UnicodeDecodeError):
            return []

    def set_chronic_illness_types(self, codes: list[str]) -> None:
        """Encode + assign. Caller should save() to persist."""
        import json
        self.chronic_illness_types_encrypted = json.dumps(list(codes)).encode("utf-8")


class HealthVersion(_VersionBase):
    health = models.ForeignKey(Health, on_delete=models.PROTECT, related_name="versions")
    chronic_illness_flag = models.CharField(max_length=8, blank=True)
    chronic_illness_types_encrypted = EncryptedBinaryField(null=True, blank=True)

    class Meta:
        verbose_name = "Health version"
        constraints = [
            models.UniqueConstraint(fields=["health", "version_number"], name="health_version_unique"),
        ]


class Disability(_DetailBase):
    """Section D3–D8 — Washington Group Short Set (Members 2+ yrs).
    wg_disability_flag is True when any column is `03` (a lot of
    difficulty) or `04` (cannot do at all). Computed on save
    (ADR-0022)."""

    member = models.OneToOneField(
        Member, on_delete=models.PROTECT, related_name="disability",
    )
    seeing = models.CharField(max_length=4, blank=True)
    hearing = models.CharField(max_length=4, blank=True)
    walking = models.CharField(max_length=4, blank=True)
    memory = models.CharField(max_length=4, blank=True)
    selfcare = models.CharField(max_length=4, blank=True)
    communication = models.CharField(max_length=4, blank=True)
    wg_disability_flag = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.member_id and not self.sub_region_code:
            self.sub_region_code = self.member.sub_region_code
        threshold = {"03", "04"}
        self.wg_disability_flag = any(
            (v or "").strip() in threshold
            for v in (
                self.seeing, self.hearing, self.walking,
                self.memory, self.selfcare, self.communication,
            )
        )
        super().save(*args, **kwargs)


class DisabilityVersion(_VersionBase):
    disability = models.ForeignKey(Disability, on_delete=models.PROTECT, related_name="versions")
    seeing = models.CharField(max_length=4, blank=True)
    hearing = models.CharField(max_length=4, blank=True)
    walking = models.CharField(max_length=4, blank=True)
    memory = models.CharField(max_length=4, blank=True)
    selfcare = models.CharField(max_length=4, blank=True)
    communication = models.CharField(max_length=4, blank=True)
    wg_disability_flag = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Disability version"
        constraints = [
            models.UniqueConstraint(fields=["disability", "version_number"], name="disability_version_unique"),
        ]


class Education(_DetailBase):
    """Section E1–E6 (Members 3+ yrs)."""

    member = models.OneToOneField(
        Member, on_delete=models.PROTECT, related_name="education",
    )
    literacy_status = models.CharField(max_length=8, blank=True)
    ever_attended = models.CharField(max_length=8, blank=True)
    never_attended_reason = models.CharField(max_length=8, blank=True)
    highest_grade = models.CharField(max_length=8, blank=True)
    currently_attending = models.CharField(max_length=8, blank=True)
    why_stopped = models.CharField(max_length=8, blank=True)

    def save(self, *args, **kwargs):
        if self.member_id and not self.sub_region_code:
            self.sub_region_code = self.member.sub_region_code
        super().save(*args, **kwargs)


class EducationVersion(_VersionBase):
    education = models.ForeignKey(Education, on_delete=models.PROTECT, related_name="versions")
    literacy_status = models.CharField(max_length=8, blank=True)
    ever_attended = models.CharField(max_length=8, blank=True)
    never_attended_reason = models.CharField(max_length=8, blank=True)
    highest_grade = models.CharField(max_length=8, blank=True)
    currently_attending = models.CharField(max_length=8, blank=True)
    why_stopped = models.CharField(max_length=8, blank=True)

    class Meta:
        verbose_name = "Education version"
        constraints = [
            models.UniqueConstraint(fields=["education", "version_number"], name="education_version_unique"),
        ]


class Employment(_DetailBase):
    """Section F1–F10 (Members 7+ yrs)."""

    member = models.OneToOneField(
        Member, on_delete=models.PROTECT, related_name="employment",
    )
    main_activity_last_30d = models.CharField(max_length=8, blank=True)
    work_frequency = models.CharField(max_length=8, blank=True)
    sector = models.CharField(max_length=8, blank=True)
    employment_status = models.CharField(max_length=8, blank=True)
    not_working_reason = models.CharField(max_length=8, blank=True)
    is_govt_programme_beneficiary = models.CharField(max_length=8, blank=True)
    programmes_benefited = models.JSONField(default=list, blank=True)
    currently_benefiting = models.CharField(max_length=8, blank=True)
    made_savings = models.CharField(max_length=8, blank=True)
    savings_location = models.CharField(max_length=8, blank=True)

    def save(self, *args, **kwargs):
        if self.member_id and not self.sub_region_code:
            self.sub_region_code = self.member.sub_region_code
        super().save(*args, **kwargs)


class EmploymentVersion(_VersionBase):
    employment = models.ForeignKey(Employment, on_delete=models.PROTECT, related_name="versions")
    main_activity_last_30d = models.CharField(max_length=8, blank=True)
    work_frequency = models.CharField(max_length=8, blank=True)
    sector = models.CharField(max_length=8, blank=True)
    employment_status = models.CharField(max_length=8, blank=True)
    not_working_reason = models.CharField(max_length=8, blank=True)
    is_govt_programme_beneficiary = models.CharField(max_length=8, blank=True)
    programmes_benefited = models.JSONField(default=list, blank=True)
    currently_benefiting = models.CharField(max_length=8, blank=True)
    made_savings = models.CharField(max_length=8, blank=True)
    savings_location = models.CharField(max_length=8, blank=True)

    class Meta:
        verbose_name = "Employment version"
        constraints = [
            models.UniqueConstraint(fields=["employment", "version_number"], name="employment_version_unique"),
        ]
