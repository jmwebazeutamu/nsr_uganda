"""The field dictionary contract.

The household review screen used to carry its own field vocabulary: a
39-entry label map and a 27-entry field-to-choice-list map, maintained by
hand beside an instrument that already defined all of it. That is the
same defect this project has now found seven times — two vocabularies for
one concept, drifting apart — and the only thing that has ever caught it
is a test that asserts on both originals at once.

So these tests assert against the registry AND against the payload keys
the DIH connectors actually emit. A label that exists only in the console,
or a canonical field that maps to no question, fails here.
"""

import pytest
from django.urls import reverse

from apps.dqa.models import DqaRule, RuleStatus
from apps.intake.canonical_fields import (
    DERIVED_FIELDS, QUESTION_ALIASES, QUESTION_TO_CANONICAL,
)
from apps.intake.field_dictionary import build_field_dictionary, strip_question_code
from apps.intake.models import FormQuestion, FormVersion


@pytest.fixture(autouse=True)
def instrument(db):
    """Load the real v1 instrument into the test database.

    These are contract tests over the actual questionnaire, so a
    hand-built two-question fixture would prove nothing: the defect being
    guarded against is a mapping that does not match the real form.

    The snapshot rather than scripts/import_legacy_questionnaire.py,
    because that script reads k-forms/build_nsr_xlsform.py, which is not
    in the repository — the instrument sitting in the databases today
    cannot be rebuilt from a clean checkout. instrument_v1.json is that
    instrument, captured so that it can be.
    """
    from django.core.management import call_command

    call_command("load_instrument", quiet=True)


@pytest.mark.django_db
class TestCanonicalFieldSeeding:
    def test_every_mapped_question_exists_in_the_active_instrument(self):
        """A mapping entry for a question that does not exist is dead
        weight that will quietly stop being maintained."""
        active = FormVersion.objects.filter(is_active=True).first()
        assert active is not None, "no active FormVersion to map against"
        names = set(
            FormQuestion.objects
            .filter(section__form_version=active)
            .values_list("name", flat=True)
        )
        unknown = sorted(set(QUESTION_ALIASES) - names)
        assert not unknown, (
            f"canonical_fields.py maps questions that are not in the active "
            f"instrument: {unknown}"
        )

    def test_the_migration_actually_populated_the_column(self):
        seeded = FormQuestion.objects.exclude(canonical_field="").count()
        assert seeded > 0, (
            "no FormQuestion carries a canonical_field — migration "
            "0008_seed_canonical_fields did not run or did not match"
        )

    def test_canonical_field_matches_the_stated_mapping(self):
        for question in FormQuestion.objects.exclude(canonical_field=""):
            expected = QUESTION_TO_CANONICAL.get(question.name)
            if expected is None:
                # The L0x coping questions are mapped by prefix.
                assert question.name.startswith(("l01", "l02")), (
                    f"{question.name} has canonical_field "
                    f"{question.canonical_field!r} but no mapping rule "
                    f"produced it"
                )
                continue
            assert question.canonical_field == expected


