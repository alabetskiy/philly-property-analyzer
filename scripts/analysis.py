"""Pure rules: turns gathered records into evidence-backed flags. No network calls.

Everything here is a lead to verify, not a finding of fact. Public records lag, contain errors, and
cannot see inside a house, so flags describe what the record shows and what to ask about it.
"""
import re
import statistics
from datetime import date, datetime, timedelta

# Rates checked against phila.gov and published notices on 2026-11-01. See references/philly-playbook.md.
TAX_RATE = 0.013998
HOMESTEAD_EXCLUSION = 100000
TRANSFER_TAX_RATE = 0.04578
RATES_CHECKED = "2026-11-01"
PAST_HOMESTEAD_AMOUNTS = {30000, 45000, 80000, 100000}

SEVERITY_ORDER = {"critical": 0, "warn": 1, "info": 2, "good": 3}
LENSES = [
    ("title", "Title & ownership"),
    ("code", "Code & safety"),
    ("permits", "Permits vs. the work"),
    ("tax", "Tax bill"),
    ("price", "Price vs. nearby sales"),
    ("rental", "Rental compliance"),
    ("site", "Site & zoning"),
]
# Which datasets a lens depends on: a missing one must read "couldn't check", never "nothing found".
LENS_SOURCES = {
    "title": ["documents"],
    "code": ["violations", "unsafe", "imm_dang", "neighbors", "clean_seal", "demolitions"],
    "permits": ["permits"],
    "tax": ["assessments"],
    "price": ["comps"],
    "rental": ["licenses"],
    "site": ["flood"],
}
LINKS = {
    "property": "https://property.phila.gov/",
    "atlas": "https://atlas.phila.gov/",
    "li": "https://li.phila.gov/",
    "tax": "https://tax-services.phila.gov/_/",
    "homestead": "https://www.phila.gov/services/payments-assistance-taxes/taxes/property-and-real-estate-taxes/get-real-estate-tax-relief/get-the-homestead-exemption/",
    "appeal": "https://www.phila.gov/services/property-lots-housing/property-taxes/appeal-a-property-assessment/",
    "fraud": "https://www.phila.gov/services/property-lots-housing/get-help-with-deed-or-mortgage-fraud/sign-up-for-deed-fraud-protection/",
    "abatement": "https://www.phila.gov/services/payments-assistance-taxes/taxes/property-and-real-estate-taxes/get-real-estate-tax-relief/get-a-property-tax-abatement/",
    "suitability": "https://www.phila.gov/services/permits-violations-licenses/get-a-certificate/get-a-certificate-of-rental-suitability/",
}

ENTITY_PATTERN = re.compile(
    r"\b(LLC|L L C|INC|CORP|CORPORATION|LP|L P|LTD|LLP|TRUST|TRUSTEE|PARTNERS|PARTNERSHIP|HOLDINGS|"
    r"PROPERTIES|PROPERTY|REALTY|INVESTMENTS?|ASSOCIATES|ASSOCIATION|ENTERPRISES|DEVELOPMENT|"
    r"GROUP|COMPANY|BANK|AUTHORITY|CITY OF|PHILA|SEPTA|CHURCH OF|UNIVERSITY|HOUSING)\b|\bCHURCH$"
)
PUBLIC_OWNER = re.compile(
    r"\b(CITY OF|SEPTA|AUTHORITY|REDEVELOPMENT|CHURCH OF|UNIVERSITY|COMMONWEALTH|UNITED STATES|SCHOOL DISTRICT|HOSPITAL)\b|\bCHURCH$"
)
NAME_NOISE = {"LLC", "INC", "CORP", "LP", "LTD", "LLP", "THE", "OF", "AND", "JR", "SR", "II", "III", "ET", "AL", "UX"}

# Claimed work maps to the permit types that would normally document it.
CLAIM_PERMITS = {
    "electrical": ("new electric / panel", {"Electrical"}),
    "plumbing": ("new plumbing", {"Plumbing"}),
    "hvac": ("new HVAC", {"Mechanical"}),
    "structural": ("structural or gut renovation", {"Residential Building", "Building"}),
    "addition": ("addition or added floor", {"Residential Building", "Building"}),
    "roof_deck": ("roof deck", {"Residential Building", "Building", "General Permit Minor"}),
    "basement": ("finished basement or added bath", {"Residential Building", "Building", "Plumbing"}),
    "units": ("added or converted units", {"Residential Building", "Building", "Zoning"}),
}
WORK_PERMIT_TYPES = {
    "Residential Building", "Building", "General Permit Minor", "General",
    "Electrical", "Plumbing", "Mechanical", "Fire Suppression",
}
ZONING_PLAIN = {
    "RSD": "single-family detached", "RSA": "single-family attached (rowhouse)",
    "RTA": "two-family attached", "RMX": "residential mixed-use", "RM": "multi-family",
    "CMX": "commercial mixed-use", "CA": "auto-oriented commercial",
    "IRMX": "industrial-residential mixed-use", "ICMX": "industrial-commercial mixed-use",
    "IMX": "industrial mixed-use", "I": "industrial", "SP": "special purpose",
}


def is_entity(name):
    """True for businesses and institutions. Portfolio lookups are limited to these because exact
    matching on a person's name would merge strangers who share it, and would build a profile of a
    private individual that a property decision doesn't need."""
    return bool(name and ENTITY_PATTERN.search(name.upper()))


def parse_date(value, today=None):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None
    # Source tables contain typo dates such as the year 9798.
    if parsed.year < 1800 or (today and parsed > today):
        return None
    return parsed


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _money(value):
    return f"${value:,.0f}"


def _years(days):
    return days / 365.25


