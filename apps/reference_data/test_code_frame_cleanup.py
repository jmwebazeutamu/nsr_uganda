"""P1 #8 and #9 — one region per region, one code frame per list.

#8  The Region dropdown listed five options for four regions: Central,
    Eastern, Northern (R-NORTHERN), Western, Northern (UG-N). Two
    identical labels, and picking UG-N left Sub-region empty with no
    error — a dead end mid-interview, with nothing to tell the
    enumerator which "Northern" was the wrong one.

#9  Six housing lists and two employment lists each carried a legacy
    single-digit frame merged with the UBOS 2024 frame, so the wizard
    offered "Detached" (1) beside "Detached house (Bungalow)" (11),
    "Hut" twice, "Iron sheets" twice. Two enumerators coding the same
    hut produced different values.

These assert the post-migration state, so they also assert that
migrations 0018 and 0019 ran — which is what a fresh environment needs
to be true.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from apps.reference_data.api import _build_bundle
from apps.reference_data.legacy_code_frames import (
    AMBIGUOUS,
    CODED_FIELDS,
    EXACT,
    legacy_codes,
)
from apps.reference_data.models import ChoiceList, ChoiceOption, GeographicUnit

SEED = (
    Path(__file__).resolve().parent / "seeds" / "choice_lists_v1.json"
)


def _migration_0019():
    """The migration module, imported by name — its filename starts with
    a digit, so it is not a valid identifier for a plain import."""
    import importlib
    return importlib.import_module(
        "apps.reference_data.migrations.0019_retire_legacy_code_frames",
    )


@pytest.fixture
def employment_rows(db):
    """Two Employment rows carrying the legacy frame: one on a code with
    an exact UBOS counterpart, one on a code with none."""
    from datetime import date as _date

    from apps.data_management.models import Employment, Household, Member

    parent = None
    for level, code in [
        ("region", "CF-R"), ("sub_region", "CF-SR"), ("district", "CF-D"),
        ("county", "CF-C"), ("sub_county", "CF-SC"), ("parish", "CF-P"),
    ]:
        parent = GeographicUnit.objects.create(
            level=level, code=code, name=code, parent=parent,
            effective_from=_date(2026, 1, 1),
        )
    ladder = {u.level: u for u in GeographicUnit.objects.filter(code__startswith="CF-")}
    household = Household.objects.create(
        region=ladder["region"], sub_region=ladder["sub_region"],
        district=ladder["district"], county=ladder["county"],
        sub_county=ladder["sub_county"], parish=ladder["parish"],
    )
    rows = []
    for line, kwargs in enumerate([
        {"work_frequency": "1"},           # Full-time -> exact
        {"not_working_reason": "2"},       # Household duties -> ambiguous
    ], start=1):
        member = Member.objects.create(
            household=household, line_number=line,
            surname="Test", first_name=f"P{line}",
        )
        rows.append(Employment.objects.create(member=member, **kwargs))
    return tuple(rows)


# ---------------------------------------------------------------------------
# #8 — the duplicate region.


@pytest.mark.django_db
class TestOneNorthernRegion:
    def test_ug_n_is_retired(self):
        dup = GeographicUnit.objects.filter(level="region", code="UG-N").first()
        if dup is None:
            return  # never seeded in this environment
        assert dup.status == "retired"

    def test_no_two_active_regions_share_a_name(self):
        names = Counter(
            GeographicUnit.objects
            .filter(level="region", status="active")
            .values_list("name", flat=True)
        )
        duplicated = [n for n, c in names.items() if c > 1]
        assert not duplicated, (
            f"regions with more than one active row: {duplicated} — an "
            "enumerator cannot tell them apart in the dropdown"
        )

    def test_no_active_region_is_a_dead_end(self):
        """An active region with no active sub-region under it is
        exactly the trap UG-N was: selectable, then nothing."""
        stranded = []
        for region in GeographicUnit.objects.filter(level="region", status="active"):
            has_children = GeographicUnit.objects.filter(
                parent=region, level="sub_region", status="active",
            ).exists()
            if not has_children:
                stranded.append(region.code)
        assert not stranded, (
            f"active regions with no selectable sub-region: {stranded}"
        )

    def test_no_household_was_orphaned_by_the_retirement(self):
        dup = GeographicUnit.objects.filter(level="region", code="UG-N").first()
        if dup is None:
            return
        from apps.data_management.models import Household
        assert not Household.objects.filter(region=dup).exists()


# ---------------------------------------------------------------------------
# #9 — the merged code frames.


@pytest.mark.django_db
class TestOneCodeFrame:
    def _active(self, list_name):
        choice_list = (
            ChoiceList.objects.filter(list_name=list_name)
            .order_by("-version").first()
        )
        if choice_list is None:
            pytest.skip(f"{list_name} not seeded in this environment")
        return list(choice_list.options.filter(
            status=ChoiceOption.Status.ACTIVE, language="en",
        ))

    @pytest.mark.parametrize("list_name", sorted(EXACT))
    def test_no_legacy_code_is_selectable(self, list_name):
        selectable = {o.code for o in self._active(list_name)}
        survivors = selectable & legacy_codes(list_name)
        assert not survivors, (
            f"{list_name} still offers retired codes {sorted(survivors)}"
        )

    @pytest.mark.parametrize("list_name", sorted(EXACT))
    def test_no_two_selectable_options_share_a_label(self, list_name):
        labels = Counter(o.label.strip().casefold() for o in self._active(list_name))
        duplicated = sorted(label for label, n in labels.items() if n > 1)
        assert not duplicated, (
            f"{list_name} offers duplicate labels {duplicated} — an "
            "enumerator has no way to choose between them"
        )

    @pytest.mark.parametrize("list_name", sorted(EXACT))
    def test_what_survives_is_exactly_the_ubos_frame(self, list_name):
        seeded = {o["code"] for o in json.loads(SEED.read_text())[list_name]}
        selectable = {o.code for o in self._active(list_name)}
        assert selectable == seeded, (
            f"{list_name} selectable={sorted(selectable)} "
            f"seeded={sorted(seeded)}"
        )

    @pytest.mark.parametrize("list_name", sorted(EXACT))
    def test_any_legacy_code_present_is_deprecated_not_deleted(self, list_name):
        """Wherever a legacy row survives — it does on environments that
        carried the old seed — it must be `deprecated`, never deleted: a
        household answered under the old frame has to stay
        interpretable (ChoiceOption docstring, ADR-0010).

        A fresh database was never seeded with the legacy frame, so
        there is nothing to assert there; migration behaviour itself is
        covered by TestMigrationBehaviour below, which builds the
        two-frame state and runs the migration over it.
        """
        choice_list = (
            ChoiceList.objects.filter(list_name=list_name)
            .order_by("-version").first()
        )
        present = choice_list.options.filter(code__in=legacy_codes(list_name))
        for option in present:
            assert option.status == ChoiceOption.Status.DEPRECATED, (
                f"{list_name}:{option.code} is {option.status}"
            )

    def test_the_bundle_the_wizard_fetches_carries_one_frame(self):
        """The dropdowns read _build_bundle, not the table. This is the
        assertion that actually matches what the operator sees."""
        from datetime import date as _date

        bundle = _build_bundle(
            as_of=_date.today(), lang="en", names=sorted(EXACT),
        )
        for entry in bundle["lists"]:
            codes = {o["code"] for o in entry["options"]}
            leftover = codes & legacy_codes(entry["list_name"])
            assert not leftover, (
                f"{entry['list_name']} bundle still serves "
                f"{sorted(leftover)} to the wizard"
            )
            labels = Counter(o["label"].strip().casefold() for o in entry["options"])
            assert not [x for x, n in labels.items() if n > 1], (
                f"{entry['list_name']} bundle has duplicate labels"
            )


# ---------------------------------------------------------------------------
# The mapping itself.


class TestLegacyMapping:
    def test_no_code_is_both_exact_and_ambiguous(self):
        for list_name in EXACT:
            overlap = set(EXACT[list_name]) & set(AMBIGUOUS.get(list_name, {}))
            assert not overlap, f"{list_name}: {sorted(overlap)}"

    def test_every_exact_target_is_a_real_ubos_code(self):
        seed = json.loads(SEED.read_text())
        for list_name, mapping in EXACT.items():
            valid = {o["code"] for o in seed[list_name]}
            for legacy, ubos in mapping.items():
                assert ubos in valid, (
                    f"{list_name}: {legacy} -> {ubos}, which is not in the "
                    "UBOS 2024 frame"
                )

    def test_every_ambiguous_code_says_why(self):
        for list_name, entries in AMBIGUOUS.items():
            for code, reason in entries.items():
                assert reason and len(reason) > 20, (
                    f"{list_name}:{code} has no usable explanation — the "
                    "next person has to be able to act on this"
                )

    def test_every_coded_field_exists_on_its_model(self):
        from django.apps import apps as global_apps
        for app_label, model_name, field_name, list_name in CODED_FIELDS:
            model = global_apps.get_model(app_label, model_name)
            assert any(f.name == field_name for f in model._meta.fields), (
                f"{model_name}.{field_name} does not exist"
            )
            assert list_name in EXACT, f"{list_name} is not an affected list"

    def test_version_tables_are_covered(self):
        """A household's history has to read the same way as its current
        row, so every base model in the mapping needs its *Version
        counterpart there too."""
        by_model = {m for _, m, _, _ in CODED_FIELDS}
        for model_name in list(by_model):
            if model_name.endswith("Version"):
                continue
            assert f"{model_name}Version" in by_model, (
                f"{model_name} is remapped but {model_name}Version is not"
            )


@pytest.mark.django_db
class TestMigrationBehaviour:
    """Build the two-frame state the dev and production databases are
    actually in, run the migration's own function over it, and check
    what it does — the assertion a fresh database cannot make, because
    it never had a legacy frame to retire.
    """

    def _rebuild_legacy_frame(self, list_name):
        choice_list = (
            ChoiceList.objects.filter(list_name=list_name)
            .order_by("-version").first()
        )
        for code in sorted(legacy_codes(list_name)):
            ChoiceOption.objects.update_or_create(
                choice_list=choice_list, code=code, language="en",
                defaults={
                    "label": f"legacy {code}",
                    "status": ChoiceOption.Status.ACTIVE,
                },
            )
        return choice_list

    def test_it_deprecates_the_legacy_frame_and_keeps_the_ubos_one(self):
        from django.apps import apps as global_apps

        choice_list = self._rebuild_legacy_frame("work_frequency")
        assert choice_list.options.filter(
            status=ChoiceOption.Status.ACTIVE,
        ).count() > 5, "the two-frame state was not rebuilt"

        _migration_0019()._retire_legacy_frames(global_apps, None)

        active = {
            o.code for o in choice_list.options.filter(
                status=ChoiceOption.Status.ACTIVE,
            )
        }
        assert active == {"01", "02", "03", "04", "05"}
        # Retired, not removed.
        for code in legacy_codes("work_frequency"):
            option = choice_list.options.get(code=code, language="en")
            assert option.status == ChoiceOption.Status.DEPRECATED

    def test_it_rewrites_stored_values_for_the_exact_pairs(self, employment_rows):
        from django.apps import apps as global_apps

        self._rebuild_legacy_frame("work_frequency")
        self._rebuild_legacy_frame("not_working_reason")

        _migration_0019()._retire_legacy_frames(global_apps, None)

        exact, ambiguous = employment_rows
        exact.refresh_from_db()
        ambiguous.refresh_from_db()
        # "Full-time" (1) -> "Full time - permanent work" (01).
        assert exact.work_frequency == "01"
        # "Household duties" (2) has no UBOS counterpart. Left alone —
        # writing a guess here would put an answer nobody gave into a
        # household's record, and from there into its PMT score.
        assert ambiguous.not_working_reason == "2"


@pytest.mark.django_db
class TestNoRowsLeftOnAnExactLegacyCode:
    def test_migration_0019_left_nothing_behind(self):
        """Rows on an AMBIGUOUS code are the documented backlog
        (`manage.py report_legacy_choice_codes`). Rows on an EXACT one
        mean the rewrite missed them."""
        from django.apps import apps as global_apps
        stranded = {}
        for app_label, model_name, field_name, list_name in CODED_FIELDS:
            mapping = EXACT.get(list_name) or {}
            if not mapping:
                continue
            model = global_apps.get_model(app_label, model_name)
            n = model.objects.filter(**{f"{field_name}__in": list(mapping)}).count()
            if n:
                stranded[f"{model_name}.{field_name}"] = n
        assert not stranded, stranded
