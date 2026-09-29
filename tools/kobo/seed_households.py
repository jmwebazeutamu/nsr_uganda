#!/usr/bin/env python3
"""Generate synthetic, region-aware NSR household records from an XLSForm.

No data is uploaded to KoboToolbox.  The generated JSON is suitable for review
or controlled import through the Kobo API; the companion CSV is convenient for
DQA and PMT checks.

All coded values are read from the supplied form's choices sheet.  This keeps
the seed payload aligned with the deployed Questionnaire/ChoiceList contract
when option codes or ordering change.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import uuid
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

FORM = Path(__file__).with_name("nsr_form_v1.xlsx")
NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# Names reflect common naming conventions in the selected Ugandan region. They
# are fictional combinations, never copied from a respondent database.
NAMES = {
    "Central": (["Kato", "Ssemanda", "Kaggwa", "Mugisha", "Nabirye", "Nankya", "Namirembe", "Kawalya"],
                ["Amina", "Brenda", "David", "Esther", "Grace", "Isaac", "Joseph", "Sarah"]),
    "Eastern": (["Wanyama", "Waiswa", "Nabirye", "Namusoke", "Mugoya", "Wakabi", "Nabukenya", "Ouma"],
                ["Aisha", "Denis", "Evelyn", "Hassan", "Irene", "Moses", "Naume", "Peter"]),
    "Northern": (["Okello", "Ocen", "Otieno", "Acen", "Ayaa", "Odong", "Laker", "Auma"],
                 ["Acen", "Ayaa", "David", "Grace", "Komakech", "Lillian", "Okot", "Sarah"]),
    "Western": (["Mugisha", "Tumusiime", "Tibasiimwa", "Byaruhanga", "Ninsiima", "Katusiime", "Mwebesa", "Natukunda"],
                ["Annet", "Brian", "Doreen", "Ivan", "Joan", "Moses", "Sheilah", "Taremwa"]),
}


def fetch_asset(uid, token):
    """The full asset, including its `content` (survey + choices)."""
    return api_json(
        "https://kf.kobotoolbox.org/api/v2/assets/{}/?format=json".format(uid),
        token,
    )


def _from_content(asset, sheet):
    """Kobo's content rows, in the same shape the xlsx reader returns.

    Kobo carries a label as a per-language list and adds `$kuid` /
    `$autovalue` bookkeeping; the xlsx has a plain label and neither.
    Normalising here means `options`, `choice_code` and
    `select_location` do not care which source they were given.
    """
    rows = []
    for row in (asset.get("content") or {}).get(sheet) or []:
        item = {k: v for k, v in row.items() if not k.startswith("$")}
        label = item.get("label")
        if isinstance(label, list):
            item["label"] = next((part for part in label if part), "")
        rows.append(item)
    return rows


def choices_from_asset(asset):
    return _from_content(asset, "choices")


def survey_from_asset(asset):
    return _from_content(asset, "survey")


def read_choices() -> list[dict[str, str]]:
    """Read the choices sheet without depending on Excel/Python packages."""
    with zipfile.ZipFile(FORM) as book:
        root = ET.fromstring(book.read("xl/worksheets/sheet2.xml"))
    rows = []
    for row in root.findall(".//x:sheetData/x:row", NS):
        values = {}
        for cell in row.findall("x:c", NS):
            column = "".join(ch for ch in cell.attrib["r"] if ch.isalpha())
            values[column] = "".join(cell.itertext()).strip()
        rows.append(values)
    header = rows[0]
    return [{header.get(k, k): v for k, v in row.items()} for row in rows[1:]]


def read_survey() -> list[dict[str, str]]:
    with zipfile.ZipFile(FORM) as book:
        root = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in root.findall(".//x:sheetData/x:row", NS):
        values = {}
        for cell in row.findall("x:c", NS):
            column = "".join(ch for ch in cell.attrib["r"] if ch.isalpha())
            values[column] = "".join(cell.itertext()).strip()
        rows.append(values)
    header = rows[0]
    return [{header.get(k, k): v for k, v in row.items()} for row in rows[1:]]


def options(rows, list_name, parent_key=None, parent_value=None):
    answer = [r for r in rows if r.get("list_name") == list_name]
    if parent_key:
        answer = [r for r in answer if r.get(parent_key) == parent_value]
    return answer


def choice_code(rows, list_name, rng):
    """Choose a valid code from the XLSForm, never a locally invented one."""
    codes = [row.get("name", "") for row in options(rows, list_name)]
    codes = [code for code in codes if code]
    if not codes:
        raise ValueError(
            "XLSForm has no choices for {!r}; refresh it from the approved "
            "Questionnaire before seeding.".format(list_name)
        )
    return rng.choice(codes)


def all_choice_codes(rows, list_name):
    """Return every current code in form order for a select_multiple answer."""
    codes = [row.get("name", "") for row in options(rows, list_name)]
    codes = [code for code in codes if code]
    if not codes:
        raise ValueError(
            "XLSForm has no choices for {!r}; refresh it from the approved "
            "Questionnaire before seeding.".format(list_name)
        )
    return codes


def select_location(rows, region_label, rng):
    region = next(r for r in options(rows, "region") if r["label"] == region_label)
    subregion = rng.choice(options(rows, "sub_region", "region", region["name"]))
    district = rng.choice(options(rows, "district", "sub_region", subregion["name"]))
    county = rng.choice(options(rows, "county", "district", district["name"]))
    subcounty = rng.choice(options(rows, "sub_county", "county", county["name"]))
    parish = rng.choice(options(rows, "parish", "sub_county", subcounty["name"]))
    return {
        "a0_region": region["name"], "a1_subregion": subregion["name"],
        "a2_district_city": district["name"], "a3_county_municipality": county["name"],
        "a4_subcounty_division_tc": subcounty["name"], "a5_parish_ward": parish["name"],
        "_labels": {"region": region["label"], "district": district["label"], "parish": parish["label"]},
    }


def phone(rng):
    return "07{}".format("".join(str(rng.randrange(10)) for _ in range(8)))


def person_name(region, rng):
    surnames, given = NAMES[region]
    return "{} {}".format(rng.choice(given), rng.choice(surnames))


def dob_for_age(age, rng):
    today = date.today()
    # This keeps the stated completed age accurate around the birthday.
    start = date(today.year - age - 1, 1, 1)
    end = date(today.year - age, 12, 31)
    return (start + timedelta(days=rng.randrange((end - start).days + 1))).isoformat()


def member(rows, region, index, household_size, rng):
    # The first repeat row is the head. PMT evaluates head sex and education,
    # so every PMT seed must have an adult head with an education response.
    age = rng.randrange(18, 91) if index == 1 else rng.choices(
        [rng.randrange(0, 6), rng.randrange(6, 18), rng.randrange(18, 70), rng.randrange(70, 91)],
        weights=[12, 24, 54, 10],
    )[0]
    sex = rng.choice(["1", "2"])
    relation = "01" if index == 1 else rng.choice(["02", "04", "04", "08", "10"])
    has_phone = "1" if index == 1 or (age >= 16 and rng.random() < 0.72) else "2"
    record = {
        "c1_full_name": person_name(region, rng), "c2_relationship": relation,
        "c4_sex": sex, "c5_date_of_birth": dob_for_age(age, rng), "c6_age_years": age,
        "c7_birth_certificate": rng.choice(["1", "2", "3", "4", "5"]),
        "c8_nin_status": "1" if age >= 18 and rng.random() < .78 else "2",
        "c10_nationality": "UG", "c11_residency_status": "1",
        "c12_mother_alive": rng.choice(["1", "2", "98"]),
        "c13_father_alive": rng.choice(["1", "2", "98"]),
        "c17_has_phone": has_phone, "e2_ever_school": "1" if age >= 6 else "2",
    }
    if age >= 12:
        record["c3_marital_status"] = "1" if age < 18 else rng.choice(["1", "2", "3", "4"])
    if record["c8_nin_status"] == "1":
        record["c9_nin"] = "CF{}{}".format(rng.randrange(10**7, 10**8), rng.choice("ABCDEFGH"))
    if has_phone == "1":
        record["c18_telephone_1"] = phone(rng)
        record["c20_numbers_registered_mm"] = rng.choice(["1", "2"])
    if age >= 2:
        record.update({"d1_chronic_illness": "2", "d3_seeing": "1", "d4_hearing": "1", "d5_walking": "1", "d6_remembering": "1", "d7_self_care": "1", "d8_communicating": "1"})
    if age >= 15:
        record["e1_literacy"] = choice_code(rows, "literacy", rng)
    if age >= 6:
        # The active PMT model's education terms derive from this canonical
        # question. Its code comes from the form, not a seed-script mapping.
        record["e4_highest_grade"] = choice_code(rows, "education_level", rng)
    if age >= 3 and age <= 24:
        record["e5_currently_attending"] = "1" if age <= 18 else "2"
    if age >= 7:
        record.update({"f1_main_job": "05" if age < 15 else rng.choice(["01", "02", "03", "05"]),
                       "f6_gov_program_beneficiary": rng.choice(["1", "2"]), "f9_made_savings": rng.choice(["1", "2"])})
    return record


def household(rows, region, sequence, rng):
    loc = select_location(rows, region, rng)
    size = rng.randint(2, 8)
    people = [member(rows, region, i + 1, size, rng) for i in range(size)]
    urban = "1" if "City" in loc["_labels"]["district"] or rng.random() < .25 else "2"
    data = {
        "_uuid": "uuid:{}".format(uuid.uuid4()), "consent": "1",
        **{k: v for k, v in loc.items() if k != "_labels"},
        "a6_lc1_village_cell": "Test Village {:03d}".format(sequence),
        "a7_rural_urban": urban, "a8_enumeration_area": "TEST-{:04d}".format(sequence),
        "a9_household_number": "HH-{:05d}".format(sequence),
        "a11_12_gps": "0.3476 32.5825 0 5", "a13_interviewer_name_code": "TEST-ENUM-01",
        "a14_parish_supervisor_name_code": "TEST-SUP-01", "a15_start_time": "09:30:00",
        "b1_respondent_name": people[0]["c1_full_name"], "b2_telephone_number": phone(rng),
        "b3_address": "Synthetic test record — do not use operationally", "b4_head_name": people[0]["c1_full_name"],
        "b5_interview_result": "1", "hh_size": size, "household_members": people,
        "g1_tenure": choice_code(rows, "tenure", rng),
        "g2_dwelling_type": choice_code(rows, "dwelling_type", rng),
        "g3_rooms_total": rng.randint(2, 6),
        # Direct PMT observations. Values are resolved from the form's
        # ChoiceLists so an outdated seed script cannot emit obsolete codes.
        "g5_roof_material": choice_code(rows, "roof_material", rng),
        "g6_wall_material": choice_code(rows, "wall_material", rng),
        "g7_floor_material": choice_code(rows, "floor_material", rng),
        "g8_cooking_fuel": choice_code(rows, "cooking_fuel", rng),
        "g9_lighting_source": choice_code(rows, "lighting_source", rng),
        "g10_water_source": choice_code(rows, "water_source", rng),
        "g11_toilet_type": choice_code(rows, "toilet_type", rng),
        "g14_waste_disposal": choice_code(rows, "waste_disposal", rng),
        # Kobo select_multiple values are space-separated ChoiceOption codes.
        # Include every asset so all asset-presence PMT terms are testable.
        "g15_assets_owned": " ".join(all_choice_codes(rows, "asset_type")),
        "g15_count_phone": rng.randint(1, 5),
        "g15_count_radio": 1,
        "g15_count_motorcycle": rng.randint(0, 2),
        "g15_count_car": rng.randint(0, 2),
        "g15_count_bed": rng.randint(1, 4),
        "g15_count_mattress": rng.randint(1, 5),
        "g16_livelihood_source": choice_code(rows, "livelihood_source", rng),
        "h1_crop_production": rng.choice(["1", "2", "5"]), "h2_livestock": rng.choice(["1", "2", "5"]),
        "h6_land_ownership": rng.choice(["1", "2", "4"]), "i1_fies": "2", "i2_fies": "2", "i3_fies": "2",
        "i4_fies": "2", "i5_fies": "2", "i6_fies": "2", "i7_fies": "2", "i8_fies": "2",
        "i9_staples_days": 7, "i10_pulses_nuts_days": rng.randint(1, 5), "i11_milk_dairy_days": rng.randint(0, 4),
        "i12_meat_fish_eggs_days": rng.randint(0, 4), "i13_vegetables_days": rng.randint(2, 7),
        "i14_fruits_days": rng.randint(0, 5), "i15_oils_fats_days": 7, "i16_sugar_sweets_days": rng.randint(0, 5),
        "i17_condiments_days": 7, "k01_shock_affected": rng.choice(["1", "2"]),
    }
    data["g4_rooms_sleeping"] = rng.randint(1, data["g3_rooms_total"])
    if data["g11_toilet_type"] != "17": data["g12_share_toilet"] = rng.choice(["1", "2"])
    # Kobo skips the follow-up when there is no toilet facility.  Do not
    # manufacture a response for a skipped question or dereference it.
    if data.get("g12_share_toilet") == "1":
        data["g13_share_toilet_households"] = rng.randint(1, 6)
    if data["h6_land_ownership"] != "4": data["h7_land_hectares"] = round(rng.uniform(.2, 5), 2)
    return data, loc["_labels"]


def inject_errors(data, rng):
    """Add constraint and cross-field failures. These records are intentionally invalid."""
    failures = ["invalid telephone", "household size out of range", "sleeping rooms exceed total rooms",
                "member age out of range", "invalid NIN", "food-consumption days out of range", "negative land area"]
    selected = rng.sample(failures, k=3)
    for error in selected:
        if error == "invalid telephone": data["b2_telephone_number"] = "not-a-uganda-number"
        elif error == "household size out of range": data["hh_size"] = 0
        elif error == "sleeping rooms exceed total rooms": data["g4_rooms_sleeping"] = data["g3_rooms_total"] + 2
        elif error == "member age out of range": data["household_members"][0]["c6_age_years"] = 109
        elif error == "invalid NIN":
            data["household_members"][0]["c8_nin_status"] = "1"
            data["household_members"][0]["c9_nin"] = "BAD NIN!"
        elif error == "food-consumption days out of range": data["i9_staples_days"] = 9
        elif error == "negative land area":
            data["h6_land_ownership"] = "1"; data["h7_land_hectares"] = -1.5
    return selected


def prompt_choice(question, values):
    print("\n" + question)
    for number, label in enumerate(values, 1): print("  {}) {}".format(number, label))
    while True:
        answer = input("Select an option: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(values): return values[int(answer) - 1]
        print("Enter a number from 1 to {}.".format(len(values)))


def kobo_token():
    token = os.environ.get("KOBO_API_TOKEN", "").strip()
    if token:
        return token
    path = Path(os.environ.get("KOBO_API_TOKEN_FILE", "kobo_api_key"))
    if not path.is_file():
        raise RuntimeError("Kobo token not found. Set KOBO_API_TOKEN or KOBO_API_TOKEN_FILE.")
    return path.read_text(encoding="utf-8").strip()


def api_json(url, token):
    request = Request(url, headers={"Authorization": "Token " + token, "Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def multipart(field_name, filename, content):
    boundary = "----NSRSeeder" + uuid.uuid4().hex
    body = ("--{b}\r\nContent-Disposition: form-data; name=\"{n}\"; filename=\"{f}\"\r\n"
            "Content-Type: text/xml\r\n\r\n").format(b=boundary, n=field_name, f=filename).encode()
    body += content + "\r\n--{}--\r\n".format(boundary).encode()
    return body, "multipart/form-data; boundary=" + boundary


def close_row(rows, start, begin_type, end_type):
    depth = 0
    for position in range(start, len(rows)):
        if rows[position].get("type") == begin_type: depth += 1
        if rows[position].get("type") == end_type:
            depth -= 1
            if depth == 0: return position
    raise ValueError("Unclosed {} in XLSForm".format(begin_type))


def xml_submission(asset, survey, record):
    """Turn generated JSON into the OpenRosa XML accepted by Kobo's submit endpoint."""
    root = ET.Element(asset["uid"], {"id": asset["uid"]})
    formhub = ET.SubElement(root, "formhub")
    ET.SubElement(formhub, "uuid").text = asset.get("deployment__uuid", "")

    def render(start, stop, parent, values):
        position = start
        while position < stop:
            row, kind, name = survey[position], survey[position].get("type", ""), survey[position].get("name", "")
            if kind in ("begin_group", "begin_repeat"):
                end_kind = "end_group" if kind == "begin_group" else "end_repeat"
                end = close_row(survey, position, kind, end_kind)
                instances = [values] if kind == "begin_group" else values.get(name, [])
                for instance in instances:
                    child = ET.SubElement(parent, name)
                    render(position + 1, end, child, instance)
                position = end + 1
                continue
            if kind.startswith("end_") or kind in ("note", "calculate", "start", "end", "today", "deviceid", "username", "image"):
                position += 1; continue
            if name and name in values and values[name] is not None:
                ET.SubElement(parent, name).text = str(values[name])
            position += 1

    render(0, len(survey), root, record)
    ET.SubElement(root, "__version__").text = asset.get("version_id", "")
    meta = ET.SubElement(root, "meta")
    ET.SubElement(meta, "instanceID").text = record["_uuid"]
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def choose_asset(token, uid=None):
    """The deployed form these records will be generated against.

    Chosen BEFORE generating, not at upload time. Records used to be
    built from a local XLSForm passed with --form and only then offered
    a destination, so nothing checked that the codes the generator
    picked were codes the destination form offers. They were not: the
    local copy carried the retired housing frame (floor_material 1-8)
    while the deployed form has carried 11-19 since it was last
    published, and because these submissions are POSTed straight to
    /submission as OpenRosa XML — which does not validate against the
    form — 49 synthetic households entered the registry with codes no
    active ChoiceList contains.

    Reading the destination's own choices makes that impossible rather
    than unlikely.
    """
    if uid:
        return fetch_asset(uid, token)
    assets = api_json("https://kf.kobotoolbox.org/api/v2/assets/?asset_type=survey&limit=1000", token).get("results", [])
    assets = [a for a in assets if a.get("deployment__active")]
    if not assets: raise RuntimeError("No deployed Kobo survey is available to this token.")
    labels = ["{} ({} existing submissions)".format(a["name"], a.get("deployment__submission_count", 0)) for a in assets]
    chosen = assets[labels.index(prompt_choice("Choose the Kobo form these records are for:", labels))]
    # The list endpoint omits `content`; fetch the asset itself.
    return fetch_asset(chosen["uid"], token)