def _tokens(name):
    words = re.findall(r"[A-Z0-9]+", (name or "").upper())
    return {w for w in words if w not in NAME_NOISE and len(w) >= 3}


def names_match(left, right):
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return False
    return len(a & b) >= min(2, len(a), len(b))


def _flag(lens, severity, title, evidence, why, ask=None, link=None):
    return {"lens": lens, "severity": severity, "title": title, "evidence": evidence,
            "why": why, "ask": ask, "link": link}


def build_chain(data, today):
    """Merge deed records with the assessor's sale field. Deed records can lag or miss the latest
    sale, and the assessor's field holds only one sale, so neither alone is the full history."""
    chain = []
    for doc in data.get("documents") or []:
        kind = (doc.get("document_type") or "").upper()
        if "DEED" not in kind:
            continue
        when = parse_date(doc.get("display_date"), today)
        if not when:
            continue
        count = doc.get("property_count")
        price = _num(doc.get("total_consideration"))
        chain.append({
            "date": when, "kind": kind, "price": price, "grantors": doc.get("grantors") or "",
            "grantees": doc.get("grantees") or "", "property_count": count, "source": "deed",
            "arms_length": kind == "DEED" and price >= 10000 and (count in (None, 1)),
        })
    opa = data.get("opa") or {}
    sale_date = parse_date(opa.get("sale_date"), today)
    sale_price = _num(opa.get("sale_price"))
    if sale_date and not any(abs((e["date"] - sale_date).days) <= 45 for e in chain):
        chain.append({
            "date": sale_date, "kind": "SALE (assessor record)", "price": sale_price, "grantors": "",
            "grantees": opa.get("owner_1") or "", "property_count": 1, "source": "opa",
            "arms_length": sale_price >= 10000,
        })
    chain.sort(key=lambda entry: entry["date"], reverse=True)
    seen, unique = set(), []
    for entry in chain:
        key = (entry["date"], entry["kind"], entry["price"])
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    return unique


def analyze_title(data, ctx, chain, today):
    flags = []
    opa = data.get("opa") or {}
    owners = [opa.get("owner_1") or "", opa.get("owner_2") or ""]
    five_years = today - timedelta(days=int(365.25 * 5))

    note = (data.get("address") or {}).get("scope_note")
    if note:
        flags.append(_flag("title", "warn" if "whole building" in note else "info", "Check what this report covers", note,
                           "Records for a unit and its building are kept separately, so a problem can sit on either one."))

    seller = ctx.get("seller")
    if seller:
        latest_grantees = next((e["grantees"] for e in chain if e["grantees"]), "")
        matched = any(names_match(seller, name) for name in owners + latest_grantees.split(";"))
        if matched:
            flags.append(_flag("title", "good", "Seller's name matches the record",
                               f"\"{seller}\" lines up with the owner or latest grantee on record.",
                               "This is a basic check, not proof of authority to sell. A title company still has to confirm it."))
        else:
            flags.append(_flag(
                "title", "critical", "Seller's name doesn't match the record",
                f"You named \"{seller}\". Records show owner: {' / '.join(o for o in owners if o) or 'unknown'}.",
                "It can be innocent: an estate, a power of attorney, a new marriage name, or a record that hasn't caught up. It is also the classic pattern in deed theft, which Philadelphia has dealt with for years.",
                "Who exactly is signing the deed, and what documents give them the right to sell? Hold any deposit until a title company answers.",
                LINKS["fraud"]))

    for entry in chain:
        if entry["date"] < five_years:
            break
        if "SHERIFF" in entry["kind"]:
            recent = (today - entry["date"]).days <= 365
            flags.append(_flag(
                "title", "critical" if recent else "warn",
                "Sold at sheriff's sale" + (" within the past year" if recent else " in the past 5 years"),
                f"Sheriff's deed recorded {entry['date']:%b %Y}.",
                "Former owners can sometimes redeem or challenge a sheriff's sale for a period afterward, and title insurers may treat these deeds differently.",
                "Will a title company insure this without exceptions? Has the redemption period passed?",
                LINKS["property"]))

    for index, entry in enumerate(chain):
        if entry["date"] < five_years:
            break
        if "DEED" not in entry["kind"] or "SHERIFF" in entry["kind"] or entry["price"] > 1000:
            continue
        if entry["property_count"] not in (None, 1):
            continue
        related = names_match(entry["grantors"], entry["grantees"])
        resold = next((later for later in reversed(chain[:index]) if later["arms_length"]
                       and (later["date"] - entry["date"]).days <= 730), None)
        if resold:
            flags.append(_flag(
                "title", "warn", "Little-or-no-money transfer, then a quick sale",
                f"{_money(entry['price'])} deed {entry['date']:%b %Y} from {entry['grantors'] or 'unknown'} to {entry['grantees'] or 'unknown'}, "
                f"then sold for {_money(resold['price'])} in {resold['date']:%b %Y}.",
                "Family and estate transfers look like this too, but so does a forged deed being turned into cash. It deserves a human look at the actual document.",
                "Ask the title company to review this deed, including the notary and whether the grantor was alive and willing.",
                LINKS["fraud"]))
        elif not related:
            flags.append(_flag(
                "title", "info", "Little-or-no-money transfer between differently named parties",
                f"{_money(entry['price'])} deed {entry['date']:%b %Y}.",
                "Often an estate, divorce, or LLC restructuring. Worth one question because nominal deeds are also how deed theft usually starts.",
                "What was the reason for this transfer?", LINKS["fraud"]))

    three_years = today - timedelta(days=int(365.25 * 3))
    recent_sales = [e for e in chain if e["arms_length"] and e["date"] >= three_years]
    if len(recent_sales) >= 3:
        flags.append(_flag(
            "title", "warn", f"Sold {len(recent_sales)} times in 3 years",
            "; ".join(f"{e['date']:%b %Y} {_money(e['price'])}" for e in recent_sales),
            "Fast turnover can mean investor churn, or that owners keep discovering the same problem.",
            "Why has this property changed hands so often? What did each owner do to it?"))

    last_deed_date = next((e["date"] for e in chain if "DEED" in e["kind"] or e["source"] == "opa"), None)
    docs = [d for d in data.get("documents") or [] if parse_date(d.get("display_date"), today)]
    if last_deed_date:
        since = [d for d in docs if parse_date(d.get("display_date"), today) >= last_deed_date]
        distress = [d for d in since if re.search(r"LIS PENDENS|JUDG|LIEN|FORECLOS", (d.get("document_type") or "").upper())]
        if distress:
            kinds = sorted({d["document_type"] for d in distress})
            flags.append(_flag(
                "title", "warn", "Lien-type documents recorded since the last deed", ", ".join(kinds),
                "These can attach to the property and may have to be cleared at closing.",
                "Have these been satisfied? Ask for payoff letters."))
        mortgages = sum((d.get("document_type") or "").upper() == "MORTGAGE" for d in since)
        releases = sum(bool(re.search(r"SATISFACTION|RELEASE", (d.get("document_type") or "").upper())) for d in since)
        if mortgages > releases:
            flags.append(_flag(
                "title", "info", f"{mortgages - releases} mortgage(s) recorded with no matching payoff yet",
                f"{mortgages} mortgage(s), {releases} satisfaction(s) or release(s) since the last deed.",
                "Normal for most homes. The title company should confirm the payoff at closing."))
    return flags


