"""Network layer: pulls public Philadelphia records. No API keys, standard library only.

A failed source is recorded in data["gaps"] instead of raising, because the analysis must be
able to say "could not check" rather than mistake a timeout for a clean record.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

AIS_URL = "https://api.phila.gov/ais/v1/search/"
CARTO_URL = "https://phl.carto.com/api/v2/sql"
FEMA_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
HEADERS = {"User-Agent": "philly-property-analyzer/1.0 (open-source Claude skill)"}
# Web Mercator stretches distance at Philadelphia's latitude; multiply real meters by this.
MERCATOR_SCALE = 1.3


STREET_SUFFIXES = {"ST", "AVE", "RD", "LN", "DR", "CT", "PL", "BLVD", "TER", "WAY", "CIR", "PKWY", "HWY"}


class SourceError(Exception):
    pass


def _get_json(url, params=None, timeout=45, retries=2):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            last = exc
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            last = exc
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise SourceError(str(last))


def carto(sql):
    data = _get_json(CARTO_URL, {"q": sql})
    if data is None:
        raise SourceError("not found")
    if "error" in data:
        raise SourceError("; ".join(data["error"]))
    return data.get("rows", [])


def sql_str(value):
    return "'" + str(value).replace("'", "''") + "'"


def resolve_address(address):
    """Return AIS candidates for a free-text address. Empty list means no match."""
    url = AIS_URL + urllib.parse.quote(address.strip())
    data = _get_json(url, {"include_units": "false"})
    if not data:
        return []
    out = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        coords = (feature.get("geometry") or {}).get("coordinates") or [None, None]
        out.append({
            "address": props.get("street_address"),
            "opa_account_num": props.get("opa_account_num") or "",
            "zip_code": props.get("zip_code"),
            "unit_num": props.get("unit_num"),
            "zoning": props.get("zoning"),
            "historic_site": props.get("historic_site"),
            "historic_district": props.get("historic_district"),
            "census_tract": props.get("census_tract_2020"),
            "council_district": props.get("council_district_2024"),
            "police_district": props.get("police_district"),
            "planning_district": props.get("planning_district"),
            "elementary_school": props.get("elementary_school"),
            "middle_school": props.get("middle_school"),
            "high_school": props.get("high_school"),
            "rubbish_recycle_day": props.get("rubbish_recycle_day"),
            "lon": coords[0],
            "lat": coords[1],
        })
    return out


def outside_philadelphia(raw):
    """Return why an address is clearly not in Philadelphia, or None.

    The address service ignores city names, so '123 Main St, Cherry Hill, NJ' would otherwise match
    a Philadelphia street of the same name and produce a confident report on the wrong house.
    """
    text = raw.strip()
    zip_match = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", text)
    if zip_match and not zip_match.group(1).startswith("191"):
        return f"ZIP code {zip_match.group(1)} is outside Philadelphia"
    state = re.search(r",?\s*\b([A-Z]{2})\b\s*(?:\d{5}(?:-\d{4})?)?\s*$", text, flags=re.I)
    if state and state.group(1).upper() in {"NJ", "DE", "NY", "MD"}:
        return f"this address is in {state.group(1).upper()}"
    city = re.search(r",\s*([A-Za-z .'-]+?)\s*,\s*(?:PA|PENNSYLVANIA)\b", text, flags=re.I)
    if city and not re.fullmatch(r"phil(adelphia|a|ly)\.?", city.group(1).strip(), flags=re.I):
        return f"{city.group(1).strip()} is outside Philadelphia"
    return None


def split_address(raw):
    """Separate '1902 Pine St, Unit 2R, Philadelphia, PA 19103' into ('1902 Pine St', '2R')."""
    text = re.sub(r",?\s*(PHILADELPHIA|PHILLY|PHILA)\b.*$", "", raw.strip(), flags=re.I)
    text = re.sub(r",?\s*(?:PA|PENNSYLVANIA)?\s*\b191\d{2}(?:-\d{4})?\s*$", "", text, flags=re.I)
    text = re.sub(r",\s*(?:PA|PENNSYLVANIA)\s*$", "", text, flags=re.I)
    match = re.search(r"[,\s]+(?:UNIT|APT|APARTMENT|STE|SUITE|#)\s*#?\s*([A-Z0-9-]+)\s*$", text, flags=re.I)
    # "100 Apartment Rd" is a street, not apartment "RD".
    if not match or match.group(1).upper() in STREET_SUFFIXES or len(text[:match.start()].split()) < 2:
        return text.strip(" ,"), None
    return text[:match.start()].strip(" ,"), match.group(1).upper()


def _opa_units(location, unit=None):
    where = f"location={sql_str(location)}"
    if unit:
        where += f" AND unit={sql_str(unit)}"
    return carto(
        "SELECT parcel_number, location, unit, zip_code, zoning, ST_X(the_geom) AS lon, ST_Y(the_geom) AS lat "
        f"FROM opa_properties_public WHERE {where} ORDER BY unit LIMIT 40"
    )


def _from_opa_row(row, base=None):
    candidate = dict(base or {})
    address = row["location"] + (f" UNIT {row['unit']}" if row.get("unit") else "")
    candidate.update({
        "address": address, "opa_account_num": row["parcel_number"], "unit_num": row.get("unit"),
        "zip_code": candidate.get("zip_code") or (row.get("zip_code") or "")[:5],
        "zoning": candidate.get("zoning") or row.get("zoning"),
        "lon": candidate.get("lon") if candidate.get("lon") is not None else row.get("lon"),
        "lat": candidate.get("lat") if candidate.get("lat") is not None else row.get("lat"),
    })
    return candidate


def resolve(raw):
    """Turn user text into one parcel. Returns (candidate, None), or (None, error payload).

    The address service has blind spots: it drops an unknown unit silently and returns the building,
    and it often has no account number for condos or range addresses like '151-59 N 2ND ST'. The
    assessor's table fills those gaps, and a unit that can't be matched is stated rather than hidden.
    """
    outside = outside_philadelphia(raw)
    if outside:
        return None, {"error": "outside_philadelphia", "query": raw, "detail": outside,
                      "hint": "This skill only covers Philadelphia County."}
    base_text, unit = split_address(raw)
    candidates = resolve_address(base_text)
    best = candidates[0] if candidates else None
    location = (best or {}).get("address") or re.sub(r"\s+", " ", base_text).upper()
    opa_rows = _opa_units(location)

    if unit:
        match = [r for r in opa_rows if (r.get("unit") or "").upper() == unit]
        if match:
            candidate = _from_opa_row(match[0], best)
            candidate["scope_note"] = ("This is the unit's own record. Violations and permits on shared areas "
                                       "may be filed under the building, so check the building address too.")
            return candidate, None
        if best and best.get("opa_account_num"):
            candidate = dict(best)
            candidate["scope_note"] = (f"Unit {unit} has no separate property record, so this report covers the "
                                       "whole building, not that unit alone.")
            return candidate, None
        if opa_rows:
            return None, {"error": "unit_not_found", "query": raw, "units_found": [r.get("unit") for r in opa_rows],
                          "hint": "Re-run with one of these units."}
        return None, {"error": "address_not_found", "query": raw}

    usable = [c for c in candidates if c.get("opa_account_num")]
    exact = [c for c in usable if c is best]
    if exact:
        return exact[0], None
    if len(opa_rows) == 1:
        return _from_opa_row(opa_rows[0], best), None
    if opa_rows:
        return None, {"error": "multiple_matches", "query": raw,
                      "candidates": [{"address": r["location"], "unit": r.get("unit"),
                                      "opa_account_num": r["parcel_number"]} for r in opa_rows],
                      "hint": "This address has several units. Re-run with 'Unit X'."}
    if usable:
        return None, {"error": "multiple_matches", "query": raw,
                      "candidates": [{"address": c["address"], "opa_account_num": c["opa_account_num"]} for c in usable[:15]],
                      "hint": "No exact match. Re-run with one of these addresses."}
    return None, {"error": "address_not_found", "query": raw,
                  "hint": "Check the spelling and use a Philadelphia street address."}


def _point(lon, lat):
    return f"ST_Transform(ST_SetSRID(ST_Point({float(lon)},{float(lat)}),4326),3857)"


def _near(lon, lat, meters, column="the_geom_webmercator"):
    return f"ST_DWithin({column}, {_point(lon, lat)}, {meters * MERCATOR_SCALE:.0f})"


OPA_COLUMNS = (
    "parcel_number, location, unit, owner_1, owner_2, mailing_street, mailing_address_1, "
    "mailing_care_of, mailing_city_state, mailing_zip, category_code, category_code_description, "
    "building_code_description, building_code_description_new, market_value, taxable_land, "
    "taxable_building, exempt_land, exempt_building, homestead_exemption, sale_date, sale_price, "
    "year_built, year_built_estimate, total_livable_area, total_area, number_of_bedrooms, "
    "number_of_bathrooms, number_stories, exterior_condition, interior_condition, "
    "zoning, assessment_date"
)


def _fetch_opa(acct, **_):
    rows = carto(f"SELECT {OPA_COLUMNS} FROM opa_properties_public WHERE parcel_number={sql_str(acct)} LIMIT 1")
    return rows[0] if rows else None


def _fetch_assessments(acct, **_):
    return carto(
        "SELECT year, market_value, taxable_land, taxable_building, exempt_land, exempt_building "
        f"FROM assessments WHERE parcel_number={sql_str(acct)} ORDER BY year"
    )


def _fetch_documents(acct, today, **_):
    return carto(
        "SELECT document_type, display_date, grantors, grantees, total_consideration, "
        "cash_consideration, property_count, document_id FROM rtt_summary "
        f"WHERE opa_account_num={sql_str(acct)} AND display_date <= {sql_str(today.isoformat())} "
        "ORDER BY display_date DESC LIMIT 300"
    )


def _fetch_violations(acct, **_):
    return carto(
        "SELECT violationnumber, casenumber, casetype, casestatus, caseprioritydesc, violationdate, "
        "violationcode, violationcodetitle, violationstatus, violationresolutiondate, "
        "mostrecentinvestigation, underappeal FROM violations "
        f"WHERE opa_account_num={sql_str(acct)} ORDER BY violationdate DESC LIMIT 500"
    )


def _fetch_permits(acct, **_):
    return carto(
        "SELECT permitnumber, permittype, permitdescription, typeofwork, approvedscopeofwork, "
        "permitissuedate, permitcompleteddate, status, contractorname, mostrecentinsp, numberofunits, "
        "certificateofoccupancyrequired, certificateofoccupancydate FROM permits "
        f"WHERE opa_account_num={sql_str(acct)} ORDER BY permitissuedate DESC LIMIT 300"
    )


def _fetch_licenses(acct, **_):
    return carto(
        "SELECT licensenum, licensetype, rentalcategory, licensestatus, initialissuedate, "
        "expirationdate, inactivedate, numberofunits, owneroccupied, legalentitytype, unit_num "
        f"FROM business_licenses WHERE opa_account_num={sql_str(acct)} "
        "AND licensetype IN ('Rental','Vacant Residential Property / Lot') "
        "ORDER BY initialissuedate DESC LIMIT 100"
    )


def _safety_query(table, acct):
    return carto(
        "SELECT casenumber, violationcodetitle, violationdate, casecompleteddate, "
        f"violationresolutiondate, mostrecentinvestigation FROM {table} "
        f"WHERE opa_account_num={sql_str(acct)} ORDER BY violationdate DESC LIMIT 20"
    )


def _fetch_unsafe(acct, **_):
    return _safety_query("unsafe", acct)


def _fetch_imm_dang(acct, **_):
    return _safety_query("imm_dang", acct)


def _fetch_clean_seal(acct, **_):
    return carto(
        "SELECT casegroup, acttype, actdate, caseresolution FROM li_clean_seal "
        f"WHERE opa_account_num={sql_str(acct)} ORDER BY actdate DESC LIMIT 20"
    )


def _fetch_demolitions(acct, **_):
    return carto(
        "SELECT record_type, typeofwork, city_demo, start_date, completed_date, status FROM demolitions "
        f"WHERE opa_account_num={sql_str(acct)} ORDER BY start_date DESC LIMIT 10"
    )


def _fetch_neighbors(acct, lon, lat, today, **_):
    """Open unsafe/dangerous cases and recent demolitions within about 80 feet: rowhouses share walls."""
    near = _near(lon, lat, 25)
    not_self = f"opa_account_num<>{sql_str(acct)}"
    since = (today - timedelta(days=365 * 3)).isoformat()
    open_cases = []
    for table, label in (("imm_dang", "Imminently dangerous"), ("unsafe", "Unsafe")):
        rows = carto(
            f"SELECT address, violationdate FROM {table} WHERE casecompleteddate IS NULL "
            f"AND {not_self} AND {near} LIMIT 10"
        )
        open_cases += [dict(row, kind=label) for row in rows]
    demos = carto(
        f"SELECT address, start_date, completed_date, status, city_demo FROM demolitions "
        f"WHERE {not_self} AND {near} AND start_date >= {sql_str(since)} LIMIT 10"
    )
    return {"open_cases": open_cases, "demolitions": demos}


def _fetch_comps(acct, lon, lat, today, category, **_):
    """Recent single-parcel deeds nearby. Widens once if a block is too thin to say anything."""
    since = (today - timedelta(days=730)).isoformat()
    for radius in (300, 600):
        rows = carto(
            "SELECT r.display_date, r.street_address, r.total_consideration, r.grantors, r.grantees, "
            "o.total_livable_area, o.number_of_bedrooms, o.exterior_condition, o.interior_condition, "
            "o.year_built FROM rtt_summary r JOIN opa_properties_public o "
            "ON r.opa_account_num=o.parcel_number "
            "WHERE r.document_type='DEED' AND r.total_consideration>=25000 AND r.property_count=1 "
            f"AND r.display_date BETWEEN {sql_str(since)} AND {sql_str(today.isoformat())} "
            f"AND o.category_code={sql_str(category)} AND o.parcel_number<>{sql_str(acct)} "
            f"AND {_near(lon, lat, radius, 'o.the_geom_webmercator')} "
            "ORDER BY r.display_date DESC LIMIT 200"
        )
        if len(rows) >= 8:
            break
    return {"radius_m": radius, "rows": rows}


def _fetch_crime(lon, lat, today, **_):
    since = (today - timedelta(days=365)).isoformat()
    return carto(
        "SELECT text_general_code AS category, count(*) AS n FROM incidents_part1_part2 "
        f"WHERE dispatch_date >= {sql_str(since)} AND {_near(lon, lat, 400)} "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 25"
    )


def _fetch_momentum(lon, lat, today, **_):
    recent = (today - timedelta(days=730)).isoformat()
    prior = (today - timedelta(days=1460)).isoformat()
    rows = carto(
        f"SELECT sum(CASE WHEN permitissuedate >= {sql_str(recent)} THEN 1 ELSE 0 END) AS recent, "
        f"sum(CASE WHEN permitissuedate < {sql_str(recent)} THEN 1 ELSE 0 END) AS prior "
        f"FROM permits WHERE permitissuedate >= {sql_str(prior)} "
        "AND permittype IN ('Residential Building','Building','Demolition') "
        f"AND {_near(lon, lat, 300)}"
    )
    return rows[0] if rows else {}


def _fetch_flood(lon, lat, **_):
    data = _get_json(FEMA_URL, {
        "geometry": f"{float(lon)},{float(lat)}", "geometryType": "esriGeometryPoint", "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects", "outFields": "FLD_ZONE,SFHA_TF,ZONE_SUBTY",
        "returnGeometry": "false", "f": "json",
    }, timeout=25)
    if data is None or "error" in data:
        raise SourceError("FEMA flood map unavailable")
    features = data.get("features", [])
    return features[0]["attributes"] if features else {}


def _fetch_portfolio(owner, **_):
    """Only called for business owners; see analysis.is_entity for why individuals are excluded."""
    owner_sql = sql_str(owner)
    parcels = carto(
        "SELECT count(*) AS parcels, sum(market_value) AS total_value FROM opa_properties_public "
        f"WHERE owner_1={owner_sql} OR owner_2={owner_sql}"
    )[0]
    open_rows = carto(
        "SELECT address, count(*) AS n FROM violations "
        f"WHERE opa_owner={owner_sql} AND violationstatus='OPEN' "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 10"
    )
    licenses = carto(
        "SELECT count(*) AS n FROM business_licenses "
        f"WHERE opa_owner={owner_sql} AND licensetype='Rental' AND licensestatus='Active'"
    )[0]
    return {
        "owner": owner,
        "parcels": parcels.get("parcels") or 0,
        "total_value": parcels.get("total_value") or 0,
        "open_violation_addresses": open_rows,
        "open_violations": sum(row["n"] for row in open_rows),
        "open_violations_capped": len(open_rows) == 10,
        "active_rental_licenses": licenses.get("n") or 0,
    }


def gather(candidate, today=None, entity_check=None):
    """Collect every dataset for one resolved address. Never raises for a single failed source."""
    today = today or date.today()
    acct = candidate["opa_account_num"]
    if not re.fullmatch(r"\d{9}", acct or ""):
        raise SourceError(f"Address has no usable OPA account number: {acct!r}")

    data = {"address": candidate, "as_of": today.isoformat(), "gaps": {}}

    def run(name, fn, **kwargs):
        try:
            return name, fn(**kwargs), None
        except Exception as exc:  # recorded as a gap and surfaced in the report
            return name, None, str(exc)

    name, opa, err = run("opa", _fetch_opa, acct=acct)
    if err:
        raise SourceError(f"Could not read the property record: {err}")
    if not opa:
        raise SourceError(f"No property record for OPA account {acct}")
    data["opa"] = opa
    geo = {"lon": candidate.get("lon"), "lat": candidate.get("lat")}

    jobs = {
        "assessments": (_fetch_assessments, {"acct": acct}),
        "documents": (_fetch_documents, {"acct": acct, "today": today}),
        "violations": (_fetch_violations, {"acct": acct}),
        "permits": (_fetch_permits, {"acct": acct}),
        "licenses": (_fetch_licenses, {"acct": acct}),
        "unsafe": (_fetch_unsafe, {"acct": acct}),
        "imm_dang": (_fetch_imm_dang, {"acct": acct}),
        "clean_seal": (_fetch_clean_seal, {"acct": acct}),
        "demolitions": (_fetch_demolitions, {"acct": acct}),
    }
    if geo["lon"] is not None:
        jobs.update({
            "neighbors": (_fetch_neighbors, {"acct": acct, "today": today, **geo}),
            "comps": (_fetch_comps, {"acct": acct, "today": today, "category": opa.get("category_code"), **geo}),
            "crime": (_fetch_crime, {"today": today, **geo}),
            "momentum": (_fetch_momentum, {"today": today, **geo}),
            "flood": (_fetch_flood, geo),
        })
    else:
        for key in ("neighbors", "comps", "crime", "momentum", "flood"):
            data["gaps"][key] = "no map coordinates for this address"

    owner = (opa.get("owner_1") or "").strip()
    if owner and entity_check and entity_check(owner):
        jobs["portfolio"] = (_fetch_portfolio, {"owner": owner})

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(run, key, fn, **kwargs) for key, (fn, kwargs) in jobs.items()]
        for future in futures:
            key, value, err = future.result()
            data[key] = value
            if err:
                data["gaps"][key] = err
    return data