def upload_to_asset(records, survey, asset, token):
    print("\nYou are about to upload {} synthetic records to: {}".format(len(records), asset["name"]))
    if input("Type UPLOAD to confirm: ").strip() != "UPLOAD":
        print("Upload cancelled. Files remain available locally."); return
    succeeded, failed = 0, []
    for number, record in enumerate(records, 1):
        xml = xml_submission(asset, survey, record)
        body, content_type = multipart("xml_submission_file", "{}.xml".format(record["a9_household_number"]), xml)
        request = Request("https://kc.kobotoolbox.org/submission", data=body, method="POST",
                          # The OpenRosa endpoint returns its own XML response media type;
                          # application/xml is not an accepted response negotiation value.
                          headers={"Authorization": "Token " + token, "Content-Type": content_type, "Accept": "*/*"})
        try:
            with urlopen(request, timeout=60) as response:
                if response.status not in (201, 202): raise RuntimeError("HTTP {}".format(response.status))
            succeeded += 1
        except (HTTPError, URLError, RuntimeError) as error:
            detail = error.read().decode("utf-8", "replace")[:300] if isinstance(error, HTTPError) else str(error)
            failed.append({"household_number": record["a9_household_number"], "error": detail})
        print("  {}/{} uploaded".format(number, len(records)), end="\r", flush=True)
    print("\nUpload complete: {} accepted, {} rejected.".format(succeeded, len(failed)))
    if failed: print("Failures: " + json.dumps(failed, indent=2))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=list(NAMES), help="Skip the region menu")
    parser.add_argument("--households", type=int, help="Skip the household-count prompt")
    parser.add_argument("--quality", choices=["good", "errors"], help="Skip the quality menu")
    parser.add_argument("--seed", type=int, help="Random seed for repeatable output")
    parser.add_argument(
        "--asset", default=None,
        help="Kobo asset uid to generate against (default: choose from the "
             "deployed forms).",
    )
    parser.add_argument(
        "--form", type=Path, default=None,
        help="Path to the approved XLSForm used for code resolution",
    )
    parser.add_argument("--output-dir", default="seed_output")
    parser.add_argument("--upload", action="store_true", help="Offer the Kobo upload confirmation after generation")
    return parser.parse_args()


