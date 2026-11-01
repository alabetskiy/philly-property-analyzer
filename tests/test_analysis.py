import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import analysis  # noqa: E402
import report  # noqa: E402
import sources  # noqa: E402

TODAY = date(2026, 11, 1)


def base_data(**overrides):
    data = {
        "address": {"address": "100 TEST ST", "zoning": "RSA-5", "historic_site": "No", "historic_district": ""},
        "opa": {"location": "100 TEST ST", "owner_1": "DOE JANE", "mailing_street": "100 TEST ST",
                "category_code": "1", "market_value": 300000, "taxable_land": 60000, "taxable_building": 240000,
                "exempt_land": 0, "exempt_building": 0, "homestead_exemption": 0, "total_livable_area": 1200,
                "year_built": "1925", "exterior_condition": "4"},
        "assessments": [{"year": "2027", "market_value": 300000, "taxable_land": 60000, "taxable_building": 240000,
                         "exempt_land": 0, "exempt_building": 0}],
        "documents": [], "violations": [], "permits": [], "licenses": [], "unsafe": [], "imm_dang": [],
        "clean_seal": [], "demolitions": [], "neighbors": {"open_cases": [], "demolitions": []},
        "comps": {"radius_m": 300, "rows": []}, "flood": {"SFHA_TF": "F", "FLD_ZONE": "X"}, "gaps": {},
    }
    data.update(overrides)
    return data


def deed(day, price, grantors="A SELLER", grantees="B BUYER", kind="DEED", count=1):
    return {"document_type": kind, "display_date": day, "total_consideration": price,
            "grantors": grantors, "grantees": grantees, "property_count": count}


def titles(result, severity=None):
    return [f["title"] for f in result["flags"] if severity in (None, f["severity"])]


class TaxTests(unittest.TestCase):
    def test_bill_uses_current_rate(self):
        result = analysis.analyze(base_data(), today=TODAY)
        self.assertEqual(result["tax"]["current_bill"], round(300000 * 0.013998))
        self.assertEqual(result["tax"]["with_homestead_bill"], round(200000 * 0.013998))

    def test_abatement_cliff_detected_with_estimated_end(self):
        history = [
            {"year": "2020", "market_value": 78300, "taxable_land": 78300, "taxable_building": 0, "exempt_land": 0, "exempt_building": 0},
            {"year": "2021", "market_value": 579000, "taxable_land": 110000, "taxable_building": 0, "exempt_land": 0, "exempt_building": 469000},
            {"year": "2027", "market_value": 667100, "taxable_land": 133420, "taxable_building": 0, "exempt_land": 0, "exempt_building": 533680},
        ]
        data = base_data(assessments=history)
        result = analysis.analyze(data, today=TODAY)
        self.assertTrue(result["tax"]["abated"])
        self.assertEqual(result["tax"]["abatement_estimated_end"], 2031)
        self.assertIn("Abatement cliff: the tax bill is due to jump", titles(result))

    def test_homestead_alone_is_not_an_abatement(self):
        opa = dict(base_data()["opa"], homestead_exemption=100000, exempt_building=100000)
        history = [{"year": "2027", "market_value": 300000, "taxable_land": 60000, "taxable_building": 140000,
                    "exempt_land": 0, "exempt_building": 100000}]
        result = analysis.analyze(base_data(opa=opa, assessments=history), today=TODAY)
        self.assertFalse(result["tax"]["abated"])

    def test_tax_debt_is_never_reported_as_clean(self):
        result = analysis.analyze(base_data(), today=TODAY)
        self.assertTrue(any("Unpaid tax balance not checked" in t for t in titles(result)))

    def test_investor_loses_homestead(self):
        opa = dict(base_data()["opa"], homestead_exemption=100000, exempt_building=100000)
        history = [{"year": "2027", "market_value": 300000, "taxable_land": 60000, "taxable_building": 140000,
                    "exempt_land": 0, "exempt_building": 100000}]
        result = analysis.analyze(base_data(opa=opa, assessments=history), {"audience": "investor"}, TODAY)
        self.assertIn("Homestead exclusion won't carry to a non-occupant", titles(result))


