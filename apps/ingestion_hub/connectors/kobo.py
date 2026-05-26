"""Kobo Toolbox connector (US-S11-003a).

Talks to a Kobo Toolbox instance through its REST API (default
target: the OCHA humanitarian instance, `https://kobo.humanitarian
response.info`, which is what the project's first pilot runs
against).

Three live methods on top of the canonicalisation contract from
US-S8-005:

- test_connection(creds) — cheap GET against /api/v2/assets.json
  to confirm the token works and report round-trip latency. The
  Admin UI's "Test connection" button calls this before save.
- list_forms(creds) — enumerate the assets (forms) the token has
  read access to.
- pull_submissions(creds, form_id, since) — paginate through
  /api/v2/assets/{form_id}/data/ and yield each submission as a
  raw dict. The canonical mapper (kobo_to_canonical, when wired)
  will consume these per-record.

Credentials are passed in as a dict the caller has decrypted from
the KoboCredential row — the connector NEVER reads the DB
directly. Expected keys:
    {
      "server_url": "https://kobo.humanitarianresponse.info",
      "token": "abcdef…",   # Kobo Knox token, captured by the
                              # admin form's password-to-token
                              # exchange in commit 2
    }

For first-time setup (no token yet) the credentials dict carries
{"server_url", "username", "password"} and the connector exchanges
them via the token endpoint. Password is held only in this
function's local scope and never persisted as-is — the caller
writes the returned token back to KoboCredential and discards the
password. See acquire_token() below.

The httpx-vs-requests decision: `requests` was chosen so this
ships without a new ADR (option 5 of the BUG-S11-002 design
discussion). Retries use a small in-process loop rather than
urllib3.util.retry so the timing signal in ConnectionTestResult
.latency_ms reflects the full attempt sequence including backoffs.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

import requests
from requests.exceptions import RequestException

from .base import ConnectionTestResult, register_connector

logger = logging.getLogger(__name__)

# Retry policy: tight enough that a "Test connection" call doesn't
# block the admin form for more than ~30s in the worst case, loose
# enough that a transient 503 doesn't fail it. Three attempts at
# 1s/3s backoff equals at most ~19s of waits + the per-attempt
# read timeout.
DEFAULT_TIMEOUT = (5, 15)  # (connect, read), seconds
RETRY_BACKOFFS = (1.0, 3.0)  # waits between attempts 1->2 and 2->3
MAX_ATTEMPTS = 1 + len(RETRY_BACKOFFS)


def _request_with_retry(
    method: str, url: str, *, session: requests.Session,
    timeout: tuple[int, int] = DEFAULT_TIMEOUT,
    **kwargs: Any,
) -> requests.Response:
    """Wrap session.request with bounded retries on 5xx + network
    errors. 4xx responses (incl. 401/403) are returned immediately —
    those are authentication problems the caller surfaces to the
    Admin UI as `error=auth_failed`, not infrastructure flakiness."""
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = session.request(method, url, timeout=timeout, **kwargs)
            if response.status_code < 500:
                return response
            last_error = RequestException(
                f"upstream {response.status_code} on {method} {url}",
            )
        except RequestException as e:
            last_error = e
        # Last attempt — stop retrying.
        if attempt == MAX_ATTEMPTS - 1:
            break
        time.sleep(RETRY_BACKOFFS[attempt])
    # Exhausted retries — caller turns this into a test-failure result.
    raise last_error or RequestException("retry budget exhausted")


def _new_session() -> requests.Session:
    """Build a per-call session. Sharing a process-level session
    would pool connections nicely BUT leak token Authorization
    headers between credential profiles, which is a security
    surface we don't need to manage today."""
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