def _open_violations(rows):
    seen, out = set(), []
    for row in rows or []:
        key = row.get("violationnumber") or id(row)
        if key in seen:
            continue
        seen.add(key)
        status = (row.get("violationstatus") or "").upper()
        case = (row.get("casestatus") or "").upper()
        if status == "OPEN" or (status == "SVN ISSUED" and case != "CLOSED"):
            out.append(row)
    return out


def _unresolved(rows):
    return [r for r in rows or [] if not r.get("casecompleteddate") and not r.get("violationresolutiondate")]


def analyze_code(data, ctx, today):
    flags = []
    violations = data.get("violations") or []
    open_rows = _open_violations(violations)

    for table, label, why in (
        ("imm_dang", "Imminently dangerous designation",
         "The city's most severe structural finding. It can lead to a city demolition billed to the owner."),
        ("unsafe", "Unsafe structure designation",
         "L&I has found a structural problem that the owner must repair, usually with permits and an engineer."),
    ):
        live = _unresolved(data.get(table))
        if live:
            flags.append(_flag(
                "code", "critical", f"{label} is open",
                f"Case {live[0].get('casenumber')}, opened {str(live[0].get('violationdate'))[:10]}.",
                why, "Get a structural engineer's report before going further. Who pays for this repair?", LINKS["li"]))

    if open_rows:
        titles = sorted({" ".join((r.get("violationcodetitle") or "unspecified").split()) for r in open_rows})
        court = [r for r in open_rows if "COURT" in (r.get("casestatus") or "").upper()]
        severity = "critical" if court else "warn"
        title = f"{len(open_rows)} open code violation(s)" + (", in court" if court else "")
        flags.append(_flag(
            "code", severity, title, "; ".join(titles[:6]) + (" ..." if len(titles) > 6 else ""),
            "Open violations can carry fines, follow the property, and block rental licensing and permits.",
            "Will these be closed before settlement, with L&I confirmation in writing? Who pays any fines?",
            LINKS["li"]))
    elif data.get("violations") is not None:
        flags.append(_flag("code", "good", "No open code violations on record",
                           f"{len(violations)} past violation record(s) on file, none open.",
                           "Absence of a record only means nobody reported or cited it. It is not an inspection."))

    balance = [r for r in violations if "BALANCE DUE" in (r.get("casestatus") or "").upper()]
    if balance:
        flags.append(_flag(
            "code", "warn", f"Unpaid balance on {len({r.get('casenumber') for r in balance})} L&I case(s)",
            "Case status reads 'balance due'.",
            "Fines or city repair costs may still be owed, and unpaid city charges can become liens.",
            "What is the balance, and will it be paid at closing?", LINKS["li"]))

    cutoff = today - timedelta(days=int(365.25 * 5))
    recent = [r for r in violations if (parse_date(r.get("violationdate"), today) or date.min) >= cutoff]
    if len(recent) >= 10:
        flags.append(_flag("code", "info", f"{len(recent)} violations cited in the last 5 years",
                           "Pattern of repeat citations.",
                           "Repeat citations usually point to deferred maintenance.",
                           "What has been repeatedly cited, and was the underlying cause fixed?"))

    built = re.search(r"\d{4}", str((data.get("opa") or {}).get("year_built") or ""))
    seals = [c for c in data.get("clean_seal") or []
             if not (built and (parse_date(c.get("actdate"), today) or today).year < int(built.group()))]
    if seals:
        latest = seals[0]
        flags.append(_flag("code", "info", "City has cleaned or sealed this property",
                           f"{latest.get('acttype') or latest.get('casegroup')} on {str(latest.get('actdate'))[:10]}.",
                           "Indicates a past vacancy or blight period, and city costs may have been billed to the owner.",
                           "How long was it vacant, and was the heat kept on?"))

    if data.get("demolitions"):
        latest = data["demolitions"][0]
        flags.append(_flag("code", "info", "Demolition record on this parcel",
                           f"{latest.get('typeofwork') or 'Work'} demolition, status {latest.get('status')}, started {str(latest.get('start_date'))[:10]}.",
                           "Confirms what was removed. Check that what stands today was permitted afterward."))

    neighbors = data.get("neighbors") or {}
    if neighbors.get("open_cases"):
        cases = neighbors["open_cases"]
        flags.append(_flag(
            "code", "warn", "Unsafe building within about 80 feet",
            "; ".join(f"{c.get('address')} ({c.get('kind')})" for c in cases[:4]),
            "Philadelphia rowhouses often share party walls, so a failing neighbor can become your structural problem and your insurer's question.",
            "Does this building share a wall with the house? Ask your inspector to look at that wall from inside.",
            LINKS["atlas"]))
    if neighbors.get("demolitions"):
        demo = neighbors["demolitions"]
        flags.append(_flag(
            "code", "info", "Demolition within about 80 feet in the last 3 years",
            "; ".join(str(d.get("address")) for d in demo[:4]),
            "Demolishing a rowhouse exposes the party wall next door, which wasn't built to be an exterior wall.",
            "Has the exposed wall been sealed and is it weather-tight?"))

    condition = str((data.get("opa") or {}).get("exterior_condition") or "")
    if condition == "7":
        flags.append(_flag("code", "warn", "Assessor lists the exterior as sealed or structurally compromised",
                           "OPA exterior condition code 7. This field can be out of date.",
                           "The city's own valuation record describes serious condition problems.",
                           "Has this been repaired since, and under which permits?"))
    return flags


