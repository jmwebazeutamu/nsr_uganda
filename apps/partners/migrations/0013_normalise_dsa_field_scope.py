"""Put every DSA's field_scope into the catalogue's vocabulary.

`field_scope` grants by group. The console wrote `Roster`, `Housing`
and `FoodShocks`; the request validator resolves a requested field to
its group through `builder_schema.FIELD_CATALOGUE`, which calls those
`Members`, `Dwelling` + `Utilities`, and `Food consumption` + `Food
security`.

So an agreement granting `Roster` did not authorise `member.surname`.
The partner's request was refused as "outside DSA scope" — for a group
their agreement did grant, in wording that blames them for it.

`Housing` and `FoodShocks` each covered two catalogue groups, so they
**expand** rather than rename. Narrowing a signed agreement is not a
migration's decision to make; if the expansion is wider than intended,
that is an amendment for the DSA owner to make deliberately.

Names that resolve to nothing are dropped. A grant nothing can look up
authorises nothing, and leaving it makes the agreement read wider than
it is.
"""

from django.db import migrations


def normalise(apps, schema_editor):
    from apps.data_requests.field_groups import normalise as to_canonical

    DataSharingAgreement = apps.get_model("partners", "DataSharingAgreement")
    for dsa in DataSharingAgreement.objects.exclude(field_scope={}).iterator():
        before = dsa.field_scope or {}
        after = to_canonical(before)
        if after != before:
            dsa.field_scope = after
            dsa.save(update_fields=["field_scope"])


def unnormalise(apps, schema_editor):
    """Not reversible in any useful sense: `Housing` expanded into two
    groups and there is no way to tell, afterwards, which agreements
    had been written the old way. Left as a no-op rather than guessing
    a narrower scope onto a signed agreement."""


class Migration(migrations.Migration):
    dependencies = [
        ("partners", "0012_rebind_opm_legacy_drafts"),
    ]
    operations = [migrations.RunPython(normalise, unnormalise)]