# --- Canonical mapper (US-S11-011) -------------------------------------
#
# Maps the NSR socio-economic questionnaire v2 (March 2026) — the
# field block that ships in the Kobo form `a1-a15` (geography +
# interview meta), `b1-b5` (head + contact), `c1-c22` (member
# demographics + NIN), `d1-d8` (disability), `e1-e5` (education),
# `f1-f10` (employment), `g1-g16` (dwelling + assets), `h1-h6`
# (agriculture), `i1-i17` (food security), `k01` (shocks), `l*`
# (coping) — onto the canonical shape the DIH staging pipeline
# expects. See ADR-0007 for the connector plug-in pattern.
#
# Required NSR fields (geographic 7-level codes, member roster with
# names + sex) are mapped strictly. Optional fields (NIN, GPS,
# disability/education/employment metadata) are best-effort — when
# absent in the Kobo payload we leave the canonical key out rather
# than fabricating a default. Downstream DQA rules (AC-MANDATORY,
# AC-NIN-FORMAT) catch missing required values per SAD §4.2.
#
# Strict failures (missing geo block, empty roster) raise KeyError so
# the caller (stage_from_landing) routes the row to Quarantine
# per AC-DIH-QUARANTINE.

# Kobo's c4_sex carries UBOS's 1=male / 2=female convention, which
# is identical to the seeded `sex` ChoiceList. Per ADR-0010, the
# canonical_payload carries raw ChoiceOption codes — so this is a
# passthrough, not a translation. (Pre-ADR-0010 the connector
# converted to "M"/"F"; that mapping was removed in US-S22-005h.)


def _split_full_name(full: str) -> tuple[str, str]:
    """Best-effort surname/first_name split from a single
    full-name string. Ugandan convention on official forms is
    surname first, given names after — so we take the first
    whitespace-separated token as surname and the rest as
    first_name. The split is conservative: if the string is empty
    or one token, surname gets the whole thing and first_name is
    blank. Operators correct edge cases via UPD after promotion."""
    parts = (full or "").strip().split(None, 1)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _parse_kobo_gps(gps: str | None) -> tuple[float | None, float | None, float | None]:
    """ODK/Kobo geopoint serialisation: 'lat lng altitude accuracy',
    space-separated, with empty / 0 / 9 sentinels for unknown
    altitude+accuracy. Returns (lat, lng, accuracy_m) — altitude is
    ignored since NSR doesn't capture it."""
    if not gps:
        return None, None, None
    parts = gps.strip().split()
    if len(parts) < 2:
        return None, None, None
    try:
        lat = float(parts[0])
        lng = float(parts[1])
    except ValueError:
        return None, None, None
    accuracy = None
    if len(parts) >= 4:
        try:
            accuracy = float(parts[3])
        except ValueError:
            accuracy = None
    return lat, lng, accuracy


def _kobo_flatten(d: dict) -> dict:
    """Return a copy of `d` with every group-prefixed key
    (`group/subgroup/field`) also accessible as the trailing
    segment (`field`). Kobo's `begin_group` produces these slash-
    separated keys, and a form with group nesting (the v1 legacy
    NSR questionnaire) would otherwise fail every `raw.get("...")`
    in canonicalize.

    First-wins on collision so an explicit top-level key isn't
    masked by a deeper alias. Originals are preserved so the audit
    chain on RawLanding still shows the form's true field paths.
    """
    out = dict(d)
    for k, v in d.items():
        if "/" in k:
            tail = k.rsplit("/", 1)[-1]
            out.setdefault(tail, v)
    return out