def _issue(permit, today):
    return parse_date(permit.get("permitissuedate"), today)


def analyze_permits(data, ctx, chain, today):
    flags = []
    permits = data.get("permits") or []
    work = [p for p in permits if p.get("permittype") in WORK_PERMIT_TYPES]

    stop = [p for p in permits if "STOP WORK" in (p.get("status") or "").upper()]
    if stop:
        flags.append(_flag("permits", "critical", "Stop-work order on a permit",
                           f"{stop[0].get('permittype')} permit {stop[0].get('permitnumber')}.",
                           "L&I halted this work. Nothing built after that point can be assumed legal.",
                           "Why was work stopped, and has it been lifted in writing?", LINKS["li"]))

    five_years = today - timedelta(days=int(365.25 * 5))
    expired = [p for p in work if (p.get("status") or "").lower() == "expired"
               and (_issue(p, today) or date.min) >= five_years]
    if expired:
        flags.append(_flag(
            "permits", "warn", f"{len(expired)} permit(s) expired without being completed",
            "; ".join(f"{p.get('permittype')} {p.get('permitnumber')} ({str(p.get('permitissuedate'))[:10]})" for p in expired[:4]),
            "The work may have been done without final inspection, and an open problem like this can surface at resale.",
            "Was this work finished? Can you show final inspection sign-off?", LINKS["li"]))

    two_years = today - timedelta(days=730)
    stale = [p for p in work if (p.get("status") or "").lower() == "issued"
             and (_issue(p, two_years) or today) <= two_years]
    if stale:
        flags.append(_flag("permits", "info", f"{len(stale)} permit(s) still open after 2+ years",
                           "; ".join(f"{p.get('permittype')} {p.get('permitnumber')}" for p in stale[:4]),
                           "An old permit that never closed may need a final inspection before a future sale.",
                           "Can the contractor close these before settlement?"))

    no_co = [p for p in permits if str(p.get("certificateofoccupancyrequired") or "").upper() in ("YES", "Y", "TRUE")
             and not p.get("certificateofoccupancydate") and (p.get("status") or "").lower() != "cancelled"]
    if no_co:
        flags.append(_flag("permits", "warn", "Certificate of occupancy required but not on record",
                           f"Permit {no_co[0].get('permitnumber')}.",
                           "Without one, the building may not be legally occupiable and a tax abatement clock or lender could be affected.",
                           "Can you provide the certificate of occupancy?", LINKS["li"]))

    # Ghost renovation: a big price jump with no permit trail in the window that would explain it.
    sales = [e for e in chain if e["arms_length"]]
    asking = ctx.get("price")
    pair = None
    if asking and sales:
        pair = (sales[0], {"date": today, "price": float(asking), "label": "asking price"})
    elif len(sales) >= 2:
        pair = (sales[1], dict(sales[0], label="resale"))
    if pair:
        bought, after = pair
        held = (after["date"] - bought["date"]).days
        if bought["price"] > 0 and 0 <= held <= 365 * 3 and after["price"] / bought["price"] >= 1.4:
            start = bought["date"] - timedelta(days=90)
            trail = [p for p in work if start <= (_issue(p, today) or date.min) <= after["date"]]
            gain = after["price"] / bought["price"] - 1
            evidence = (f"Bought for {_money(bought['price'])} in {bought['date']:%b %Y}; "
                        f"{after['label']} {_money(after['price'])} ({gain:.0%} up in {held / 30.4:.0f} months).")
            if not trail:
                flags.append(_flag(
                    "permits", "warn", "Ghost renovation: big price jump, no permit trail",
                    evidence + " No building or trade permits on record for that window.",
                    "A jump this size normally means major work. With no permits, nobody independent checked the wiring, plumbing, or structure behind the new finishes.",
                    "What work was done and who did it? Bring an inspector who opens panels and looks at the basement and the rear wall.",
                    LINKS["li"]))
            else:
                kinds = sorted({p.get("permittype") for p in trail})
                flags.append(_flag("permits", "good", "Price jump is backed by permits",
                                   evidence + f" Permits in that window: {', '.join(kinds)}.",
                                   "A permit trail shows the work was at least filed. Check that the permits were completed."))

    ten_years = today - timedelta(days=int(365.25 * 10))
    recent_types = {p.get("permittype") for p in work if (_issue(p, today) or date.min) >= ten_years}
    for claim in ctx.get("claims") or []:
        if claim not in CLAIM_PERMITS:
            continue
        label, needed = CLAIM_PERMITS[claim]
        if recent_types & needed:
            flags.append(_flag("permits", "good", f"Listing claim has a permit: {label}",
                               f"Found {', '.join(sorted(recent_types & needed))} permit in the last 10 years.",
                               "Check the date and scope match what the listing describes."))
        else:
            flags.append(_flag(
                "permits", "warn", f"Listing claim with no permit: {label}",
                f"Expected a {' or '.join(sorted(needed))} permit in the last 10 years and found none.",
                "Some minor work doesn't need a permit and old records can be incomplete, but this is exactly the work inspectors want to see signed off.",
                f"Who did the {label}, when, and can you share the permit or invoices?", LINKS["li"]))
    return flags


