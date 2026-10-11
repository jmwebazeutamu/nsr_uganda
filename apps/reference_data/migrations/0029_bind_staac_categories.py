"""Bind STAAC's sixteen categories to NSR's six.

Migration 0026 registered the codes and left every `canonical_code`
null, saying the correspondence was a policy statement for whoever
owns both vocabularies rather than an engineering guess. That is
still true; what has changed is that the decision has been taken and
this records it. Until now every STAAC case was held unfiled, which
was the designed behaviour and not a tenable resting place.

Recorded on 11 October 2026 on MGLSD's instruction, against synthetic
data in dev. Revisable through the ChoiceList approval workflow
without a deploy — `resolve_canonical_code` reads the column, so
changing a binding and re-running `pull_staac_handovers --file-held`
re-files what is waiting under the new one.

The bindings are written onto version 1 rather than into a new list
version. A new version is how a binding CHANGES meaning; this is the
first meaning any of them has had, nothing was ever resolved through
the nulls, and a v2 whose only difference from v1 is "v1 was
unusable" records nothing worth keeping.

Where it loses information, said plainly
----------------------------------------
Sixteen into six does not divide. Three places are worth knowing:

* **C07 is the lossy one, and it is the common one.** Its STAAC
  sub-categories are wrongful exclusion, wrongful inclusion, PMT
  score dispute and list manipulation — in NSR terms
  `exclusion_error`, `inclusion_error`, `data_correction` and
  `programme_issue`, four different cases behind one code. It binds
  to `exclusion_error` because being left out is the dominant case
  and the one the registry can act on, and because the partner API
  does not transmit the sub-category. The narrative says which;
  triage should re-categorise when it says something else. This is
  the single best argument for STAAC sending sub-categories one day.
* **`data_correction` is bound by nothing.** No STAAC category means
  "the registry holds the wrong facts about me" — the nearest is a
  C07 PMT-score dispute, which arrives under the binding above. An
  NSR grievance that should have been a data correction will
  therefore arrive as an exclusion error and be re-categorised by
  hand. Noted rather than forced: inventing a mapping to fill the
  gap would misfile the other three quarters of C07.
* **C12 (GBV, SEA and SH) can never arrive.** STAAC seals that
  category and `eligibility_reason` refuses a sealed one, so no
  handover can carry it. It is bound anyway so the vocabulary has no
  hole: a code that resolves to nothing looks identical to a code
  nobody has decided about, and the second needs attention while the
  first does not.

The rest group by what the complaint is ABOUT: money and delivery
under `programme_issue`, an officer's behaviour under
`operator_conduct`, ghost beneficiaries under `inclusion_error`
because a ghost is someone on the list who should not be, and the
residue under `other`.
"""

from django.db import migrations

LIST_NAME = "staac_grievance_category"

BINDINGS = {
    # Money, procurement and delivery — what the programme did.
    "C01": "programme_issue",      # Procurement irregularity
    "C03": "programme_issue",      # Embezzlement or diversion of funds
    "C05": "programme_issue",      # Shoddy or incomplete works
    "C06": "programme_issue",      # Delayed or non-receipt of funds/inputs
    "C08": "programme_issue",      # Payment not received or short payment
    # An officer's conduct — what a person did.
    "C04": "operator_conduct",     # Bribery or solicitation
    "C09": "operator_conduct",     # Staff conduct or abuse of office
    "C10": "operator_conduct",     # Interference by officials
    # Who is on the list, and who is not.
    "C02": "inclusion_error",      # Ghost beneficiaries, workers or projects
    "C07": "exclusion_error",      # Targeting and selection irregularity
    # Everything the registry has no narrower category for.
    "C11": "other",                # Environmental and social
    "C12": "other",                # GBV, SEA and SH — sealed, unreachable
    "C13": "other",                # Protected disclosure (whistleblower)
    "C14": "other",                # Household or group dispute
    "C15": "other",                # Information request or clarification
    "C16": "other",                # Other
}


def bind(apps, schema_editor):
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")
    for code, canonical in BINDINGS.items():
        ChoiceOption.objects.filter(
            choice_list__list_name=LIST_NAME, code=code,
        ).update(canonical_code=canonical)


def unbind(apps, schema_editor):
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")
    ChoiceOption.objects.filter(
        choice_list__list_name=LIST_NAME, code__in=list(BINDINGS),
    ).update(canonical_code=None)


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0028_staac_category_labels_are_the_names"),
    ]

    operations = [migrations.RunPython(bind, unbind)]