def _kobo_member_to_canonical(raw: dict, line_number: int) -> dict:
    """Convert one row from `household_members[]` to the canonical
    member shape. Kobo namespaces every field as
    `household_members/c1_full_name` and nested sub-groups produce
    `household_members/education_literacy/e1_literacy`; the
    flatten helper aliases every group-prefixed key to its trailing
    segment so the lookups below work for both flat and nested
    forms."""
    m = _kobo_flatten(raw)
    full = m.get("c1_full_name", "")
    surname, first_name = _split_full_name(full)
    # The first member with c2_relationship='01' is the head by the
    # form convention. The caller (kobo_to_canonical) passes
    # line_number; the head_member resolution happens in
    # promote_stage_record via the is_head flag.
    is_head = (m.get("c2_relationship") or "").strip() == "01"
    canonical: dict = {
        "line_number": int(m.get("member_index") or line_number),
        "is_head": is_head,
        "surname": surname,
        "first_name": first_name,
        "other_name": "",
        "sex": str(m.get("c4_sex") or "").strip(),
        "date_of_birth": m.get("c5_date_of_birth") or None,
        "age_years": _to_int(m.get("c6_age_years")),
        "relationship_to_head": "" if is_head else (m.get("c2_relationship") or ""),
        "telephone_1": (m.get("c18_telephone_1") or "").strip(),
        "telephone_2": "",
        # NIN trio — only fill nin when the form says the member has a
        # card (c8_nin_status='1'); otherwise the c9_nin field is
        # typically absent. The canonical helper in promote_stage_record
        # will hash/encrypt; we just pass the raw string here.
        "nin": (m.get("c9_nin") or "").strip().upper()
                if (m.get("c8_nin_status") or "").strip() == "1" else "",
        # ────────────────────────────────────────────────────────────
        # Detail blocks (US-S11-020) — per-member sections from the
        # questionnaire so the household-detail screen can render
        # Health / Disability, Education, Employment tabs from the
        # canonical_payload without inventing new tables yet. Each
        # section retains the raw form code; the React side maps it
        # to a human label when rendering.
        # ────────────────────────────────────────────────────────────
        "health": {
            "chronic_illness": m.get("d1_chronic_illness", ""),
            "seeing":         m.get("d3_seeing", ""),
            "hearing":        m.get("d4_hearing", ""),
            "walking":        m.get("d5_walking", ""),
            "remembering":    m.get("d6_remembering", ""),
            "self_care":      m.get("d7_self_care", ""),
            "communicating":  m.get("d8_communicating", ""),
        },
        "education": {
            "literacy":             m.get("e1_literacy", ""),
            "ever_school":          m.get("e2_ever_school", ""),
            "never_school_reason":  m.get("e3_never_school_reason", ""),
            "highest_grade":        m.get("e4_highest_grade", ""),
            "currently_attending":  m.get("e5_currently_attending", ""),
        },
        "employment": {
            "main_job":              m.get("f1_main_job", ""),
            "work_frequency":        m.get("f2_work_frequency", ""),
            "work_sector":           m.get("f3_work_sector", ""),
            "work_status":           m.get("f4_work_status", ""),
            "not_working_reason":    m.get("f5_not_working_reason", ""),
            "gov_program_beneficiary": m.get("f6_gov_program_beneficiary", ""),
            "programmes":            m.get("f7_programmes", ""),
            "currently_benefiting":  m.get("f8_currently_benefiting", ""),
            "made_savings":          m.get("f9_made_savings", ""),
            "savings_place":         m.get("f10_savings_place", ""),
        },
        # Lineage so the audit chain can trace any field back to the
        # original Kobo question code.
        "_source_keys": {
            "kobo_member_index": m.get("member_index", ""),
            "c8_nin_status": m.get("c8_nin_status", ""),
            "c11_residency_status": m.get("c11_residency_status", ""),
        },
    }
    return canonical


# ──────────────────────────────────────────────────────────────────────
# Household-level questionnaire blocks (US-S11-020)
#
# Mapped from the questionnaire's g* (housing/assets), h* (agriculture),
# i* (food security + 7-day food consumption), k* (shocks), l* (coping).
# Kept as flat dicts keyed by the form's question codes so the React
# detail screen can render them without re-querying the raw landing.
# ──────────────────────────────────────────────────────────────────────

def _kobo_housing_block(raw: dict) -> dict:
    return {
        "tenure":              raw.get("g1_tenure", ""),
        "dwelling_type":       raw.get("g2_dwelling_type", ""),
        "rooms_total":         _to_int(raw.get("g3_rooms_total")),
        "rooms_sleeping":      _to_int(raw.get("g4_rooms_sleeping")),
        "roof_material":       raw.get("g5_roof_material", ""),
        "wall_material":       raw.get("g6_wall_material", ""),
        "floor_material":      raw.get("g7_floor_material", ""),
        "cooking_fuel":        raw.get("g8_cooking_fuel", ""),
        "lighting_source":     raw.get("g9_lighting_source", ""),
        "water_source":        raw.get("g10_water_source", ""),
        "toilet_type":         raw.get("g11_toilet_type", ""),
        "share_toilet":        raw.get("g12_share_toilet", ""),
        "share_toilet_households": _to_int(raw.get("g13_share_toilet_households")),
        "waste_disposal":      raw.get("g14_waste_disposal", ""),
        "assets_owned":        raw.get("g15_assets_owned", ""),  # space-separated codes
        "asset_counts": {
            "mattress": _to_int(raw.get("g15_count_mattress")),
            "solar":    _to_int(raw.get("g15_count_solar")),
            "bed":      _to_int(raw.get("g15_count_bed")),
            "tv":       _to_int(raw.get("g15_count_tv")),
            "bicycle":  _to_int(raw.get("g15_count_bicycle")),
            "phone":    _to_int(raw.get("g15_count_phone")),
        },
        "livelihood_source":   raw.get("g16_livelihood_source", ""),
    }


