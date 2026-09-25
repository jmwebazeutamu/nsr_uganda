"""One vocabulary for DSA field groups.

A Data Sharing Agreement grants by **group**; a data request names
**field paths**. `builder_schema.FIELD_CATALOGUE` is the only
maintained mapping between the two, so the groups come from it.

They did not. Three files listed them and the three disagreed:

    catalogue          Members   Dwelling  Utilities  Food consumption
                                                      Food security
    screens-dsas.jsx   Roster    Housing              FoodShocks
    scope-edit-modal   Roster    Housing              FoodShocks

An agreement written in the console granted `Roster`; the validator
resolved `member.surname` to `Members`, did not find it, and refused
the partner's request as **"outside DSA scope"** — for a group their
agreement did grant, in wording that blamed them for asking.

And `Geography` was never on the console's list, so no agreement
written through the UI could grant a partner the household's location.
That is what the end-to-end DRS test was failing on.

Two agreements in production were written in the old vocabulary.
Migration `partners.0013` moved them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from apps.data_requests import field_groups
from apps.data_requests.builder_schema import FIELD_CATALOGUE

DESIGN = Path("design")

#: The files that used to carry their own copy.
CONSOLE_SCOPE_PICKERS = (
    DESIGN / "v0.1/screens/screens-dsas.jsx",
    DESIGN / "v0.1/components/scope-edit-modal.jsx",
)


class TestTheGroupsComeFromTheCatalogue:

    def test_every_catalogue_field_has_a_group(self):
        ungrouped = [f["key"] for f in FIELD_CATALOGUE if not f.get("group")]
        assert ungrouped == [], (
            f"{ungrouped} can be requested but belong to no group, so no "
            "DSA can grant them and every request for them is refused"
        )

    def test_the_vocabulary_is_derived_not_listed(self):
        assert set(field_groups.canonical_groups()) == {
            f["group"] for f in FIELD_CATALOGUE
        }

    def test_no_group_spans_two_entities(self):
        """The property "household fields yes, member fields no" is only
        expressible while this holds — and the DRS end-to-end fixture
        depends on it."""
        spread: dict[str, set[str]] = {}
        for field in FIELD_CATALOGUE:
            spread.setdefault(field["group"], set()).add(
                str(field["key"]).partition(".")[0],
            )
        straddling = {g: sorted(e) for g, e in spread.items() if len(e) > 1}
        assert straddling == {}, (
            f"{straddling} span more than one entity — a DSA can no longer "
            "grant one entity's fields without the other's"
        )


class TestTheConsoleDoesNotKeepItsOwnCopy:

    @pytest.mark.parametrize("page", CONSOLE_SCOPE_PICKERS, ids=lambda p: p.name)
    def test_it_asks_the_server(self, page):
        assert "useFieldGroups()" in page.read_text(), (
            f"{page} renders a scope picker without asking the server "
            "which groups exist"
        )

    @pytest.mark.parametrize("page", CONSOLE_SCOPE_PICKERS, ids=lambda p: p.name)
    @pytest.mark.parametrize("stale", ["Roster", "Housing", "FoodShocks"])
    def test_the_old_names_are_gone_from_the_pickers(self, page, stale):
        """Not a search of the whole file — these names are legitimately
        discussed in comments explaining the correction. What must not
        come back is a list ENTRY."""
        text = page.read_text()
        for pattern in (rf'key:\s*"{stale}"', rf'\["{stale}",'):
            assert not re.search(pattern, text), (
                f"{page} lists {stale!r} again — the validator has never "
                "known that name"
            )

    def test_no_other_console_file_hardcodes_the_vocabulary(self):
        """A fourth copy somewhere else is the same defect in a new
        place.

        Scoped to files that actually deal with `field_scope`. The
        words themselves are ordinary — the household detail screen has
        tabs called Members, Education and Dwelling, and those are tab
        labels, not grants. What matters is a file that writes a DSA's
        field scope while holding its own idea of what the groups are.
        """
        groups = set(field_groups.canonical_groups())
        offenders = {}
        for path in DESIGN.rglob("*.jsx"):
            if path.name.endswith(".test.jsx") or path in CONSOLE_SCOPE_PICKERS:
                continue
            text = path.read_text()
            if "field_scope" not in text:
                continue
            found = {g for g in groups if f'"{g}"' in text}
            if len(found) >= 3:
                offenders[str(path)] = sorted(found)
        assert offenders == {}, (
            f"{offenders} write a DSA field scope while naming the groups "
            "themselves — ask the server, as the pickers do"
        )


class TestLegacyAgreementsStillMeanSomething:

    def test_every_alias_targets_a_real_group(self):
        known = set(field_groups.canonical_groups())
        for old, new in field_groups.LEGACY_ALIASES.items():
            unknown = [g for g in new if g not in known]
            assert unknown == [], f"{old} maps to {unknown}, which do not exist"

    def test_a_legacy_grant_is_not_narrowed(self):
        """`Housing` covered dwelling AND utilities. Renaming it to one
        of them would quietly take access away from a signed
        agreement."""
        out = field_groups.normalise({"Housing": True})
        assert out == {"Dwelling": True, "Utilities": True}

    def test_a_legacy_denial_stays_a_denial(self):
        assert field_groups.normalise({"Roster": False}) == {"Members": False}

    def test_a_name_nothing_resolves_is_dropped(self):
        """A grant nothing can look up authorises nothing, and keeping
        it makes the agreement read wider than it is."""
        assert field_groups.normalise({"Nonsense": True}) == {}
        assert field_groups.unknown_groups({"Nonsense": True}) == ["Nonsense"]

    def test_canonical_names_pass_through(self):
        assert field_groups.normalise({"Geography": True}) == {"Geography": True}


@pytest.mark.django_db
class TestTheDataAgrees:

    def test_no_agreement_grants_a_group_that_does_not_exist(self):
        """The health check migration 0013 exists to satisfy. A DSA
        granting an unresolvable group refuses requests it should
        allow, and the refusal blames the partner."""
        from apps.partners.models import DataSharingAgreement

        offenders = {
            dsa.reference: field_groups.unknown_groups(dsa.field_scope)
            for dsa in DataSharingAgreement.objects.all()
            if field_groups.unknown_groups(dsa.field_scope)
        }
        assert offenders == {}, (
            f"{offenders} grant groups the catalogue cannot resolve — run "
            "the normalisation in partners/0013"
        )


@pytest.mark.django_db
class TestTheEndpointServesIt:

    def test_it_returns_the_canonical_groups(self, client, django_user_model):
        from rest_framework.test import APIClient

        user = django_user_model.objects.create_user(username="dsa.admin",
                                                     password="p")
        api = APIClient()
        api.force_authenticate(user=user)

        r = api.get("/api/v1/drs/requests/field-groups/")
        assert r.status_code == 200, r.data
        served = [g["key"] for g in r.data["groups"]]
        assert served == field_groups.canonical_groups()

    def test_each_group_says_how_much_it_grants(self, django_user_model):
        """"Geography (11 fields)" is the difference between an informed
        grant and a guess."""
        from rest_framework.test import APIClient

        user = django_user_model.objects.create_user(username="dsa.admin2",
                                                     password="p")
        api = APIClient()
        api.force_authenticate(user=user)

        groups = api.get("/api/v1/drs/requests/field-groups/").data["groups"]
        assert all(g["field_count"] > 0 for g in groups)
        assert all(g["entities"] for g in groups)