def compute_tax(data, today):
    opa = data.get("opa") or {}
    history = data.get("assessments") or []
    latest = history[-1] if history else None
    source = latest or opa
    market = _num(source.get("market_value"))
    taxable = _num(source.get("taxable_land")) + _num(source.get("taxable_building"))
    exempt_building = _num(source.get("exempt_building"))
    exempt_land = _num(source.get("exempt_land"))
    homestead = _num(opa.get("homestead_exemption"))

    result = {
        "year": int(latest["year"]) if latest and str(latest.get("year")).isdigit() else None,
        "market_value": market,
        "taxable": taxable,
        "current_bill": round(taxable * TAX_RATE),
        "full_bill": round(market * TAX_RATE),
        "with_homestead_bill": round(max(market - HOMESTEAD_EXCLUSION, 0) * TAX_RATE),
        "homestead_on_record": homestead > 0,
        "abated": False,
        "fully_exempt": market > 0 and taxable == 0,
        "rate": TAX_RATE,
        "rates_checked": RATES_CHECKED,
        "history": [{"year": h.get("year"), "market_value": _num(h.get("market_value"))} for h in history],
    }
    other_exemption = exempt_building - homestead
    if other_exemption > 0 and not result["fully_exempt"] and exempt_building not in PAST_HOMESTEAD_AMOUNTS:
        result["abated"] = True
        result["exempt_amount"] = exempt_building
        start = None
        for row in reversed(history):
            value = _num(row.get("exempt_building"))
            if value <= 0 or value in PAST_HOMESTEAD_AMOUNTS:
                break
            start = row.get("year")
        if start and str(start).isdigit():
            result["abatement_first_year"] = int(start)
            result["abatement_estimated_end"] = int(start) + 10
    return result


def analyze_tax(data, ctx, tax, today):
    flags = [_flag(
        "tax", "info", "Unpaid tax balance not checked: look it up",
        "The city's public delinquency table refuses automated access, and the balance dataset ends at tax year 2016.",
        "Unpaid real estate tax becomes a lien on the property. Don't read silence here as a clean record.",
        "What does the city show as owed today? Check before making an offer.", LINKS["tax"])]
    for_whom = ctx.get("audience") or "buyer"
    year_label = f"tax year {tax['year']}" if tax.get("year") else "the latest year"

    if tax["fully_exempt"]:
        flags.append(_flag(
            "tax", "warn", "Currently pays no real estate tax",
            f"Assessed at {_money(tax['market_value'])} with $0 taxable in {year_label}.",
            f"A tax exemption usually belongs to the owner, not the house. A new private owner could face about {_money(tax['full_bill'])} a year.",
            "Why is this exempt, and what happens to the exemption at sale?", LINKS["property"]))
    if tax["abated"]:
        jump = tax["with_homestead_bill"] if for_whom in ("buyer", "owner") else tax["full_bill"]
        extra = jump - tax["current_bill"]
        owner = (data.get("opa") or {}).get("owner_1") or ""
        if PUBLIC_OWNER.search(owner.upper()):
            flags.append(_flag(
                "tax", "warn", "Partial tax exemption may not survive a sale",
                f"Now about {_money(tax['current_bill'])} a year; without the exemption about {_money(tax['full_bill'])}. Owner on record: {owner}.",
                "This exemption looks tied to a public or institutional owner, so a private buyer shouldn't count on it.",
                "What is this exemption based on, and does it end at sale?", LINKS["property"]))
            return flags
        end = tax.get("abatement_estimated_end")
        # An estimated end already in the past means the estimate is wrong, not that the abatement ended.
        if end and end <= today.year:
            end = None
        left = (end - today.year) if end else None
        severity = "critical" if left is not None and left <= 2 and extra >= 3000 else "warn"
        when = f"around {end} (estimate based on when the exemption first appears)" if end else "on a date to confirm with OPA"
        flags.append(_flag(
            "tax", severity, "Abatement cliff: the tax bill is due to jump",
            f"Now about {_money(tax['current_bill'])} a year on {_money(tax['taxable'])} taxable. "
            f"Without the abatement about {_money(jump)} a year, or {_money(extra)} more. It ends {when}.",
            "Philadelphia abatements exempt new construction or improvements for a fixed term. Mortgage quotes based on today's bill can understate what you'll pay later. Newer abatements also phase down year by year, so the increase may arrive early.",
            "What year does the abatement end, and is it the phased version? Run your budget on the full bill. Note Homestead can't be used while a 10-year abatement is active.",
            LINKS["abatement"]))

    if tax["homestead_on_record"] and for_whom == "investor":
        flags.append(_flag(
            "tax", "warn", "Homestead exclusion won't carry to a non-occupant",
            f"The seller's bill is about {_money(tax['current_bill'])}. A non-occupant owner would pay about {_money(tax['full_bill'])}.",
            "Homestead requires the owner to live there, so the seller's tax figure understates an investor's cost.",
            "Use the full bill in your numbers, not the seller's."))
    elif for_whom in ("buyer", "owner") and not tax["homestead_on_record"] and not tax["abated"] and not tax["fully_exempt"]:
        saving = tax["full_bill"] - tax["with_homestead_bill"]
        if saving > 0:
            flags.append(_flag(
                "tax", "info", f"Homestead could cut about {_money(saving)} a year if the owner lives here",
                "No Homestead exclusion on record for this parcel.",
                "It takes up to $100,000 off the taxable value for owner-occupants, with no age or income test. The final application date each year is December 1.",
                None, LINKS["homestead"]))

    history = tax["history"]
    if len(history) >= 2 and history[-2]["market_value"] > 0:
        change = history[-1]["market_value"] / history[-2]["market_value"] - 1
        if abs(change) >= 0.20:
            flags.append(_flag(
                "tax", "info", f"Assessment moved {change:+.0%} in {history[-1]['year']}",
                f"{_money(history[-2]['market_value'])} to {_money(history[-1]['market_value'])}.",
                "A large swing changes the bill and can reflect a change in the property record, such as completed work."))
    return flags


