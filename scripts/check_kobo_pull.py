"""Verify a Kobo pull carried section K/L detail through to the payload.

Run after a pull:

    python manage.py shell < scripts/check_kobo_pull.py

On production:

    docker compose -f compose.production.yml --env-file .env \
      exec -T web python manage.py shell < scripts/check_kobo_pull.py

Reports, for the most recent connector run: which key form section K arrived in
(grouped "shocks/k03_..." or flat "k03_..."), whether the connector
produced shock and coping rows from it, and whether promotion turned them
into registry entities.
"""

from apps.data_management.models import CopingStrategy, Shock
from apps.ingestion_hub.connectors.kobo import _kobo_flatten
from apps.ingestion_hub.models import ConnectorRun, RawLanding, StageRecord

# The most recent pull, which is the one worth checking. Records landed
# before the section K/L fix will flag here and that is correct — they
# were mapped by the old connector. Only judge the newest run.
run = ConnectorRun.objects.order_by("-id").first()
if run is None:
    print("no connector runs yet — nothing to check")
    raise SystemExit

landings = list(RawLanding.objects.filter(connector_run=run).order_by("received_at"))
print(f"\n=== connector run {run.id} — {len(landings)} landing(s) ===")
print(f"    status={run.status} started={run.started_at}")

grouped = flat = neither = 0
for landing in landings:
    payload = landing.payload or {}
    keys = list(payload)
    has_grouped = any("/" in k and k.rsplit("/", 1)[-1].startswith("k03_") for k in keys)
    has_flat = any(k.startswith("k03_") for k in keys)
    if has_grouped:
        grouped += 1
    elif has_flat:
        flat += 1
    else:
        neither += 1

print(f"  section K key form:  grouped={grouped}  flat={flat}  no K answers={neither}")
print("  (both forms must work — canonicalize() flattens before mapping)")

print("\n=== did the detail survive into the canonical payload? ===")
checked = with_k = rows_ok = rows_missing = 0
coping_ok = coping_missing = 0
for landing in landings:
    flat_payload = _kobo_flatten(landing.payload or {})
    answered_k = any(
        flat_payload.get(f"k03_{infix}_shock_type")
        for infix in ("crops", "livestock", "labour_employment", "other")
    )
    answered_l = any(
        str(v or "").strip()
        for k, v in flat_payload.items()
        if k.startswith(("l01", "l02"))
    )
    stage = StageRecord.objects.filter(raw_landing=landing).first()
    if stage is None:
        continue
    checked += 1
    payload = stage.canonical_payload or {}
    if answered_k:
        with_k += 1
        if payload.get("shocks"):
            rows_ok += 1
        else:
            rows_missing += 1
            print(f"  !! {landing.source_reference}: section K answered, "
                  f"no 'shocks' rows on the staged payload")
    if answered_l:
        if payload.get("coping_strategies"):
            coping_ok += 1
        else:
            coping_missing += 1
            print(f"  !! {landing.source_reference}: section L answered, "
                  f"no 'coping_strategies' rows on the staged payload")

print(f"  staged records checked: {checked}")
print(f"  section K answered: {with_k}  ->  rows present {rows_ok}, MISSING {rows_missing}")
print(f"  section L answered  ->  rows present {coping_ok}, MISSING {coping_missing}")

print("\n=== did promotion create registry rows? ===")
promoted = [s for s in StageRecord.objects.filter(
    raw_landing__in=landings) if s.promoted_household_id]
print(f"  promoted households among these: {len(promoted)}")
if promoted:
    ids = [s.promoted_household_id for s in promoted]
    print(f"  Shock rows:          {Shock.objects.filter(household_id__in=ids).count()}")
    print(f"  CopingStrategy rows: {CopingStrategy.objects.filter(household_id__in=ids).count()}")

print("\nverdict:", "FAIL — see !! lines above"
      if (rows_missing or coping_missing) else "OK — nothing dropped")
