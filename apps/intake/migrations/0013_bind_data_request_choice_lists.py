"""Bind migrated DRS enum definitions to canonical ChoiceLists.

Definitions without an authoritative option source are disabled.  That is a
deliberate fail-closed rule: a stale inline list must never become a selectable
request predicate.
"""

from django.db import migrations


def bind_choice_lists(apps, schema_editor):
    from apps.data_management import choice_field_map

    Definition = apps.get_model("intake", "DataRequestFieldDefinition")
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    active_lists = {
        row.list_name: row
        for row in ChoiceList.objects.filter(status="active").order_by("-version")
    }
    bindings = {
        "household": choice_field_map.HOUSEHOLD_FIELDS,
        "member": choice_field_map.MEMBER_FIELDS,
    }

    for definition in Definition.objects.filter(data_type__in=("enum", "enum-multi")):
        if definition.choice_list_ref_id or definition.options_source:
            continue
        root, _, field = definition.registry_path.partition(".")
        binding = bindings.get(root, {}).get(field)
        choice_list = active_lists.get(binding[0]) if binding else None
        if choice_list is None:
            definition.is_active = False
            definition.save(update_fields=["is_active", "updated_at"])
            continue
        definition.choice_list_ref_id = choice_list.id
        definition.save(update_fields=["choice_list_ref", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("intake", "0012_datarequestfielddefinition"),
    ]

    operations = [
        migrations.RunPython(bind_choice_lists, migrations.RunPython.noop),
    ]
