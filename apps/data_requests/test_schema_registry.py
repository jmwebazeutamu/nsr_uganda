"""Regression tests for the canonical DRS disclosure schema."""

from datetime import date

import pytest

from apps.data_requests.builder_schema import field_catalogue
from apps.intake.models import DataRequestFieldDefinition
from apps.reference_data.models import ChoiceList, ChoiceListStatus


@pytest.mark.django_db
def test_drs_catalogue_reads_only_active_dictionary_definitions():
    """A retired definition must disappear even if the former bootstrap
    module still contains an entry with the same key."""
    DataRequestFieldDefinition.objects.update(is_active=False)
    DataRequestFieldDefinition.objects.create(
        registry_path="household.canonical_test_field",
        label="Canonical test field",
        data_type="text",
        disclosure_group="Test disclosure",
        privacy_class="Internal",
        is_active=True,
    )

    assert field_catalogue() == [{
        "group": "Test disclosure",
        "key": "household.canonical_test_field",
        "label": "Canonical test field",
        "sensitivity": "Internal",
        "type": "text",
    }]


@pytest.mark.django_db
def test_drs_catalogue_uses_the_definition_choice_list_not_inline_options():
    choice_list = ChoiceList.objects.create(
        list_name="drs_registry_test",
        version=1,
        status=ChoiceListStatus.ACTIVE,
        author="test",
        effective_from=date(2026, 1, 1),
    )
    definition = DataRequestFieldDefinition.objects.create(
        registry_path="household.canonical_choice_test",
        label="Canonical choice test",
        data_type="enum",
        disclosure_group="Test disclosure",
        privacy_class="Internal",
        choice_list_ref=choice_list,
    )

    item = next(field for field in field_catalogue() if field["key"] == definition.registry_path)
    assert item["options_source"] == "choice_list?name=drs_registry_test"
    assert "options" not in item