class TitleTests(unittest.TestCase):
    def test_seller_mismatch_is_critical(self):
        result = analysis.analyze(base_data(), {"seller": "Robert Stranger"}, TODAY)
        self.assertIn("Seller's name doesn't match the record", titles(result, "critical"))

    def test_seller_match_in_any_name_order(self):
        result = analysis.analyze(base_data(), {"seller": "Jane Doe"}, TODAY)
        self.assertIn("Seller's name matches the record", titles(result, "good"))

    def test_nominal_deed_then_sale(self):
        docs = [deed("2026-05-01", 250000, "NEW OWNER LLC", "C BUYER"),
                deed("2025-11-01", 1, "OLD HOLDER", "NEW OWNER LLC", "MISCELLANEOUS DEED")]
        result = analysis.analyze(base_data(documents=docs), today=TODAY)
        self.assertIn("Little-or-no-money transfer, then a quick sale", titles(result, "warn"))

    def test_recent_sheriff_sale_is_critical(self):
        docs = [deed("2026-06-01", 40000, "SHERIFF", "BIDDER LLC", "SHERIFF'S DEED")]
        result = analysis.analyze(base_data(documents=docs), today=TODAY)
        self.assertIn("Sold at sheriff's sale within the past year", titles(result, "critical"))

    def test_bad_future_dates_are_ignored(self):
        docs = [deed("9798-06-12", 500000)]
        self.assertEqual(analysis.build_chain(base_data(documents=docs), TODAY), [])

    def test_assessor_sale_fills_in_lagging_deeds(self):
        opa = dict(base_data()["opa"], sale_date="2026-09-02", sale_price=705000)
        docs = [deed("2021-03-18", 640000)]
        chain = analysis.build_chain(base_data(opa=opa, documents=docs), TODAY)
        self.assertEqual(chain[0]["price"], 705000)
        self.assertEqual(len(chain), 2)


class PermitTests(unittest.TestCase):
    def flip(self, permits):
        docs = [deed("2026-06-01", 400000), deed("2025-06-01", 150000)]
        return analysis.analyze(base_data(documents=docs, permits=permits), today=TODAY)

    def test_ghost_renovation_without_permits(self):
        self.assertIn("Ghost renovation: big price jump, no permit trail", titles(self.flip([]), "warn"))

    def test_flip_with_permits_is_not_ghost(self):
        permits = [{"permittype": "Residential Building", "permitissuedate": "2025-08-01", "status": "Completed"}]
        result = self.flip(permits)
        self.assertNotIn("Ghost renovation: big price jump, no permit trail", titles(result))
        self.assertIn("Price jump is backed by permits", titles(result, "good"))

    def test_listing_claim_without_permit(self):
        result = analysis.analyze(base_data(), {"claims": ["electrical"]}, TODAY)
        self.assertIn("Listing claim with no permit: new electric / panel", titles(result, "warn"))

    def test_stop_work_is_critical(self):
        permits = [{"permittype": "Building", "permitnumber": "P1", "status": "Stop Work"}]
        result = analysis.analyze(base_data(permits=permits), today=TODAY)
        self.assertIn("Stop-work order on a permit", titles(result, "critical"))


class CodeTests(unittest.TestCase):
    def test_open_unsafe_is_critical(self):
        unsafe = [{"casenumber": "CF-1", "violationdate": "2024-01-01", "casecompleteddate": None, "violationresolutiondate": None}]
        result = analysis.analyze(base_data(unsafe=unsafe), today=TODAY)
        self.assertIn("Unsafe structure designation is open", titles(result, "critical"))

    def test_complied_violation_is_not_open(self):
        rows = [{"violationnumber": "V1", "violationstatus": "COMPLIED", "casestatus": "CLOSED"}]
        result = analysis.analyze(base_data(violations=rows), today=TODAY)
        self.assertEqual(result["open_violations"], [])

    def test_court_violation_is_critical(self):
        rows = [{"violationnumber": "V1", "violationstatus": "OPEN", "casestatus": "IN VIOLATION - COURT",
                 "violationcodetitle": "ROOF"}]
        result = analysis.analyze(base_data(violations=rows), today=TODAY)
        self.assertIn("1 open code violation(s), in court", titles(result, "critical"))

    def test_party_wall_neighbor(self):
        neighbors = {"open_cases": [{"address": "102 TEST ST", "kind": "Unsafe"}], "demolitions": []}
        result = analysis.analyze(base_data(neighbors=neighbors), today=TODAY)
        self.assertIn("Unsafe building within about 80 feet", titles(result, "warn"))


