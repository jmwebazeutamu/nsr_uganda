"""One vocabulary for DSA field groups.

A Data Sharing Agreement grants by **group**; a data request names
**field paths**. `DataRequestFieldDefinition` in the canonical Data
Dictionary is the only maintained mapping between the two, so the
groups come from it.

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

The vocabulary moved into the canonical Data Dictionary in
`intake.0012`: `DataRequestFieldDefinition.disclosure_group` is where a
field's disclosure classification lives, bound to the `FormQuestion`
that collects it and the `ChoiceList` that constrains it. These tests
read it through `builder_schema.field_catalogue()`, which is a
**database read** — so every assertion about the vocabulary needs the
database, and every one of them has to prove the registry is populated
before concluding anything from it. An empty registry makes "no group
spans two entities" true and meaningless.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from apps.data_requests import field_groups
from apps.data_requests.builder_schema import field_catalogue

DESIGN = Path("design")

#: The files that used to carry their own copy.
CONSOLE_SCOPE_PICKERS = (
    DESIGN / "v0.1/screens/screens-dsas.jsx",
    DESIGN / "v0.1/components/scope-edit-modal.jsx",
)


@pytest.mark.django_db
class TestTheGroupsComeFromTheRegistry:

    def test_the_registry_is_populated(self):
        """Every case below reads the Data Dictionary. On an empty one
        they all pass and none of them mean anything — `set() == set()`
        proves nothing about a vocabulary."""
        from apps.intake.models import DataRequestFieldDefinition

        assert DataRequestFieldDefinition.objects.filter(is_active=True).exists(), (
            "no active DataRequestFieldDefinition rows — intake.0012 seeds "
            "them, and without them no DSA can grant anything"
        )
        assert len(field_catalogue()) > 50, (
            "the catalogue is implausibly small; the tests below would "
            "pass on it without checking anything"
        )

    def test_every_field_has_a_disclosure_group(self):
        ungrouped = [f["key"] for f in field_catalogue() if not f.get("group")]
        assert ungrouped == [], (
            f"{ungrouped} can be requested but belong to no group, so no "
            "DSA can grant them and every request for them is refused"
        )

    def test_the_vocabulary_is_derived_not_listed(self):
        """`canonical_groups()` must be the registry's own answer, not a
        list maintained beside it."""
        from apps.intake.models import DataRequestFieldDefinition

        from_registry = {
            d.disclosure_group
            for d in DataRequestFieldDefinition.objects.filter(is_active=True)
            if d.disclosure_group
        }
        assert set(field_groups.canonical_groups()) == from_registry

    def test_no_group_spans_two_entities(self):
        """The property "household fields yes, member fields no" is only
        expressible while this holds — and the DRS end-to-end fixture
        depends on it."""
        spread: dict[str, set[str]] = {}
        for field in field_catalogue():
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

    @pytest.mark.django_db
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


@pytest.mark.django_db
class TestLegacyAgreementsStillMeanSomething:
    """`normalise` resolves against the registry, so these need the
    database even though they look like pure string work."""


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


@pytest.mark.django_db
class TestTheCanonicalPathEndToEnd:
    """A field's disclosure group, from the Data Dictionary to the
    refusal a partner reads.

    The pieces are each tested above. This walks the whole path,
    because the defect that started all of this was not in any one
    piece — it was that two of them held different vocabularies and
    nothing compared them.
    """

    def _dsa(self, granted: dict):
        from datetime import date

        from apps.partners.models import DataSharingAgreement, Partner

        partner = Partner.objects.create(code="E2E-GRP", name="Group Partner")
        return DataSharingAgreement.objects.create(
            partner=partner, reference="DSA-GROUPS-1", version=1,
            field_scope=granted,
            effective_from=date(2026, 1, 1), effective_to=date(2030, 12, 31),
        )

    def test_a_granted_group_lets_its_fields_through(self):
        """The canonical path: registry says which group a field is in,
        the DSA grants that group, the request is allowed."""
        from apps.data_requests.services import _requested_field_groups
        from apps.intake.models import DataRequestFieldDefinition

        definition = (
            DataRequestFieldDefinition.objects
            .filter(is_active=True).exclude(disclosure_group="")
            .order_by("registry_path").first()
        )
        assert definition is not None, "registry is empty; see the guard above"

        dsa = self._dsa({definition.disclosure_group: True})
        requested = _requested_field_groups([definition.registry_path])

        assert requested == {definition.disclosure_group}
        allowed = {k for k, v in (dsa.field_scope or {}).items() if v}
        assert requested <= allowed, (
            f"{definition.registry_path} resolves to "
            f"{requested}, which the DSA granting "
            f"{allowed} does not cover"
        )

    def test_a_group_the_agreement_does_not_grant_is_refused(self):
        """The failure case, and the one that was reported as a bug:
        the refusal must name the group, so the operator can see it is
        a scope question and not a malformed request."""
        from apps.data_requests.services import DrsError, validate_against_dsa
        from apps.intake.models import DataRequestFieldDefinition

        groups = [g for g in field_groups.canonical_groups()]
        assert len(groups) >= 2, "need two groups to grant one and refuse the other"
        granted, withheld = groups[0], groups[1]

        wanted = (
            DataRequestFieldDefinition.objects
            .filter(is_active=True, disclosure_group=withheld)
            .order_by("registry_path").first()
        )
        assert wanted is not None

        dsa = self._dsa({granted: True})
        with pytest.raises(DrsError) as exc:
            validate_against_dsa({"fields": [wanted.registry_path]}, dsa)

        assert withheld in str(exc.value), (
            f"the refusal does not name {withheld!r}: {exc.value}"
        )

    def test_retiring_a_definition_removes_its_group_from_the_vocabulary(self):
        """`is_active` on the definition is what makes a field
        requestable. Retiring the last field in a group must take the
        group out of what a DSA can grant — otherwise an agreement can
        be written granting something nothing resolves to, which is the
        original defect in a new costume.
        """
        from apps.intake.models import DataRequestFieldDefinition

        counts: dict[str, int] = {}
        for d in DataRequestFieldDefinition.objects.filter(is_active=True):
            counts[d.disclosure_group] = counts.get(d.disclosure_group, 0) + 1
        singletons = [g for g, n in counts.items() if n == 1]
        if not singletons:
            pytest.skip("no single-field group to retire in this registry")

        group = singletons[0]
        assert group in field_groups.canonical_groups()

        DataRequestFieldDefinition.objects.filter(
            disclosure_group=group,
        ).update(is_active=False)

        assert group not in field_groups.canonical_groups()
        assert field_groups.normalise({group: True}) == {}, (
            "a retired group can still be granted, and nothing will "
            "resolve it"
        )


@pytest.mark.django_db
class TestTheDescriptionsAreAKnownGap:
    """`field_groups.DESCRIPTIONS` is a hardcoded dict.

    It is the operator-facing sentence beside each checkbox in the
    scope picker — "Geography: Region through village, and the GPS
    point". It has no column: `DataRequestFieldDefinition` carries the
    field's classification, not a sentence about the group, and
    `ChoiceList.description` describes a code frame.

    Reported rather than invented. A description table for fourteen
    sentences would be a parallel structure for a concept nobody has
    asked to make configurable. What must not happen is the dict
    quietly becoming a second vocabulary — so it is checked against the
    registry rather than left to drift.
    """

    def test_no_description_names_a_group_that_does_not_exist(self):
        stale = sorted(
            set(field_groups.DESCRIPTIONS) - set(field_groups.canonical_groups())
        )
        assert stale == [], (
            f"{stale} have descriptions but are not groups any more — the "
            "dict is drifting from the registry"
        )

    def test_a_group_without_a_description_still_works(self):
        """A missing sentence is a missing sentence, not a missing
        feature. The picker shows the bare group name."""
        entry = next(
            g for g in field_groups.catalogue()
            if g["key"] in field_groups.canonical_groups()
        )
        assert entry["label"]
        assert "description" in entry
