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


class Sex(models.TextChoices):
    MALE = "M", "Male"
    FEMALE = "F", "Female"


class UrbanRural(models.TextChoices):
    URBAN = "urban"
    RURAL = "rural"
    PERI_URBAN = "peri_urban"


class NinStatus(models.TextChoices):
    HAS_CARD = "has_card"
    LOST = "lost"
    NOT_ISSUED = "not_issued"
    NO = "no"
    UNKNOWN = "unknown"


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
    village = models.ForeignKey(
        "reference_data.GeographicUnit", on_delete=models.PROTECT,
        related_name="households_in_village",
    )

    urban_rural = models.CharField(max_length=16, choices=UrbanRural.choices)
    enumeration_area = models.CharField(max_length=32, blank=True)
    household_number = models.CharField(max_length=32, blank=True)

    address_narrative = models.TextField(blank=True)

    # GPS — decimal placeholders; upgrades to PostGIS PointField in a follow-up.
    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_accuracy_m = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

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
    sex = models.CharField(max_length=1, choices=Sex.choices)
    date_of_birth = models.DateField(null=True, blank=True)
    age_years = models.PositiveSmallIntegerField(null=True, blank=True)

    marital_status = models.CharField(max_length=32, blank=True)
    nationality = models.CharField(max_length=32, blank=True)
    residency_status = models.CharField(max_length=32, blank=True)
    birth_certificate_status = models.CharField(max_length=32, blank=True)

    # NIN trio per ADR-0002. nin_value is encrypted; nin_hash is the join key;
    # nin_last4 is the masked display value.
    nin_status = models.CharField(max_length=16, choices=NinStatus.choices, default=NinStatus.UNKNOWN)
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