class GapTests(unittest.TestCase):
    def test_failed_source_reads_unknown_not_clear(self):
        data = base_data(violations=None, gaps={"violations": "timeout"})
        result = analysis.analyze(data, today=TODAY)
        code = next(l for l in result["lenses"] if l["key"] == "code")
        self.assertEqual(code["status"], "unknown")
        self.assertNotIn("No open code violations on record", titles(result))


class RentalTests(unittest.TestCase):
    def test_renter_without_license_is_flagged_but_not_confirmed(self):
        result = analysis.analyze(base_data(), {"audience": "renter"}, TODAY)
        self.assertIn("No active rental license found", titles(result, "warn"))

    def test_owner_occupant_buyer_is_not_flagged(self):
        result = analysis.analyze(base_data(), {"audience": "buyer"}, TODAY)
        self.assertNotIn("No active rental license found", titles(result))

    def test_illegal_unit_check(self):
        licenses = [{"licensetype": "Rental", "licensestatus": "Active", "numberofunits": "3"}]
        result = analysis.analyze(base_data(licenses=licenses), today=TODAY)
        self.assertIn("Unit count may exceed what the zoning allows", titles(result, "warn"))


class PriceTests(unittest.TestCase):
    def comps(self, n=8):
        return {"radius_m": 300, "rows": [
            {"display_date": "2026-01-01", "street_address": f"{i} X ST", "total_consideration": 300000 + i * 1000,
             "total_livable_area": 1200, "grantors": "A", "grantees": "B"} for i in range(n)]}

    def test_high_asking_warns(self):
        result = analysis.analyze(base_data(comps=self.comps()), {"price": 500000}, TODAY)
        self.assertTrue(any("above nearby sales" in t for t in titles(result, "warn")))

    def test_too_few_comps_gives_no_range(self):
        result = analysis.analyze(base_data(comps=self.comps(2)), {"price": 500000}, TODAY)
        self.assertNotIn("mid", result["comps"])


class AddressTests(unittest.TestCase):
    def test_split_unit_forms(self):
        self.assertEqual(sources.split_address("100 Test St, Unit 2R, Philadelphia, PA 19103"), ("100 Test St", "2R"))
        self.assertEqual(sources.split_address("100 Test St #2R"), ("100 Test St", "2R"))
        self.assertEqual(sources.split_address("100 Test St Apt 2r"), ("100 Test St", "2R"))
        self.assertEqual(sources.split_address("100 Test St"), ("100 Test St", None))

    def test_zip_and_state_are_stripped(self):
        self.assertEqual(sources.split_address("100 Test St, Philadelphia, PA 19147"), ("100 Test St", None))
        self.assertEqual(sources.split_address("100 Test St, PA 19147"), ("100 Test St", None))
        self.assertEqual(sources.split_address("100 Test St 19147"), ("100 Test St", None))

    def test_addresses_outside_philadelphia_are_refused(self):
        for address in ("123 Main St, Cherry Hill, NJ 08002", "100 Bala Ave, Bala Cynwyd, PA 19004",
                        "1 Market St, Upper Darby, PA", "50 Main St, Wilmington, DE"):
            self.assertIsNotNone(sources.outside_philadelphia(address), address)

    def test_philadelphia_addresses_are_allowed(self):
        for address in ("100 Test St", "100 Test St, Philadelphia, PA 19147", "100 Test St, Philly, PA",
                        "100 Test St 19147", "100 Test St Unit 2R"):
            self.assertIsNone(sources.outside_philadelphia(address), address)

    def test_street_names_are_not_mistaken_for_units(self):
        self.assertEqual(sources.split_address("100 Apartment Rd"), ("100 Apartment Rd", None))

    def test_whole_building_scope_is_a_warning(self):
        data = base_data()
        data["address"]["scope_note"] = "Unit 3 has no separate property record, so this report covers the whole building, not that unit alone."
        self.assertIn("Check what this report covers", titles(analysis.analyze(data, today=TODAY), "warn"))