def summarize_comps(data, area):
    comps = data.get("comps") or {}
    usable = []
    for row in comps.get("rows") or []:
        price = _num(row.get("total_consideration"))
        living = _num(row.get("total_livable_area"))
        if names_match(row.get("grantors"), row.get("grantees")):
            continue
        ppsf = price / living if living >= 300 else None
        if ppsf is not None and not 15 <= ppsf <= 2000:
            continue
        usable.append({"date": str(row.get("display_date"))[:10], "address": row.get("street_address"),
                       "price": price, "area": living, "ppsf": ppsf,
                       "beds": row.get("number_of_bedrooms"), "condition": row.get("exterior_condition")})
    if area and area >= 300:
        similar = [c for c in usable if c["ppsf"] and 0.65 * area <= c["area"] <= 1.35 * area]
        if len(similar) >= 5:
            usable = similar
    summary = {"count": len(usable), "radius_m": comps.get("radius_m"), "rows": usable[:12],
               "confidence": "low" if len(usable) < 5 else ("medium" if len(usable) < 12 else "higher")}
    if len(usable) < 3:
        return summary
    ppsfs = sorted(c["ppsf"] for c in usable if c["ppsf"])
    prices = sorted(c["price"] for c in usable)
    use_ppsf = bool(area and area >= 300 and len(ppsfs) >= 3)
    series = ppsfs if use_ppsf else prices
    mid = statistics.median(series)
    quart = statistics.quantiles(series, n=4) if len(series) >= 4 else [series[0], mid, series[-1]]
    factor = area if use_ppsf else 1
    summary.update({"method": "price per sq ft x this home's size" if use_ppsf else "median sale price",
                    "low": round(quart[0] * factor, -3), "mid": round(mid * factor, -3), "high": round(quart[2] * factor, -3)})
    if use_ppsf:
        summary["median_ppsf"] = round(mid)
    return summary


def analyze_price(data, ctx, comps, tax):
    flags = []
    if "mid" not in comps:
        if data.get("comps") is not None:
            flags.append(_flag("price", "info", "Too few nearby sales to compare",
                               f"{comps['count']} usable sale(s) nearby in the last 2 years.",
                               "Get a local agent's comparable sales before relying on any price."))
        return flags

    span = f"{_money(comps['low'])} to {_money(comps['high'])}"
    note = f"{comps['count']} nearby sales, {comps['method']}. Records can't see condition, so a shell and a new rehab count alike."
    asking = ctx.get("price")
    if asking:
        asking = float(asking)
        if asking > comps["high"] * 1.1:
            flags.append(_flag("price", "warn", f"Asking price is above nearby sales: {asking / comps['mid'] - 1:+.0%} from the middle",
                               f"Asking {_money(asking)}; nearby range {span}. {note}",
                               "A premium can be justified by condition or finishes, but an appraisal may not agree, and you may have to cover the gap in cash.",
                               "Which specific sales support this price?"))
        elif asking < comps["low"] * 0.8:
            flags.append(_flag("price", "warn", f"Asking price is well below nearby sales: {asking / comps['mid'] - 1:+.0%} from the middle",
                               f"Asking {_money(asking)}; nearby range {span}. {note}",
                               "Cheap for the block usually has a reason: condition, title, or a tax or code problem.",
                               "Why is this priced under its neighbors?"))
        else:
            flags.append(_flag("price", "good", "Asking price sits within range of nearby sales",
                               f"Asking {_money(asking)}; nearby range {span}. {note}",
                               "This is a rough screen, not an appraisal."))
    else:
        flags.append(_flag("price", "info", f"Nearby sales suggest about {span}", note, "This is a rough screen, not an appraisal."))

    market = tax.get("market_value") or 0
    if market:
        if market > comps["mid"] * 1.15:
            flags.append(_flag("price", "info", f"City's value looks high against sales: {market / comps['mid'] - 1:+.0%}",
                               f"Assessed at {_money(market)}; middle of nearby sales about {_money(comps['mid'])}.",
                               "Owners can appeal an assessment. The formal deadline is usually early October, and new owners may have a special 30-day window.",
                               None, LINKS["appeal"]))
        elif market < comps["mid"] * 0.75:
            flags.append(_flag("price", "info", f"City's value looks low against sales: {market / comps['mid'] - 1:+.0%}",
                               f"Assessed at {_money(market)}; middle of nearby sales about {_money(comps['mid'])}.",
                               "A future reassessment could raise the tax bill. Budget using a value closer to your purchase price."))
    return flags