def _kobo_agriculture_block(raw: dict) -> dict:
    return {
        "crop_production":   raw.get("h1_crop_production", ""),
        "livestock":         raw.get("h2_livestock", ""),
        "livestock_counts":  raw.get("h3_livestock_counts", ""),  # free-text "goats=3; chicken=8"
        "ag_purpose":        raw.get("h4_ag_purpose", ""),
        "crops_grown":       raw.get("h5_crops_grown", ""),       # comma-list
        "land_ownership":    raw.get("h6_land_ownership", ""),
    }


def _kobo_food_security_block(raw: dict) -> dict:
    """FIES 8-item module + 7-day food consumption (HDDS-style).
    The form codes are preserved; the React side renders them with
    the questionnaire labels."""
    fies_keys = ("i1_fies", "i2_fies", "i3_fies", "i4_fies",
                 "i5_fies", "i6_fies", "i7_fies", "i8_fies")
    # Each food group has days (i9 = staples through i17 = condiments)
    # plus primary/secondary source codes + yesterday flag.
    groups = [
        ("staples",        "i9"),
        ("pulses_nuts",    "i10"),
        ("milk_dairy",     "i11"),
        ("meat_fish_eggs", "i12"),
        ("vegetables",     "i13"),
        ("fruits",         "i14"),
        ("oils_fats",      "i15"),
        ("sugar_sweets",   "i16"),
        ("condiments",     "i17"),
    ]
    food_groups = {}
    for label, prefix in groups:
        food_groups[label] = {
            "days":              _to_int(raw.get(f"{prefix}_{label}_days")),
            "source_primary":    raw.get(f"{prefix}_{label}_source_primary", ""),
            "source_secondary":  raw.get(f"{prefix}_{label}_source_secondary", ""),
            "yesterday":         raw.get(f"{prefix}_{label}_yesterday", ""),
        }
    return {
        "fies": {k: raw.get(k, "") for k in fies_keys},
        "food_groups": food_groups,
    }


def _kobo_shocks_coping_block(raw: dict) -> dict:
    """Shock affected flag + per-strategy coping responses. The form
    codes are 1-4 (always/often/sometimes/never) on each strategy."""
    coping_keys = [
        # l01* — financial / asset coping
        "l01a_casual_labor", "l01b_sell_assets", "l01c_borrow_money",
        "l01d_assistance_friends", "l01e_assistance_agencies", "l01f_remittances",
        "l01g_sand_gravel", "l01h_relocate", "l01i_begging",
        # l02* — food coping
        "l02a_less_preferred_food", "l02b_borrow_food_money", "l02c_reduce_portions",
        "l02d_reduce_meals", "l02e_restrict_adults", "l02f_day_without_eating",
        "l02g_wild_food", "l02h_merge_households", "l02i_begging",
    ]
    return {
        "shock_affected": raw.get("k01_shock_affected", ""),
        "coping": {k: raw.get(k, "") for k in coping_keys},
    }


def _to_int(value) -> int | None:
    """Coerce Kobo's string-encoded ints. Returns None when the value
    is blank, missing, or non-numeric — leave numeric defaulting to
    the downstream DQA layer rather than fabricating zeros."""
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _slug(value: str) -> str:
    """Match load_ubos_geography._slug: uppercase, spaces/slashes → hyphen."""
    return value.strip().upper().replace(" ", "-").replace("/", "-")


