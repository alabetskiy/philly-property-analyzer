# Data Sources and Their Limits

All sources are public and need no API key. Availability was checked **2026-11-01**. Philadelphia's data is at `https://phl.carto.com/api/v2/sql` unless noted.

| Dataset | Table or service | Used for | Known limits |
|---|---|---|---|
| Address lookup | `api.phila.gov/ais/v1/search/` | Parcel ID, zoning, historic status, schools, coordinates | Silently returns the building when a unit isn't known. Often has no account number for condos. The script handles both. |
| Property record | `opa_properties_public` | Owner, value, size, age, condition, last sale | Condition codes can be years old. Interiors are mostly never inspected. |
| Assessment history | `assessments` | Value by year, abatement start | Back to 2013 at most. Doesn't name the type of exemption. |
| Recorded documents | `rtt_summary` | Deeds, sheriff's deeds, mortgages | Lags the assessor's sale field. In testing, one sale from September 2026 showed in the assessor's record with no matching deed yet. Contains typo dates such as year 9798. |
| Code violations | `violations` | Open and past L&I cases | Only what someone reported and L&I cited. |
| Dangerous buildings | `unsafe`, `imm_dang` | Open structural cases, including neighbors | Neighbor search uses an approximate 80-foot radius, so it can't confirm a shared wall. |
| Permits | `permits` | Work history, expired permits, stop-work orders | Older records are thinner. Some minor work needs no permit. |
| Licenses | `business_licenses` | Rental and vacant licenses | Linked by parcel, so some units may be missed. |
| Clean and seal | `li_clean_seal` | Past vacancy signals | Can predate the current building, so older records are filtered. |
| Demolitions | `demolitions` | On the parcel and next door | |
| Crime | `incidents_part1_part2` | Raw counts within a quarter mile | Reports, not convictions. Reflects reporting and foot traffic. Never scored. |
| Flood | FEMA NFHL `hazards.fema.gov` | Flood zone | Maps lag real risk, and basement water isn't captured. |

## What is not available

- **Current tax debt.** `real_estate_tax_delinquencies` refuses access, and `real_estate_tax_balances` stops at tax year 2016, so neither is used. Users must check [the city's lookup](https://tax-services.phila.gov/_/). If you find a working source, this is the most valuable upgrade to the skill.
- **Water bills, private liens, and judgments.** A title search covers these.
- **Interior condition.** Only an inspection covers this.
- **Rents.** Users supply their own. If a Zillow connector is available in the session, its rent estimate can fill `--rent`, but call it an estimate.

## How the comparison works

Nearby sales are single-parcel deeds of $25,000 or more in the last 2 years, in the same property category, within 300 m and widening to 600 m if fewer than 8 turn up. Sales between parties with matching names are dropped, as are prices outside $15-$2,000 per square foot. When at least 5 similar-sized homes (within 35%) exist, only those are used. The range is the middle 50%, rounded to $1,000. Condition isn't controlled, so a shell and a new rehab count alike. It's a screen and not an appraisal.

## Calibration

A random sample of 36 single-family parcels in testing produced 0 serious findings, 13 homes with at least one "look closer" item, and 23 with none. If a future change makes most homes "stop and verify", the rules have become too sensitive and users will stop trusting them.