class AbatementEdgeTests(unittest.TestCase):
    def history(self):
        return [{"year": "2015", "market_value": 500000, "taxable_land": 100000, "taxable_building": 0, "exempt_land": 0, "exempt_building": 400000},
                {"year": "2027", "market_value": 500000, "taxable_land": 100000, "taxable_building": 0, "exempt_land": 0, "exempt_building": 400000}]

    def test_public_owner_exemption_is_not_called_an_abatement(self):
        opa = dict(base_data()["opa"], owner_1="SEPTA")
        result = analysis.analyze(base_data(opa=opa, assessments=self.history()), today=TODAY)
        self.assertIn("Partial tax exemption may not survive a sale", titles(result))
        self.assertNotIn("Abatement cliff: the tax bill is due to jump", titles(result))

    def test_elapsed_estimate_is_not_printed_as_a_date(self):
        result = analysis.analyze(base_data(assessments=self.history()), today=TODAY)
        cliff = next(f for f in result["flags"] if f["title"].startswith("Abatement cliff"))
        self.assertEqual(cliff["severity"], "warn")
        self.assertIn("confirm with OPA", cliff["evidence"])

    def cliff(self, audience):
        history = [{"year": "2018", "market_value": 500000, "taxable_land": 100000, "taxable_building": 150000, "exempt_land": 0, "exempt_building": 250000},
                   {"year": "2027", "market_value": 500000, "taxable_land": 100000, "taxable_building": 150000, "exempt_land": 0, "exempt_building": 250000}]
        result = analysis.analyze(base_data(assessments=history), {"audience": audience}, TODAY)
        return next(f for f in result["flags"] if f["title"].startswith("Abatement cliff"))

    def test_cliff_quotes_full_bill_for_every_audience(self):
        for audience in ("buyer", "owner", "investor", "renter"):
            self.assertIn("Without the abatement about $6,999 a year, or $3,499 more", self.cliff(audience)["evidence"])

    def test_homestead_bill_is_separate_and_only_for_possible_occupants(self):
        for audience in ("buyer", "owner"):
            self.assertIn("With Homestead, if the owner lives here, about $5,599", self.cliff(audience)["evidence"])
        self.assertNotIn("With Homestead", self.cliff("investor")["evidence"])

    def test_cliff_severity_still_assumes_an_occupant_takes_homestead(self):
        self.assertEqual(self.cliff("buyer")["severity"], "warn")
        self.assertEqual(self.cliff("investor")["severity"], "critical")


class EntityTests(unittest.TestCase):
    def test_person_surnamed_church_is_private(self):
        self.assertFalse(analysis.is_entity("CHURCH JOHN"))
        self.assertTrue(analysis.is_entity("MT ZION BAPTIST CHURCH"))

    def test_entities_and_people(self):
        self.assertTrue(analysis.is_entity("2125 ABIGAIL INVESTMENTS"))
        self.assertTrue(analysis.is_entity("V2 PROPERTIES ENTITY 6 LLC"))
        self.assertFalse(analysis.is_entity("DOE JANE"))


class MathTests(unittest.TestCase):
    def test_investor_math(self):
        ctx = {"price": 300000, "rent": 2000, "rate": 0.07, "down": 0.25, "audience": "investor"}
        result = analysis.analyze(base_data(), ctx, TODAY)["investor"]
        self.assertEqual(result["transfer_tax_total"], round(300000 * 0.04578))
        self.assertAlmostEqual(result["loan"]["monthly_payment"], 1497, delta=2)


class ReportTests(unittest.TestCase):
    def test_negative_money_reads_naturally(self):
        self.assertEqual(report.money(-16403), "-$16,403")

    def test_redaction_removes_private_names_and_keeps_companies(self):
        docs = [deed("2025-01-01", 200000, "SMITH JOHN", "ACME HOLDINGS LLC")]
        data = base_data(documents=docs)
        result = analysis.analyze(data, today=TODAY)
        page = report.render(data, result, redact=True)
        self.assertNotIn("DOE JANE", page)
        self.assertNotIn("SMITH JOHN", page)
        self.assertIn("ACME HOLDINGS LLC", page)

    def test_html_is_escaped(self):
        data = base_data()
        data["opa"]["owner_1"] = "<script>alert(1)</script>"
        page = report.render(data, analysis.analyze(data, today=TODAY))
        self.assertNotIn("<script>alert(1)</script>", page)


if __name__ == "__main__":
    unittest.main()
