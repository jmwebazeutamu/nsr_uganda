"""`docs/ssot_agent_prompt.md` names real code.

The digest exists to be pasted into agent prompts, which means it is read
far from the code it describes and nobody notices when it goes stale. A
digest that points an agent at `apps.pmt.models.PMTBandThreshold` after
that class is renamed is worse than no digest: it sends the work
confidently to the wrong place.

So every symbol the digest cites is listed in `CITED` below and checked
BOTH ways:

  * it resolves in the codebase — the code has not been renamed out from
    under the digest;
  * it appears verbatim in the digest's paste block — the digest has not
    been edited away from this list.

A one-way check is not enough, and a regex over the prose is not enough
either. The first version of this test scanned for `apps.`-prefixed
dotted paths, which silently skipped every symbol cited after a comma
(`PMTModelVersion, PMTBandThreshold` — the second name has no prefix),
so renaming `PMTBandThreshold` in the digest passed. Hence the explicit
list.

This cannot check that a *rule* is still the right rule, only that the
things it points at exist. `docs/ssot_register.md` stays authoritative;
this guards the copy.
"""

from __future__ import annotations

import importlib
import pathlib
import re

import pytest

DIGEST = pathlib.Path(__file__).resolve().parents[2] / "docs" / "ssot_agent_prompt.md"


def _paste_block() -> str:
    """The fenced block between the two markers — the part that travels
    into a prompt, and so the part that must hold up. Prose outside it
    may describe things loosely."""
    text = DIGEST.read_text(encoding="utf-8")
    body = text[text.index("## Paste from here"):text.index("## Stop here")]
    fences = re.findall(r"```\n(.*?)```", body, re.DOTALL)
    assert len(fences) == 1, f"expected one fenced block, found {len(fences)}"
    return fences[0]


#: Every code symbol the paste block names: (dotted path, text as the
#: digest spells it). The second element is what must appear verbatim —
#: usually the bare name, because the digest cites siblings after a comma
#: rather than repeating the module.
CITED: tuple[tuple[str, str], ...] = (
    ("apps.reference_data.models.GeographicUnit", "apps.reference_data.models.GeographicUnit"),
    ("apps.reference_data.models.GeographicUnit.Level", "GeographicUnit.Level"),
    ("apps.reference_data.code_frames.resolve_geographic_labels",
     "apps.reference_data.code_frames.resolve_geographic_labels"),
    ("apps.reference_data.models.ChoiceList", "apps.reference_data.models.ChoiceList"),
    ("apps.reference_data.models.ChoiceOption", "ChoiceOption"),
    ("apps.reference_data.models.ReferenceSequence",
     "apps.reference_data.models.ReferenceSequence"),
    ("apps.reference_data.references.next_reference",
     "apps.reference_data.references.next_reference"),
    ("apps.intake.models.FormQuestion", "apps.intake.models.FormQuestion"),
    ("apps.intake.models.DataRequestFieldDefinition",
     "apps.intake.models.DataRequestFieldDefinition"),
    ("apps.data_requests.builder_schema", "apps.data_requests.builder_schema"),
    ("apps.data_requests.builder_schema.build_schema", "build_schema()"),
    ("apps.data_requests.builder_schema.field_catalogue", "field_catalogue()"),
    ("apps.data_requests.field_groups.canonical_groups",
     "apps.data_requests.field_groups.canonical_groups"),
    ("apps.data_requests.field_groups.catalogue", ".catalogue()"),
    ("apps.data_requests.models.DataRequest", "apps.data_requests.models.DataRequest"),
    ("apps.data_management.models.Household", "apps.data_management.models.Household"),
    ("apps.data_management.models.Member", "Member"),
    ("apps.data_management.models.Household.GEO_CODE_FIELDS", "Household.GEO_CODE_FIELDS"),
    ("apps.pmt.models.PMTModelVersion", "apps.pmt.models.PMTModelVersion"),
    ("apps.pmt.models.PMTBandThreshold", "PMTBandThreshold"),
    ("apps.pmt.models.PMTResult", "PMTResult"),
    ("apps.partners.models.Partner", "apps.partners.models.Partner"),
    ("apps.partners.models.DataSharingAgreement", "DataSharingAgreement"),
    ("apps.partners.models.Programme", "apps.partners.models.Programme"),
    ("apps.referral.models.ProgrammeEnrolment",
     "apps.referral.models.ProgrammeEnrolment"),
    ("apps.security.roles.ROLES", "apps.security.roles.ROLES"),
    ("apps.security.roles.ROLE_CODES", "ROLE_CODES"),
    ("apps.security.abac", "apps.security.abac"),
    ("apps.security.abac.scope_q_for_field", "scope_q_for_field"),
    ("apps.security.abac.user_can_access_household", "user_can_access_household"),
    ("apps.security.models.AuditEvent", "apps.security.models.AuditEvent"),
    ("apps.security.audit.emit", "apps.security.audit.emit"),
    ("apps.dqa", "apps.dqa"),
    ("apps.ddup", "apps.ddup"),
    ("apps.update_workflow.models.ChangeRequest",
     "apps.update_workflow.models.ChangeRequest"),
    ("apps.update_workflow.models.UpdRoutingRule", "UpdRoutingRule"),
    ("apps.grievance.models.GrmTierRule", "apps.grievance.models.GrmTierRule"),
    ("apps.grievance.visibility.allowed_actions",
     "apps.grievance.visibility.allowed_actions"),
)

