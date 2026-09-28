"""Report where submissions actually come from, and what they carry.

The deployed questionnaire went a year emitting a retired code frame
and nothing noticed, because nothing compared the form in the field
against the registry that defines it. Two facts, both already in the
database, are enough to see it:

* every submission records the Kobo asset it came from
  (`_xform_id_string`), and `FormVersion.kobo_asset_uid` records the
  asset the registry believes it publishes to;
* every code the registry cannot interpret is an `UnmappedChoiceValue`
  row, attributable to the run and therefore to the asset.

On the dev registry those two facts say something the export code alone
never could: submissions arrive from `ak2w5k5WAbU53ChwwM8bC7` and
`aRpVGbQLmPbVo3e4XUjSGe`, while the active FormVersion records
`aAeFzAFk6wSpCq7d7dpBga`, which has received nothing. Republishing the
FormVersion would have updated an asset nobody submits to, reported
success, and left the field forms exactly as stale.

Read-only. It reports; it changes nothing and publishes nothing.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict

from django.core.management.base import BaseCommand

from apps.ingestion_hub.models import RawLanding, UnmappedChoiceValue
from apps.intake.models import FormVersion


def _asset_of(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("_xform_id_string") or "")


def _form_version_of(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("__version__") or "")


def collect(limit: int | None = None) -> list[dict]:
    """One row per Kobo asset submissions have arrived from."""
    tracked = {
        fv.kobo_asset_uid: fv
        for fv in FormVersion.objects.exclude(kobo_asset_uid="")
    }

    landings = RawLanding.objects.order_by("-received_at")
    if limit:
        landings = landings[:limit]

    counts: dict[str, int] = defaultdict(int)
    versions: dict[str, set[str]] = defaultdict(set)
    landing_ids: dict[str, set[str]] = defaultdict(set)
    for landing in landings.iterator():
        asset = _asset_of(landing.payload)
        counts[asset] += 1
        version = _form_version_of(landing.payload)
        if version:
            versions[asset].add(version)
        landing_ids[asset].add(str(landing.id))

    # Unmapped codes, attributed to the asset through the landing.
    unmapped: dict[str, set[tuple[str, str]]] = defaultdict(set)
    rows = (
        UnmappedChoiceValue.objects
        .filter(is_current=True)
        .values_list(
            "stage_record__raw_landing_id",
            "choice_list_name",
            "source_code",
        )
    )
    landing_to_asset = {
        landing_id: asset
        for asset, ids in landing_ids.items()
        for landing_id in ids
    }
    for landing_id, list_name, code in rows:
        asset = landing_to_asset.get(str(landing_id))
        if asset is not None:
            unmapped[asset].add((list_name, code))

    out = []
    for asset, submissions in sorted(counts.items(), key=lambda kv: -kv[1]):
        form_version = tracked.get(asset)
        out.append({
            "asset_uid": asset or "(none recorded)",
            "submissions": submissions,
            "form_versions_seen": ",".join(sorted(versions[asset])) or "(none)",
            "tracked_by": (
                f"v{form_version.version}" if form_version else ""
            ),
            "unmapped_codes": len(unmapped[asset]),
            "sample": "; ".join(
                f"{lst}={code}" for lst, code in sorted(unmapped[asset])[:4]
            ),
        })
    return out


def orphan_form_versions() -> list[FormVersion]:
    """Active FormVersions publishing to an asset nothing arrives from.

    The condition that made the stale form invisible, stated as a query.
    """
    seen = {
        _asset_of(landing.payload)
        for landing in RawLanding.objects.only("payload").iterator()
    }
    return [
        fv for fv in FormVersion.objects.filter(is_active=True)
        .exclude(kobo_asset_uid="")
        if fv.kobo_asset_uid not in seen
    ]


class Command(BaseCommand):
    help = (
        "Report the Kobo assets submissions arrive from, whether the "
        "registry tracks them, and which codes they carry that the "
        "registry cannot interpret."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Only read the most recent N raw landings.",
        )
        parser.add_argument(
            "--csv", action="store_true",
            help="Emit CSV on stdout instead of a table.",
        )

    def handle(self, *args, **options):
        rows = collect(limit=options.get("limit"))
        if options.get("csv"):
            writer = csv.DictWriter(
                sys.stdout,
                fieldnames=[
                    "asset_uid", "submissions", "form_versions_seen",
                    "tracked_by", "unmapped_codes", "sample",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)
            return

        if not rows:
            self.stdout.write("No raw landings to report on.")
            return

        self.stdout.write("Kobo assets submissions have arrived from:\n")
        for row in rows:
            tracked = row["tracked_by"] or "NOT TRACKED"
            self.stdout.write(
                f"  {row['asset_uid']:26} {row['submissions']:6} submissions  "
                f"{tracked:12} {row['unmapped_codes']:4} unmapped code(s)",
            )
            if row["sample"]:
                self.stdout.write(f"      e.g. {row['sample']}")

        if not UnmappedChoiceValue.objects.exists():
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "  No UnmappedChoiceValue rows exist at all, so every "
                "count above is 'not measured' rather than 'nothing "
                "wrong'. Codes are checked when a record is staged, so "
                "records staged before that check was enabled carry no "
                "findings. Re-stage a sample to measure them.",
            ))

        orphans = orphan_form_versions()
        if orphans:
            self.stdout.write("")
            for form_version in orphans:
                self.stdout.write(self.style.WARNING(
                    f"  FormVersion v{form_version.version} is active and "
                    f"publishes to {form_version.kobo_asset_uid!r}, which has "
                    f"received no submissions. Republishing it would update "
                    f"an asset nobody is submitting to.",
                ))