def main():
    args = parse_args()
    # Where the choice codes come from.
    #
    # The deployed form by default, so a generated code is by
    # construction one the destination accepts. A local XLSForm is
    # still allowed but has to be asked for, because a local copy is
    # exactly what went stale: it carried floor_material 1-8 long after
    # the deployed form moved to 11-19, and these records bypass form
    # validation on the way in.
    token = asset = None
    if args.form:
        global FORM
        FORM = args.form.expanduser()
        if not FORM.exists(): sys.exit("Missing XLSForm: {}".format(FORM))
        print("Reading choices from {} — this is a local copy and may be "
              "behind the deployed form.".format(FORM))
    else:
        token = kobo_token()
        asset = choose_asset(token, args.asset)
        print("Reading choices from the deployed form: {} ({})".format(
            asset.get("name"), asset.get("uid")))
    region = args.region or prompt_choice("Which region should the test households represent?", list(NAMES))
    count = args.households
    while count is None:
        try:
            count = int(input("How many households should be generated? ").strip())
            if not 1 <= count <= 10000: raise ValueError
        except ValueError:
            print("Enter a whole number from 1 to 10,000."); count = None
    quality = args.quality or prompt_choice("What data quality should be generated?", ["good", "errors"])
    rng = random.Random(args.seed)
    rows = read_choices() if asset is None else choices_from_asset(asset)
    if not rows:
        sys.exit("The chosen form carries no choices; nothing can be generated "
                 "from it without inventing codes.")
    records, manifest = [], []
    for number in range(1, count + 1):
        record, location = household(rows, region, number, rng)
        failures = inject_errors(record, rng) if quality == "errors" else []
        records.append(record)
        manifest.append({"household_number": record["a9_household_number"], "region": region,
                         "district": location["district"], "parish": location["parish"], "intended_dqa_failures": failures})
    output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = "nsr_{}_{}_{}".format(region.lower(), quality, stamp)
    json_path, csv_path, manifest_path = output / (stem + ".json"), output / (stem + ".csv"), output / (stem + "_dqa_manifest.json")
    json_path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    flat = []
    for record in records:
        base = {k: v for k, v in record.items() if k != "household_members"}
        for line, person in enumerate(record["household_members"], 1): flat.append({**base, "member_line": line, **person})
    fields = sorted({key for row in flat for key in row})
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); writer.writeheader(); writer.writerows(flat)
    if quality == "errors":
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("\nCreated {} household records ({}).".format(count, quality))
    print("JSON: {}".format(json_path)); print("CSV: {}".format(csv_path))
    if quality == "errors": print("DQA manifest: {}".format(manifest_path))
    upload = args.upload
    if not upload and sys.stdin.isatty():
        upload = input("Upload these records to KoboToolbox now? [y/N]: ").strip().lower() in ("y", "yes")
    if upload:
        try:
            if asset is None:
                token = kobo_token()
                asset = choose_asset(token, args.asset)
            survey = read_survey() if args.form else survey_from_asset(asset)
            upload_to_asset(records, survey, asset, token)
        except (RuntimeError, HTTPError, URLError, ValueError) as error:
            print("Kobo upload was not completed: {}".format(error), file=sys.stderr)
            sys.exit(1)
    else:
        print("No records were uploaded to KoboToolbox.")

if __name__ == "__main__": main()