#: Model fields the digest names, which `hasattr` on the class does not
#: reach the same way as a method or constant.
CITED_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("apps.pmt.models", "PMTModelVersion", "band_strategy"),
    ("apps.pmt.models", "PMTModelVersion", "band_cutoffs"),
    ("apps.security.models", "AuditEvent", "self_hash"),
    ("apps.security.models", "AuditEvent", "occurred_at"),
)


def _resolve(path: str):
    """Import the longest importable prefix, then getattr the rest."""
    parts = path.split(".")
    module, consumed = None, 0
    for i in range(len(parts), 0, -1):
        try:
            module = importlib.import_module(".".join(parts[:i]))
        except ImportError:
            continue
        consumed = i
        break
    assert module is not None, f"{path}: no importable module prefix"
    obj = module
    for attr in parts[consumed:]:
        assert hasattr(obj, attr), (
            f"{path}: no attribute {attr!r} — the code moved and "
            f"docs/ssot_agent_prompt.md still points here"
        )
        obj = getattr(obj, attr)
    return obj


@pytest.mark.django_db
@pytest.mark.parametrize(("path", "text"), CITED, ids=[c[0] for c in CITED])
def test_cited_symbol_resolves(path, text):
    _resolve(path)


@pytest.mark.parametrize(("path", "text"), CITED, ids=[c[0] for c in CITED])
def test_cited_symbol_is_actually_in_the_digest(path, text):
    """The other direction: if the digest is edited to name something
    else, this list must be updated with it — which forces the rename to
    be checked against the code by the test above."""
    assert text in _paste_block(), (
        f"{text!r} is no longer in the digest's paste block; CITED is "
        f"stale for {path}"
    )


@pytest.mark.django_db
@pytest.mark.parametrize(("module", "klass", "field"), CITED_FIELDS)
def test_cited_model_field_exists(module, klass, field):
    model = getattr(importlib.import_module(module), klass)
    names = {f.name for f in model._meta.get_fields()}
    assert field in names, f"{klass}.{field} is gone; the digest names it"


@pytest.mark.django_db
def test_no_apps_path_in_the_digest_escapes_cited():
    """A citation added to the digest but not to `CITED` would never be
    resolved against the code. Catch it at the point it is added."""
    listed = {text for _, text in CITED}
    found = set(re.findall(r"\bapps(?:\.[A-Za-z_][A-Za-z0-9_]*)+", _paste_block()))
    unlisted = sorted(p for p in found if p not in listed)
    assert not unlisted, (
        f"cited in the digest but absent from CITED: {unlisted}"
    )


def test_the_digest_defers_to_the_register():
    """The digest must say which file wins, or it becomes a second
    vocabulary — the defect class this register exists to stop."""
    text = DIGEST.read_text(encoding="utf-8")
    assert "docs/ssot_register.md" in text
    assert "authoritative" in text.lower()


def test_every_register_binding_reaches_the_digest():
    """A binding added to the register but not the digest is invisible to
    every agent prompted with the digest."""
    register = DIGEST.with_name("ssot_register.md").read_text(encoding="utf-8")
    rows = [
        ln.split("|")[1].strip()
        for ln in register.splitlines()
        if ln.startswith("| ") and ln.count("|") >= 4
    ]
    domains = [r for r in rows if r and r != "Domain" and not set(r) <= {"-"}]
    assert len(domains) >= 20, f"parsed only {len(domains)} register rows"

    digest = _paste_block().lower()
    # Matched on the distinctive words of each domain rather than the whole
    # phrase, because the digest's left column is narrower than the
    # register's and abbreviates ("DRS field defs" for "Data-request fields").
    missing = [
        domain for domain in domains
        if (words := [w for w in re.split(r"[^a-z]+", domain.lower()) if len(w) > 3])
        and not any(w in digest for w in words)
    ]
    assert not missing, f"register domains absent from the digest: {missing}"
