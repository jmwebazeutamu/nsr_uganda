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

# Kobo field code → NSR canonical sex value. The form uses UBOS's
# 1=male / 2=female convention; the NSR Member.sex column convention
# (see the four shipped connectors) is "M"/"F".
_KOBO_SEX_TO_CANONICAL = {"1": "M", "2": "F"}


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


def _kobo_member_to_canonical(raw: dict, line_number: int) -> dict:
    """Convert one row from `household_members[]` to the canonical
    member shape. Kobo namespaces every field as
    `household_members/c1_full_name` etc., so we strip the prefix
    before consulting the dict."""
    m = {k.removeprefix("household_members/"): v for k, v in raw.items()}
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
        "sex": _KOBO_SEX_TO_CANONICAL.get(str(m.get("c4_sex") or "").strip(), ""),
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
        # Lineage so the audit chain can trace any field back to the
        # original Kobo question code.
        "_source_keys": {
            "kobo_member_index": m.get("member_index", ""),
            "c8_nin_status": m.get("c8_nin_status", ""),
            "c11_residency_status": m.get("c11_residency_status", ""),
        },
    }
    return canonical


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

    region_code = f"R-{_slug(region_name)}" if region_name else ""
    subregion_code = (
        f"SR-{_slug(subregion_name)}-{_slug(region_name)}"
        if subregion_name and region_name else ""
    )
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
    """
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
    urban_rural = "urban" if str(raw.get("a7_rural_urban") or "").strip() == "2" else "rural"

    geographic = _canonicalize_kobo_geo(raw)
    # The lineage block stays inside _source_keys so the
    # promote_stage_record path (which only consumes the named geo
    # fields) doesn't see an unexpected key.
    geo_form_values = geographic.pop("_form_values")

    canonical: dict = {
        "geographic": geographic,
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


register_connector(KoboConnector())