@pytest.mark.django_db
class TestFieldDictionary:
    def test_both_producers_field_names_resolve_to_one_question(self):
        """The defect this whole mapping exists to stop.

        Kobo and the parish wizard name the same fields differently —
        rooms_sleeping vs sleeping_rooms, self_care vs selfcare, main_job
        vs main_activity_last_30d. The review screen's old hardcoded map
        held only the wizard's names, so every Kobo-shaped record showed
        raw keys and undecoded codes. Both names must now reach the same
        question, with the same label and the same choice list.
        """
        fields = build_field_dictionary().as_dict()["fields"]
        pairs = {
            "g4_rooms_sleeping": ("rooms_sleeping", "sleeping_rooms"),
            "g3_rooms_total": ("rooms_total", "total_rooms"),
            "g9_lighting_source": ("lighting_source", "lighting_energy"),
            "g10_water_source": ("water_source", "drinking_water_source"),
            "g11_toilet_type": ("toilet_type", "toilet_facility"),
            "g16_livelihood_source": ("livelihood_source", "main_livelihood"),
            "d6_remembering": ("remembering", "memory"),
            "d7_self_care": ("self_care", "selfcare"),
            "d8_communicating": ("communicating", "communication"),
            "e1_literacy": ("literacy", "literacy_status"),
            "f1_main_job": ("main_job", "main_activity_last_30d"),
            "f3_work_sector": ("work_sector", "sector"),
            "f4_work_status": ("work_status", "employment_status"),
            "f10_savings_place": ("savings_place", "savings_location"),
            "h4_ag_purpose": ("ag_purpose", "agricultural_purpose"),
        }
        for question_name, (kobo_key, wizard_key) in pairs.items():
            for key in (kobo_key, wizard_key):
                assert key in fields, (
                    f"{key} does not resolve — a {question_name} answer would "
                    f"render as a raw key with its code undecoded"
                )
                assert fields[key]["question_name"] == question_name
            assert fields[kobo_key]["label"] == fields[wizard_key]["label"], (
                f"{kobo_key} and {wizard_key} are the same question but "
                f"render different labels"
            )
            assert fields[kobo_key]["choice_list"] == fields[wizard_key]["choice_list"]

    def test_every_key_real_payloads_carry_resolves(self):
        """Assert against the payloads, not against a copy of the map.

        The previous mapping passed its own tests and still resolved
        nothing on real data, because it was built from the console's
        vocabulary rather than from what the connectors emit.
        """
        import json
        from pathlib import Path

        repo = Path(__file__).resolve().parent.parent.parent
        payloads = json.loads(
            (repo / "design" / "v0.1" / "data" / "fixtures"
             / "canonical-payloads.json").read_text()
        )
        fields = build_field_dictionary().as_dict()["fields"]

        def leaves(node, prefix="", out=None):
            out = [] if out is None else out
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(value, dict):
                        leaves(value, f"{prefix}{key}.", out)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                leaves(item, f"{prefix}{key}.", out)
                            else:
                                out.append((key, prefix))
                    else:
                        out.append((key, prefix))
            return out

        def resolves(key, prefix):
            if key in fields:
                return True
            # Kobo nests the food groups, so the parent segment
            # disambiguates "days" across nine of them.
            segments = [s for s in prefix.rstrip(".").split(".") if s]
            if segments and not segments[-1].isdigit():
                return f"{segments[-1]}_{key}" in fields
            return False

        for shape, payload in payloads.items():
            unresolved = sorted({
                key for key, prefix in leaves(payload)
                if key != "_fixture"
                and "_source_keys" not in prefix
                and not prefix.startswith("consent_block")
                and not resolves(key, prefix)
            })
            assert not unresolved, (
                f"{shape} payload carries {len(unresolved)} field(s) the "
                f"registry cannot name: {unresolved}"
            )

    def test_coded_fields_carry_their_choice_list(self):
        fields = build_field_dictionary().as_dict()["fields"]
        expected = {
            "wall_material": "wall_material",
            "cooking_fuel": "cooking_fuel",
            "water_source": "water_source",
            "toilet_type": "toilet_type",
            "sex": "sex",
            "marital_status": "marital_status",
            "land_title": "title_deed",
            "urban_rural": "rural_urban",
            "interview_result": "interview_result",
        }
        for canonical, list_name in expected.items():
            assert fields[canonical]["choice_list"] == list_name, (
                f"{canonical} decodes with "
                f"{fields[canonical]['choice_list']!r}, expected {list_name!r}"
            )

    def test_labels_come_from_the_instrument_not_from_the_console(self):
        """The whole point: change the question, change the screen."""
        question = FormQuestion.objects.get(
            name="g6_wall_material", section__form_version__is_active=True,
        )
        question.label = "G6. Main wall material (revised wording)"
        question.save(update_fields=["label"])

        fields = build_field_dictionary().as_dict()["fields"]
        assert fields["wall_material"]["label"] == "Main wall material (revised wording)"

    def test_derived_fields_are_labelled_and_marked_as_such(self):
        """Fields the connector produces are not questions. They still
        need labels, but the screen must be able to say they were not
        asked — first_name and surname are split out of C1 Full Name, and
        showing all three as "Full Name" would be worse than useless."""
        fields = build_field_dictionary().as_dict()["fields"]
        for name in DERIVED_FIELDS:
            assert name in fields, f"{name} has no label at all"
            assert fields[name]["source"] == "derived"
            assert fields[name]["question_name"] == ""

    def test_question_code_prefixes_are_stripped_for_display_only(self):
        assert strip_question_code("G6. Main wall material") == "Main wall material"
        assert strip_question_code("A11/A12. CAPI GPS Coordinates") == "CAPI GPS Coordinates"
        assert strip_question_code("L01.a Engage in casual labor") == "Engage in casual labor"
        # No prefix: unchanged.
        assert strip_question_code("Number of household members") == "Number of household members"
        # Never empty, even if the label is only a code.
        assert strip_question_code("G6.") == "G6."

    def test_the_full_question_text_survives_for_traceability(self):
        fields = build_field_dictionary().as_dict()["fields"]
        assert fields["wall_material"]["question_label"].startswith("G6."), (
            "the code prefix must remain available so a reviewer can find "
            "the question on the paper form"
        )


