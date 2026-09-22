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
from apps.intake.canonical_fields import CAPTURE_METADATA, QUESTION_TO_CANONICAL
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
        unknown = sorted(set(QUESTION_TO_CANONICAL) - names)
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
    def test_the_fields_the_review_screen_needs_resolve(self):
        """The keys the old hardcoded maps carried are exactly the keys
        the screen renders. Every one that the instrument genuinely asks
        must now resolve from the registry."""
        dictionary = build_field_dictionary().as_dict()
        fields = dictionary["fields"]
        # A representative slice, deliberately including the four the
        # prefix-stripping heuristic would have got wrong.
        must_resolve = {
            "wall_material": "g6_wall_material",
            "sleeping_rooms": "g4_rooms_sleeping",   # words swap
            "land_title": "h8_title_deed",           # different words
            "contact_phone": "b2_telephone_number",  # different words
            "start": "a15_start_time",               # different words
            "cooking_fuel": "g8_cooking_fuel",
            "water_source": "g10_water_source",
            "toilet_type": "g11_toilet_type",
            "literacy_status": "e1_literacy",
            "main_activity_last_30d": "f1_main_job",
            "sex": "c4_sex",
            "marital_status": "c3_marital_status",
        }
        for canonical, question_name in must_resolve.items():
            assert canonical in fields, f"{canonical} does not resolve"
            assert fields[canonical]["question_name"] == question_name, (
                f"{canonical} resolves to {fields[canonical]['question_name']}, "
                f"expected {question_name}"
            )
            assert fields[canonical]["label"], f"{canonical} has an empty label"

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

    def test_capture_metadata_is_labelled_and_marked_as_such(self):
        """Fields the channel emits are not questions. They still need
        labels, but the screen must be able to say they were not asked."""
        fields = build_field_dictionary().as_dict()["fields"]
        for name in CAPTURE_METADATA:
            assert name in fields, f"{name} has no label at all"
            assert fields[name]["source"] == "capture-metadata"
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

    def test_an_unknown_form_version_is_404_not_a_silent_default(
        self, client, django_user_model,
    ):
        """Falling back to the active instrument for a version that does
        not exist would label a record against the wrong questionnaire."""
        user = django_user_model.objects.create_user(username="dict-reader2", password="pw")
        client.force_login(user)
        response = client.get(reverse("field-dictionary"), {"form_version": 9999})
        assert response.status_code == 404