def owner_absent(opa):
    """Mailing address differs from the property and no Homestead claim."""
    location = re.sub(r"\W+", "", (opa.get("location") or "").upper())
    mailing = re.sub(r"\W+", "", (opa.get("mailing_street") or opa.get("mailing_address_1") or "").upper())
    if _num(opa.get("homestead_exemption")) > 0:
        return False
    if not mailing:
        return False
    return not (mailing.startswith(location) or location.startswith(mailing))


def analyze_rental(data, ctx, today):
    flags = []
    opa = data.get("opa") or {}
    audience = ctx.get("audience") or "buyer"
    licenses = data.get("licenses") or []
    rentals = [l for l in licenses if l.get("licensetype") == "Rental"]
    active = [l for l in rentals if (l.get("licensestatus") or "").lower() == "active"]
    absent = owner_absent(opa)
    is_residential = str(opa.get("category_code")) in ("1", "2", "3")

    if active:
        units = sum(int(_num(l.get("numberofunits"))) for l in active)
        flags.append(_flag("rental", "good", "Active rental license on record",
                           f"{len(active)} active license(s) covering {units} unit(s).",
                           "A license is the baseline, not a quality guarantee."))
    elif data.get("licenses") is not None and is_residential and (absent or audience == "renter"):
        # A missing record isn't a confirmed problem: licenses can be linked to another address record.
        severity = "warn"
        lapsed = sorted({l.get("licensestatus") for l in rentals if l.get("licensestatus")})
        extra = f" Past license status: {', '.join(lapsed)}." if lapsed else ""
        flags.append(_flag(
            "rental", severity, "No active rental license found",
            f"Owner mailing address differs from the property: {'yes' if absent else 'no'}.{extra}",
            "City rules bar collecting rent on a property that needs a license but doesn't have one. It may also be owner-occupied or not rented at all, and a unit may be licensed under an address the record doesn't link.",
            "Can you show the current rental license, Certificate of Rental Suitability, and lead certificate?",
            LINKS["suitability"]))

    bad = [l for l in rentals if (l.get("licensestatus") or "").lower() in ("revoked", "suspended")]
    if bad:
        flags.append(_flag("rental", "warn", "Rental license was revoked or suspended",
                           f"License {bad[0].get('licensenum')}: {bad[0].get('licensestatus')}.",
                           "Revocation usually follows unresolved violations.",
                           "Why, and has it been resolved?", LINKS["li"]))

    built = re.search(r"\d{4}", str(opa.get("year_built") or ""))
    if built and int(built.group()) < 1978 and is_residential and (active or audience in ("renter", "investor")):
        flags.append(_flag(
            "rental", "info", "Built before 1978: lead certificate rules apply to rentals",
            f"Year built on record: {built.group()}.",
            "Philadelphia landlords need a lead-safe or lead-free certificate to sign a lease or hold a rental license. A lead-safe certificate expires after 4 years.",
            "Can you share the current lead certificate?", LINKS["suitability"]))

    portfolio = data.get("portfolio")
    if portfolio and portfolio.get("parcels") and (active or portfolio.get("active_rental_licenses")):
        count = portfolio["open_violations"]
        text = "open violations at 10+ addresses" if portfolio.get("open_violations_capped") else f"{count} open violation(s)"
        severity = "warn" if count >= 10 else "info"
        flags.append(_flag(
            "rental", severity, f"Owner company holds {portfolio['parcels']} parcel(s), with {text}",
            f"{portfolio['owner']}: {portfolio['active_rental_licenses']} active rental license(s) under this exact name. Name matching misses related companies and can undercount.",
            "How an owner treats other buildings is a useful signal about how they'll treat this one.",
            "Who responds to repairs, and what's the typical turnaround?"))
    return flags


def analyze_site(data, ctx):
    flags = []
    address = data.get("address") or {}
    opa = data.get("opa") or {}
    flood = data.get("flood") or {}

    if flood.get("SFHA_TF") == "T":
        flags.append(_flag("site", "warn", f"In a FEMA high-risk flood area (zone {flood.get('FLD_ZONE')})",
                           str(flood.get("ZONE_SUBTY") or "Special Flood Hazard Area"),
                           "Lenders generally require flood insurance here, and it can change the monthly cost a lot.",
                           "Get a flood insurance quote and ask for any elevation certificate or claims history."))
    elif flood.get("ZONE_SUBTY") and "0.2" in str(flood.get("ZONE_SUBTY")):
        flags.append(_flag("site", "info", "In FEMA's moderate flood-risk area",
                           str(flood["ZONE_SUBTY"]),
                           "Insurance usually isn't required, but basements in older rowhouses still flood. Ask about water history."))

    if str(address.get("historic_site") or "").strip().upper() not in ("", "NO") or (address.get("historic_district") or "").strip():
        flags.append(_flag("site", "info", "Historic designation",
                           f"Site: {address.get('historic_site') or 'n/a'}. District: {address.get('historic_district') or 'none'}.",
                           "Exterior changes generally need Historical Commission review, which adds time and cost to window, facade, and roof work.",
                           "What exterior work are you planning? Check it with the Commission first."))

    zoning = (address.get("zoning") or opa.get("zoning") or "").upper()
    base = re.match(r"[A-Z]+", zoning)
    if zoning:
        plain = ZONING_PLAIN.get(base.group() if base else "", "see city zoning code")
        flags.append(_flag("site", "info", f"Zoned {zoning}: {plain}",
                           "From the city's address record.",
                           "Zoning decides what you can legally build or how many units you can have."))
        units = max([int(_num(l.get("numberofunits"))) for l in (data.get("licenses") or [])
                     if (l.get("licensestatus") or "").lower() == "active" and l.get("licensetype") == "Rental"] or [0])
        multi_record = str(opa.get("category_code")) == "2"
        family = base.group() if base else ""
        too_many = (family in ("RSD", "RSA") and (units >= 2 or multi_record)) or (family == "RTA" and units >= 3)
        if too_many:
            flags.append(_flag(
                "site", "warn", "Unit count may exceed what the zoning allows",
                f"Zoned {zoning} ({plain}); records show {units or 'multiple'} unit(s).",
                "It might be legally grandfathered, or it might be an illegal conversion. An illegal unit can mean lost rent, fines, and financing or insurance trouble.",
                "Can you show the zoning permit or certificate of occupancy for this many units?",
                LINKS["li"]))
    return flags