@pytest.fixture
def active_age_rules(db):
    """Seed the intra-household rules and activate the ones that carry
    the age boundaries.

    The seeder creates rules as DRAFT because they go through dual
    approval; the dictionary deliberately reads only ACTIVE rules, so a
    draft revision of AC-HOH-AGE cannot move a boundary on screen before
    it has been approved. Activating here is what an approver would do.
    """
    from scripts.seed_dqa_intra_household_rules import seed

    seed()
    DqaRule.objects.filter(
        rule_id__in=["AC-HOH-AGE", "AC-HOH-AGE-CHILD-LED", "AC-ORPHAN-FLAG"],
    ).update(status=RuleStatus.ACTIVE)


@pytest.mark.django_db
class TestRepeatBlockColumns:
    """A repeat block flattens many questions into a few columns.

    Every question in the block would otherwise claim the column name as
    an alias and the first one would win — so the shock_type column read
    "Main shock affecting crops" on the livestock row, and all eighteen
    coping strategies shared the label "Engage in casual labor". A column
    that names one of the things it holds is worse than one that names
    none.
    """

    def test_columns_are_named_for_the_column_not_the_first_question(self):
        fields = build_field_dictionary().as_dict()["fields"]
        expected = {
            "shock_type": "Shock type",
            "severity": "Severity of loss",
            "strategy_type": "Coping strategy",
            "frequency": "How often",
            "category": "Livelihood affected",
            "asset_type": "Asset",
        }
        for name, label in expected.items():
            assert fields[name]["label"] == label, (
                f"the {name} column reads {fields[name]['label']!r} — it has "
                f"inherited a question's label instead of naming the column"
            )
            assert fields[name]["source"] == "repeat-column"

    def test_columns_still_decode_through_their_list(self):
        """Naming the column must not cost the decoding."""
        fields = build_field_dictionary().as_dict()["fields"]
        assert fields["shock_type"]["choice_list"] == "shock_type"
        assert fields["severity"]["choice_list"] == "severity"
        assert fields["frequency"]["choice_list"] == "coping_frequency"
        assert fields["asset_type"]["choice_list"] == "asset_type"

    def test_each_coping_question_keeps_its_own_name(self):
        """Kobo keys each coping strategy by its question name, and all
        eighteen were reported "not in questionnaire" when the column
        aliases took over."""
        fields = build_field_dictionary().as_dict()["fields"]
        for name in [
            "l01a_casual_labor", "l01b_sell_assets", "l01c_borrow_money",
            "l01d_assistance_friends", "l01e_assistance_agencies",
            "l01f_remittances", "l01g_sand_gravel", "l01h_relocate",
            "l01i_begging", "l02a_less_preferred_food",
            "l02b_borrow_food_money", "l02c_reduce_portions",
            "l02d_reduce_meals", "l02e_restrict_adults",
            "l02f_day_without_eating", "l02g_wild_food",
            "l02h_merge_households", "l02i_begging",
        ]:
            assert name in fields, f"{name} reports as not in the questionnaire"
            assert fields[name]["source"] == "instrument"
            assert fields[name]["question_name"] == name
        # And they are eighteen DIFFERENT strategies, not one repeated.
        labels = {
            fields[n]["label"] for n in fields
            if n.startswith(("l01", "l02"))
        }
        assert len(labels) == 18, (
            f"only {len(labels)} distinct coping labels — the questions are "
            f"sharing a label again"
        )

    def test_a_label_collision_keeps_the_question_code(self):
        """L01.i and L02.i are both "Begging" once the code is stripped —
        one a livelihood response, one a food response. Two identical
        rows on a review screen is worse than a visible code."""
        fields = build_field_dictionary().as_dict()["fields"]
        assert fields["l01i_begging"]["label"] != fields["l02i_begging"]["label"]
        assert fields["l01i_begging"]["label"].startswith("L01")
        assert fields["l02i_begging"]["label"].startswith("L02")

    def test_a_label_that_does_not_collide_is_still_stripped(self):
        fields = build_field_dictionary().as_dict()["fields"]
        assert fields["l01a_casual_labor"]["label"] == "Engage in casual labor"