def _canonicalize_kobo_geo(raw: dict) -> dict:
    """Translate the Kobo form's geographic representation into the
    NSR canonical codes that GeographicUnit rows are keyed on.

    The Kobo form writes:
      a0_region              "western"            (name, lowercased)
      a1_subregion           "kigezi"             (name, lowercased)
      a2_district_city       "412"                (UBOS district code)
      a3_county_municipality "412_02"             (district_county, _-separated)
      a4_subcounty_division_tc "412_02_05"        (district_county_subcounty)
      a5_parish_ward         "412_02_05_01"       (district_county_subcounty_parish)
      a6_lc1_village_cell    "Akello Village"     (name only — no UBOS code at
                                                   this level per the loader)

    The UBOS loader (scripts/load_ubos_geography.py) writes:
      region:     "R-WESTERN"                     (R-{SLUG})
      sub_region: "SR-KIGEZI-WESTERN"             (SR-{SLUG}-{R_SLUG})
      district:   "412"                           (same)
      county:     "412.02"                        (.-separated)
      sub_county: "412.02.05"
      parish:     "412.02.05.01"
      village:    (not loaded today — UBOS source has no village rows)

    Village is fabricated from `{parish_code}.{slug(village_name)}`
    so the Household.village FK can be satisfied without requiring a
    UBOS village registry that doesn't exist yet. Operators can
    rename / re-link villages later via a UPD ChangeRequest.
    """
    region_name = (raw.get("a0_region") or "").strip()
    subregion_name = (raw.get("a1_subregion") or "").strip()
    district_code = (raw.get("a2_district_city") or "").strip()
    county_code = (raw.get("a3_county_municipality") or "").strip().replace("_", ".")
    subcounty_code = (raw.get("a4_subcounty_division_tc") or "").strip().replace("_", ".")
    parish_code = (raw.get("a5_parish_ward") or "").strip().replace("_", ".")
    village_name = (raw.get("a6_lc1_village_cell") or "").strip()

    # Idempotent prefix build — current Kobo form sends raw names
    # ('Eastern', 'Bukedi') and we slug+prefix to get the canonical
    # code. The v1 legacy form sends already-encoded codes
    # ('R-EASTERN', 'SR-BUKEDI-EASTERN'); the startswith guards keep
    # us from emitting 'R-R-EASTERN' / 'SR-SR-BUKEDI-...' in that case.
    if region_name.startswith("R-"):
        region_code = region_name
    elif region_name:
        region_code = f"R-{_slug(region_name)}"
    else:
        region_code = ""

    if subregion_name.startswith("SR-"):
        subregion_code = subregion_name
    elif subregion_name and region_name:
        subregion_code = f"SR-{_slug(subregion_name)}-{_slug(region_name)}"
    else:
        subregion_code = ""
    village_code = (
        f"{parish_code}.{_slug(village_name)}"
        if parish_code and village_name else ""
    )

    return {
        "region": region_code,
        "sub_region": subregion_code,
        "district": district_code,
        "county": county_code,
        "sub_county": subcounty_code,
        "parish": parish_code,
        "village": village_code,
        # Lineage so the UPD reviewer can see what the form originally
        # captured if we later need to renegotiate the encoding.
        "_form_values": {
            "region_name": region_name,
            "subregion_name": subregion_name,
            "village_name": village_name,
        },
    }