def investor_math(tax, ctx):
    """Plain arithmetic on the user's own assumptions. Never a buy or sell recommendation."""
    price, rent = ctx.get("price"), ctx.get("rent")
    if not price or not rent:
        return None
    price, rent = float(price), float(rent)
    vacancy = ctx.get("vacancy", 0.05)
    maintenance = ctx.get("maintenance", 0.08)
    management = ctx.get("management", 0.0)
    insurance = ctx.get("insurance", 1500.0)
    gross = rent * 12

    def scenario(annual_tax):
        operating = gross * (vacancy + maintenance + management) + insurance + annual_tax
        return {"annual_tax": annual_tax, "noi": round(gross - operating), "cap_rate": round((gross - operating) / price, 4)}

    today_case = scenario(tax["full_bill"] if tax["homestead_on_record"] else tax["current_bill"])
    result = {
        "assumptions": {"price": price, "monthly_rent": rent, "vacancy": vacancy, "maintenance": maintenance,
                        "management": management, "insurance": insurance},
        "today": today_case,
        "full_tax": scenario(tax["full_bill"]),
        "transfer_tax_total": round(price * TRANSFER_TAX_RATE),
        "transfer_tax_half": round(price * TRANSFER_TAX_RATE / 2),
    }
    rate, down = ctx.get("rate"), ctx.get("down")
    if rate and down is not None:
        monthly_rate = float(rate) / 12
        months = int(ctx.get("term", 30)) * 12
        loan = price * (1 - float(down))
        payment = loan / months if monthly_rate == 0 else loan * monthly_rate / (1 - (1 + monthly_rate) ** -months)
        debt = payment * 12
        cash_in = price * float(down) + result["transfer_tax_half"]
        for case in (result["today"], result["full_tax"]):
            case["annual_cash_flow"] = round(case["noi"] - debt)
            case["cash_on_cash"] = round((case["noi"] - debt) / cash_in, 4) if cash_in else None
            case["dscr"] = round(case["noi"] / debt, 2) if debt else None
        result["loan"] = {"amount": round(loan), "monthly_payment": round(payment), "cash_in_estimate": round(cash_in)}
    return result


def analyze(data, ctx=None, today=None):
    ctx = ctx or {}
    today = today or date.today()
    chain = build_chain(data, today)
    tax = compute_tax(data, today)
    area = _num((data.get("opa") or {}).get("total_livable_area"))
    comps = summarize_comps(data, area)

    flags = (analyze_title(data, ctx, chain, today) + analyze_code(data, ctx, today)
             + analyze_permits(data, ctx, chain, today) + analyze_tax(data, ctx, tax, today)
             + analyze_price(data, ctx, comps, tax) + analyze_rental(data, ctx, today) + analyze_site(data, ctx))
    flags.sort(key=lambda f: SEVERITY_ORDER[f["severity"]])

    gaps = data.get("gaps") or {}
    lenses = []
    for key, title in LENSES:
        mine = [f for f in flags if f["lens"] == key]
        worst = min((SEVERITY_ORDER[f["severity"]] for f in mine), default=None)
        missing = [s for s in LENS_SOURCES[key] if s in gaps]
        if worst == 0:
            status = "stop"
        elif worst == 1:
            status = "look"
        elif missing:
            status = "unknown"
        elif worst == 2:
            status = "note"
        else:
            status = "clear"
        lenses.append({"key": key, "title": title, "status": status, "missing_sources": missing,
                       "counts": {s: sum(f["severity"] == s for f in mine) for s in SEVERITY_ORDER}})

    critical = sum(f["severity"] == "critical" for f in flags)
    warn = sum(f["severity"] == "warn" for f in flags)
    if critical:
        headline = f"{critical} serious record finding{'s' if critical != 1 else ''} to resolve before going further"
    elif warn:
        headline = f"{warn} item{'s' if warn != 1 else ''} to look into before you sign"
    else:
        headline = "No major red flags in the public record"

    return {
        "address": (data.get("address") or {}).get("address"),
        "as_of": today.isoformat(),
        "audience": ctx.get("audience") or "buyer",
        "headline": headline,
        "counts": {"critical": critical, "warn": warn},
        "lenses": lenses,
        "flags": flags,
        "questions": [f["ask"] for f in flags if f.get("ask") and f["severity"] in ("critical", "warn")]
        + [f["ask"] for f in flags if f.get("ask") and f["severity"] == "info"],
        "tax": tax,
        "comps": comps,
        "sales": [dict(e, date=e["date"].isoformat()) for e in chain[:12]],
        "open_violations": _open_violations(data.get("violations"))[:30],
        "investor": investor_math(tax, ctx),
        "gaps": gaps,
        "context": {
            "crime_last_12_months_quarter_mile": data.get("crime"),
            "building_permits_nearby": data.get("momentum"),
        },
    }