@pytest.mark.django_db
class TestThresholds:
    def test_thresholds_are_read_from_the_active_dqa_rules(self, active_age_rules):
        dictionary = build_field_dictionary().as_dict()
        assert dictionary["thresholds"]["head_min_age"] == 12
        assert dictionary["thresholds"]["child_max_age"] == 17
        assert dictionary["thresholds"]["orphan_max_age"] == 18

    def test_changing_the_rule_moves_the_threshold(self, active_age_rules):
        """These were literals in the console. Editing AC-HOH-AGE moved
        the boundary the engine enforced but not the one the composition
        panel drew; the two are now the same number."""
        rule = (
            DqaRule.objects
            .filter(rule_id="AC-HOH-AGE", status=RuleStatus.ACTIVE)
            .order_by("-version").first()
        )
        assert rule is not None
        rule.parameters = {**(rule.parameters or {}), "min_head_age": 15}
        rule.save(update_fields=["parameters"])

        assert build_field_dictionary().as_dict()["thresholds"]["head_min_age"] == 15

    def test_the_elderly_boundary_is_reported_missing_not_invented(self):
        """60 was a literal with no authority behind it. Until something
        in the registry defines it, the dictionary must say so rather
        than supply a number."""
        dictionary = build_field_dictionary().as_dict()
        assert dictionary["thresholds"]["elderly_min_age"] is None
        assert "elderly_min_age" in dictionary["missing_thresholds"]
        assert "AC-ELDERLY-HEAD" in dictionary["missing_thresholds"]["elderly_min_age"], (
            "the gap must name what would close it, or nobody will close it"
        )


@pytest.mark.django_db
class TestFieldDictionaryEndpoint:
    def test_it_requires_a_session(self, client):
        response = client.get(reverse("field-dictionary"))
        assert response.status_code in (302, 401, 403)

    def test_it_serves_the_dictionary(self, client, django_user_model, active_age_rules):
        user = django_user_model.objects.create_user(username="dict-reader", password="pw")
        client.force_login(user)
        response = client.get(reverse("field-dictionary"))
        assert response.status_code == 200
        body = response.json()
        assert body["form_version"] is not None
        assert body["fields"]["wall_material"]["choice_list"] == "wall_material"
        assert body["thresholds"]["head_min_age"] == 12
        assert "elderly_min_age" in body["missing_thresholds"]

    def test_it_serves_an_etag_and_honours_a_conditional_get(
        self, client, django_user_model,
    ):
        """Without this the client caches the dictionary for the life of
        the tab, so a corrected mapping never reaches an open console."""
        user = django_user_model.objects.create_user(username="etag", password="pw")
        client.force_login(user)
        first = client.get(reverse("field-dictionary"))
        assert first.status_code == 200
        etag = first["ETag"]
        assert etag

        again = client.get(reverse("field-dictionary"), HTTP_IF_NONE_MATCH=etag)
        assert again.status_code == 304

    def test_the_etag_changes_when_a_label_changes(self, client, django_user_model):
        user = django_user_model.objects.create_user(username="etag2", password="pw")
        client.force_login(user)
        before = client.get(reverse("field-dictionary"))["ETag"]

        question = FormQuestion.objects.get(
            name="g6_wall_material", section__form_version__is_active=True,
        )
        question.label = "G6. Main wall material (revised)"
        question.save(update_fields=["label"])

        after = client.get(reverse("field-dictionary"))["ETag"]
        assert before != after, (
            "the ETag did not move, so an open console would keep the old "
            "label until the tab was reloaded"
        )

    def test_an_unknown_form_version_is_404_not_a_silent_default(
        self, client, django_user_model,
    ):
        """Falling back to the active instrument for a version that does
        not exist would label a record against the wrong questionnaire."""
        user = django_user_model.objects.create_user(username="dict-reader2", password="pw")
        client.force_login(user)
        response = client.get(reverse("field-dictionary"), {"form_version": 9999})
        assert response.status_code == 404