def kobo_to_canonical(raw: dict) -> dict:
    """Convert a Kobo Toolbox submission (NSR socio-economic
    questionnaire v2) to the canonical NSR shape consumed by
    stage_from_landing.

    Required:
        a0_region, a1_subregion, a2_district_city,
        a3_county_municipality, a4_subcounty_division_tc,
        a5_parish_ward, a6_lc1_village_cell — all 7 GeographicUnit
        codes. Missing geography raises KeyError → row goes to
        Quarantine.
        household_members[] with ≥1 member. Empty roster raises
        KeyError too — a registry record without people is
        semantically meaningless.

    Best-effort:
        gps from a11_12_gps; urban/rural from a7_rural_urban
        ('1'=rural, '2'=urban per UBOS convention).

    Both forms are handled: flat-key (current questionnaire) and
    group-nested (legacy v1 — fields under identification/,
    survey_status/, housing/, agriculture/, ...). `_kobo_flatten`
    aliases every group-prefixed key to its trailing name; original
    keys are preserved so the RawLanding audit chain still shows the
    form's actual field paths.
    """
    raw = _kobo_flatten(raw)
    geo_keys = (
        "a0_region", "a1_subregion", "a2_district_city",
        "a3_county_municipality", "a4_subcounty_division_tc",
        "a5_parish_ward", "a6_lc1_village_cell",
    )
    for k in geo_keys:
        if not raw.get(k):
            raise KeyError(f"missing required Kobo geo field: {k}")

    members_raw = raw.get("household_members") or []
    if not members_raw:
        raise KeyError("Kobo submission has no household_members rows")

    lat, lng, gps_acc = _parse_kobo_gps(raw.get("a11_12_gps"))
    # Kobo's a7_rural_urban is "2" for urban / "1" for rural — the inverse of
    # the seeded rural_urban list (1=Urban, 2=Rural). Emit the seed code per
    # ADR-0010 so canonical_payload carries raw ChoiceOption codes.
    urban_rural = "1" if str(raw.get("a7_rural_urban") or "").strip() == "2" else "2"

    geographic = _canonicalize_kobo_geo(raw)
    # The lineage block stays inside _source_keys so the
    # promote_stage_record path (which only consumes the named geo
    # fields) doesn't see an unexpected key.
    geo_form_values = geographic.pop("_form_values")

    canonical: dict = {
        "geographic": geographic,
        # Household-level questionnaire blocks (US-S11-020) — surface
        # the form's g*/h*/i*/k*/l* sections so the household-detail
        # screen renders them under their tabs without inventing new
        # detail tables. These don't drive DQA / promotion today (the
        # canonical pipeline only looks at geo + members) but they
        # propagate through the audit chain on RawLanding + StageRecord.
        "housing":       _kobo_housing_block(raw),
        "agriculture":   _kobo_agriculture_block(raw),
        "food_security": _kobo_food_security_block(raw),
        "shocks_coping": _kobo_shocks_coping_block(raw),
        "interview": {
            # Form-level metadata an operator might want at a glance.
            "respondent_name":   raw.get("b1_respondent_name", ""),
            "respondent_phone":  raw.get("b2_telephone_number", ""),
            "head_name":         raw.get("b4_head_name", ""),
            "interview_result":  raw.get("b5_interview_result", ""),
            "consent":           raw.get("consent", ""),
            "hh_size":           _to_int(raw.get("hh_size")),
            "interviewer":       raw.get("a13_interviewer_name_code", ""),
            "supervisor":        raw.get("a14_parish_supervisor_name_code", ""),
            "deviceid":          raw.get("deviceid", ""),
            "start":             raw.get("start", ""),
            "end":               raw.get("end", ""),
        },
        "urban_rural": urban_rural,
        "address_narrative": (raw.get("b3_address") or "").strip(),
        "gps_lat": lat,
        "gps_lng": lng,
        "gps_accuracy_m": gps_acc,
        "members": [
            _kobo_member_to_canonical(m, i)
            for i, m in enumerate(members_raw, start=1)
        ],
        "_source_keys": {
            "kobo_submission_id": str(raw.get("_id", "")),
            "kobo_uuid": raw.get("_uuid", ""),
            "kobo_form_id": raw.get("_xform_id_string", ""),
            "kobo_household_number": raw.get("a9_household_number", ""),
            "kobo_enumeration_area": raw.get("a8_enumeration_area", ""),
            "kobo_submitted_by": raw.get("_submitted_by", ""),
            "kobo_submission_time": raw.get("_submission_time", ""),
            # Original geo form values pre-canonicalisation. Useful
            # when the UPD reviewer needs to see what the enumerator
            # actually typed.
            "kobo_region_name": geo_form_values["region_name"],
            "kobo_subregion_name": geo_form_values["subregion_name"],
            "kobo_village_name": geo_form_values["village_name"],
        },
    }
    return canonical


def acquire_token(
    server_url: str, username: str, password: str,
    *, session: requests.Session | None = None,
) -> str:
    """Exchange username+password for a Kobo Knox token.

    Used ONCE, by the admin form's "Save" handler in commit 2.
    The password lives in the caller's stack frame and the
    returned token is what gets encrypted onto KoboCredential.
    This function deliberately never logs the password and never
    returns it.

    POST /token/?format=json
        body: { username, password }
        -> 200 { token: "..." }
        -> 401 on bad credentials (caller turns into auth_failed)
    """
    session = session or _new_session()
    url = f"{server_url.rstrip('/')}/token/?format=json"
    response = _request_with_retry(
        "POST", url, session=session,
        data={"username": username, "password": password},
    )
    if response.status_code == 401:
        raise RequestException("Kobo rejected credentials (401)")
    response.raise_for_status()
    token = response.json().get("token")
    if not token:
        raise RequestException("Kobo /token/ returned no token field")
    return token


class KoboConnector:
    """Kobo Toolbox HTTP connector.

    Registered under code "KOBO-PILOT" to match the SourceSystem.code
    seeded in scripts/seed_dih_sources.py. When a second Kobo instance
    is onboarded (e.g., MGLSD's own deployment), the second registration
    re-uses this class with a different SourceSystem code, and the
    Admin form passes its credentials in — connector instances are
    stateless across calls so one class can serve multiple SourceSystems
    pointing at different Kobo URLs.
    """

    code = "KOBO-PILOT"

    # canonicalize wired to the module-level kobo_to_canonical
    # (US-S11-011). The function is pure — it raises KeyError on
    # missing required fields so stage_from_landing routes the row to
    # Quarantine per AC-DIH-QUARANTINE. process stays None: Kobo uses
    # the generic DIH run path (land → stage → promote) rather than a
    # side-effecting driver like NIRA reverse-feed.
    canonicalize = staticmethod(kobo_to_canonical)
    process = None

    def test_connection(self, credentials: dict) -> ConnectionTestResult:
        """Cheapest possible smoke test — list one asset, time it,
        read X-OpenRosa-Version if present."""
        server_url = credentials.get("server_url", "").rstrip("/")
        token = credentials.get("token")
        if not server_url or not token:
            return ConnectionTestResult(
                ok=False, latency_ms=0,
                error="server_url and token required",
            )

        session = _new_session()
        session.headers["Authorization"] = f"Token {token}"
        url = f"{server_url}/api/v2/assets.json?limit=1"
        started = time.perf_counter()
        try:
            response = _request_with_retry("GET", url, session=session)
        except RequestException as e:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ConnectionTestResult(
                ok=False, latency_ms=latency_ms, error=str(e),
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code == 401:
            return ConnectionTestResult(
                ok=False, latency_ms=latency_ms,
                error="auth_failed: token rejected by upstream",
            )
        if response.status_code >= 400:
            return ConnectionTestResult(
                ok=False, latency_ms=latency_ms,
                error=f"upstream {response.status_code}",
            )
        # Kobo's response headers carry a server-version-ish field on
        # some deployments; capture it best-effort.
        server_version = (
            response.headers.get("X-OpenRosa-Version")
            or response.headers.get("Server")
        )
        return ConnectionTestResult(
            ok=True, latency_ms=latency_ms, server_version=server_version,
        )

    def list_forms(self, credentials: dict) -> list[dict]:
        """Return [{uid, name, asset_type, deployment__active}]."""
        server_url = credentials["server_url"].rstrip("/")
        session = _new_session()
        session.headers["Authorization"] = f"Token {credentials['token']}"
        url = f"{server_url}/api/v2/assets.json"
        response = _request_with_retry("GET", url, session=session)
        response.raise_for_status()
        return [
            {
                "uid": a.get("uid"),
                "name": a.get("name"),
                "asset_type": a.get("asset_type"),
                "deployed": bool(a.get("deployment__active")),
            }
            for a in response.json().get("results", [])
        ]

    def pull_submissions(
        self, credentials: dict, *, form_id: str, since: str | None = None,
    ) -> Iterator[dict]:
        """Yield each submission dict; paginates via the `next` link.

        `since` is forwarded to Kobo as a filter on _submission_time;
        Kobo's query DSL is mongo-style so the value is wrapped in
        a tiny shim. Future stories can extend this to richer
        filters when the schedule-builder lands.
        """
        server_url = credentials["server_url"].rstrip("/")
        session = _new_session()
        session.headers["Authorization"] = f"Token {credentials['token']}"
        url = f"{server_url}/api/v2/assets/{form_id}/data.json"
        params: dict[str, Any] = {}
        if since:
            # Kobo accepts a mongo-style JSON query in the `query` param.
            params["query"] = (
                '{"_submission_time": {"$gte": "' + since + '"}}'
            )
        while url:
            response = _request_with_retry(
                "GET", url, session=session, params=params,
            )
            response.raise_for_status()
            body = response.json()
            yield from body.get("results", [])
            # Subsequent pages come back with `next` already containing
            # the encoded query, so we drop our params from page 2 on.
            url = body.get("next")
            params = {}


    def publish_xlsform(
        self, credentials: dict, *,
        xlsx_bytes: bytes, name: str,
        destination_uid: str | None = None,
        deploy: bool = True,
        poll_attempts: int = 30,
        poll_interval_s: float = 1.0,
    ) -> dict:
        """Upload an XLSForm xlsx to Kobo and (optionally) deploy it.

        Two modes:
          - New form (`destination_uid is None`) — uploads via
            POST /api/v2/imports/ which Kobo runs asynchronously,
            creates a fresh asset, and reports the new asset_uid
            once the import task completes.
          - Replace form (`destination_uid` set) — uploads via the
            same imports endpoint with the destination param so the
            existing asset gains a new version (the form_id /
            submission history stay attached).

        Polling: Kobo's import endpoint is async. We poll the import
        task until status='complete' / 'error' or the budget is
        exhausted. Defaults are 30 attempts × 1s = 30s total which
        covers the vast majority of real imports; very large forms
        may need a higher budget passed in.

        Returns:
            {
              "asset_uid": "aXXX",
              "import_uid": "iXXX",
              "deployed": bool,
              "status": "complete" | "error" | "timeout",
              "messages": [...],   # Kobo's import-task message stream
            }

        Raises RequestException on HTTP failure or auth rejection.
        """
        server_url = credentials["server_url"].rstrip("/")
        token = credentials["token"]
        session = _new_session()
        session.headers["Authorization"] = f"Token {token}"

        # ── upload ──────────────────────────────────────────────
        upload_url = f"{server_url}/api/v2/imports/"
        files = {
            "file": (
                f"{name}.xlsx", xlsx_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        }
        data: dict[str, Any] = {"name": name, "library": "false"}
        if destination_uid:
            data["destination"] = (
                f"{server_url}/api/v2/assets/{destination_uid}/"
            )
        upload = _request_with_retry(
            "POST", upload_url, session=session, files=files, data=data,
        )
        upload.raise_for_status()
        import_uid = upload.json().get("uid")
        if not import_uid:
            raise RequestException("Kobo /imports/ returned no uid")

        # ── poll ────────────────────────────────────────────────
        poll_url = f"{server_url}/api/v2/imports/{import_uid}/"
        status = "processing"
        body: dict = {}
        for _ in range(poll_attempts):
            resp = _request_with_retry("GET", poll_url, session=session)
            resp.raise_for_status()
            body = resp.json()
            status = body.get("status", "processing")
            if status in ("complete", "error"):
                break
            time.sleep(poll_interval_s)
        else:
            status = "timeout"

        # ── extract asset_uid ───────────────────────────────────
        asset_uid = destination_uid or ""
        if status == "complete":
            messages = body.get("messages", {}) or {}
            created = messages.get("created") or messages.get("updated") or []
            if created:
                asset_uid = created[0].get("uid") or asset_uid

        # ── deploy ──────────────────────────────────────────────
        deployed = False
        if status == "complete" and deploy and asset_uid:
            deploy_url = f"{server_url}/api/v2/assets/{asset_uid}/deployment/"
            # First-time deploy is POST; redeploy of an existing asset
            # is PATCH with active=true. Try POST first; on 405/409
            # fall through to PATCH.
            d = session.post(deploy_url, json={"active": True}, timeout=DEFAULT_TIMEOUT)
            if d.status_code in (405, 409):
                d = session.patch(deploy_url, json={"active": True}, timeout=DEFAULT_TIMEOUT)
            deployed = d.status_code < 400

        return {
            "asset_uid": asset_uid,
            "import_uid": import_uid,
            "deployed": deployed,
            "status": status,
            "messages": body.get("messages", []),
        }


register_connector(KoboConnector())
