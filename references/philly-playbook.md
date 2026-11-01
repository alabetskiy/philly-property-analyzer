# Philadelphia Playbook

Local rules behind the flags. Last checked **2026-11-01**. Rates and deadlines change, so if today is well past that date, tell the user to confirm on phila.gov. The rate constants also live at the top of `scripts/analysis.py`.

## Contents
- Real estate tax and Homestead
- Abatements
- Assessments and appeals
- Transfer tax
- Rentals
- Deed fraud
- What to do about each flag

## Real estate tax and Homestead

- **Rate:** 1.3998% of taxable value (0.6159% city, 0.7839% School District). Unchanged since 2016, and the city expected the same rate for 2027.
- **Homestead Exclusion:** takes $100,000 off the taxable value, saving up to $1,399 a year. It requires owning the home and living there as a primary residence, with no age or income test.
- **Deadlines:** December 1 is the final date each year. Applying by October 1 is recommended for early protection. Buyers closing December 2-31 may still qualify under a recent policy change.
- **Doesn't combine:** Homestead can't be used with LOOP, or with a 10-year abatement until the abatement ends. It can be used with a Low-Income or Senior Citizen Tax Freeze.
- **New buyers:** the seller's Homestead isn't a promise of what you'll pay. Apply yourself after closing.

Sources: [Homestead](https://www.phila.gov/services/payments-assistance-taxes/taxes/property-and-real-estate-taxes/get-real-estate-tax-relief/get-the-homestead-exemption/), [Eight questions about property taxes](https://www.phila.gov/2025-06-12-eight-questions-answered-about-philly-property-taxes/), [Revenue regulations](https://www.phila.gov/media/20250505143809/Real-Estate-Tax-regulations-updated-2025-May.pdf)

## Abatements

- Residential new-construction abatements run 10 years. Under the current ordinance the abated share **declines 10% a year**: year 1 fully abated, year 10 at 10%. Older abatements were generally flat for the term, so the phase-down matters for which bill to expect next year.
- The clock starts at the later of the first month after the title date or the first month after completion and certificate of occupancy.
- **The script's end year is an estimate:** first year the exemption appears in the assessment history, plus 10. It can't tell which schedule applies. Tell the user to confirm the end year and schedule with OPA.
- An abatement can be cancelled to take Homestead instead, but a removed abatement can't be reinstated. On a lower-value home, the math can favor Homestead; run it before advising them to ask OPA.

Sources: [Get a property tax abatement](https://www.phila.gov/services/payments-assistance-taxes/taxes/property-and-real-estate-taxes/get-real-estate-tax-relief/get-a-property-tax-abatement/), [2025 residential application](https://www.phila.gov/media/20250826121006/opa-application-abatement-new-construction-residential-2025.pdf)

## Assessments and appeals

- The city's market value drives the bill. 2027 values were mailed in 2026.
- **Formal appeal** goes to the Board of Revision of Taxes. For tax year 2027 the deadline was **October 5, 2026**, so that window has closed for most owners. The next cycle is expected around the same time in 2027.
- **Exception:** the form allows some new owners or buyers 30 days from the deed, agreement of sale, or notice date. Anyone who just bought should check this now.
- **First Level Review** is a separate OPA process. City sources disagreed on its 2026 date (September 1 versus October 5), so don't quote one without checking.
- **LOOP** (Longtime Owner Occupants Program): for owners of 10+ years who meet income limits, with a 50% one-year or 75% five-year assessment increase. Applications for 2027 are due September 30, 2027.
- An appeal needs evidence. The nearby sales in the report are a starting point, but sales of truly similar homes are what persuade. Appeals can also raise a value. Suggest an attorney or tax professional for high-value homes.

Sources: [Appeal an assessment](https://www.phila.gov/services/property-lots-housing/property-taxes/appeal-a-property-assessment/), [BRT appeals](https://www.phila.gov/departments/board-of-revision-of-taxes/property-assessment-appeals/), [2027 assessments notice](https://www.phila.gov/2026-06-30-city-of-philadelphia-to-mail-2027-property-assessments-and-launch-expanded-outreach-to-connect-homeowners-to-tax-relief/)

## Transfer tax

- **4.578% total** since July 1, 2025: 3.578% city plus 1% state. Many older web pages still say 4.278%.
- The buyer-seller split is custom and contract, not law. Half and half is common.

Sources: [Saul Ewing alert](https://www.saul.com/insights/alert/philadelphia-increases-realty-transfer-tax-rate-3-578-starting-july-1-2025), [EY, Aug 2025](https://taxnews.ey.com/news/2025-1650-realty-transfer-tax-and-recordation-fee-updates-in-new-jersey-pennsylvania-the-city-of-philadelphia-and-rhode-island)

## Rentals

A landlord should be able to show all three:

1. **Rental license.** City code bars collecting rent on a property that requires a license before one is issued. Renewed yearly.
2. **Certificate of Rental Suitability.** Issued by L&I within 60 days before a tenancy starts. It confirms the license is in place and that there are no known outstanding maintenance or fire code violations.
3. **Lead certificate** for pre-1978 buildings, regardless of a child's age. Lead-safe certificates last 4 years; lead-free ones don't expire. A rental license can't be issued or renewed without it.

"No license found" isn't proof of a violation, because a home might be owner-occupied, not rented, or linked to a different address record. Ask to see the documents. For tenant disputes, point to the [Fair Housing Commission](https://www.phila.gov/departments/fair-housing-commission/tenant-protections/rental-suitability/) and legal aid, not to a legal conclusion.

Sources: [Rental License Requirements](https://www.phila.gov/media/20231204173843/Rental-License-Requirements_Nov-2023.pdf), [Certificate of Rental Suitability](https://www.phila.gov/services/permits-violations-licenses/get-a-certificate/get-a-certificate-of-rental-suitability/), [Lead program FAQ](https://leadcertification.phila.gov/faq). Some of this guidance dates from 2020-2023, so confirm details with L&I.

## Deed fraud

- **Warning signs in the record:** a recent nominal-price deed, a quick sale after it, or a seller who doesn't match the record. All of these have innocent explanations, so raise them as questions.
- **Protect yourself as a buyer:** use a title company, buy owner's title insurance, and don't wire money until title is cleared.
- **Protect yourself as an owner:** [Fraud Guard](https://www.phila.gov/services/property-lots-housing/get-help-with-deed-or-mortgage-fraud/sign-up-for-deed-fraud-protection/) is free and emails you when a document is recorded with your name. Alerts can arrive about 30 days after recording. Every Philadelphia owner should have it, especially for a vacant home or an inherited one where the deed is still in a relative's name.
- **If it happened:** Department of Records (215) 686-2290 or records.info@phila.gov, a police report, the DA's Economic and Cyber Crime Unit (215) 686-9902, and a real estate attorney, because fixing it usually takes a quiet title action in court. A February 2026 law lets victims with a court order ask for the transfer tax back.

Sources: [Report deed fraud](https://www.phila.gov/2025-06-05-philadelphia-makes-it-easier-to-report-deed-fraud-online/), [Nov 2025 tool](https://www.phila.gov/2025-11-10-philadelphia-launches-new-tool-to-stop-deed-fraud/), [Feb 2026 law](https://www.phila.gov/2026-02-13-new-law-helps-deed-fraud-victims-get-money-back/)

## What to do about each flag

| Flag | Best next step |
|---|---|
| Unsafe or imminently dangerous | Structural engineer before any offer. Ask who pays. |
| Open violations | Written L&I closure as a settlement condition. |
| Ghost renovation, or a claim with no permit | Inspector who opens panels and checks basement and rear walls. Ask for permits or invoices. |
| Expired permit or no certificate of occupancy | Seller closes it before settlement. Lenders may care. |
| Abatement cliff | Budget on the full bill. Confirm end year and schedule with OPA. |
| Seller mismatch or nominal deed | Title company before any deposit. |
| Sheriff's deed | Ask the title company about redemption rights and exceptions. |
| Unit count versus zoning | Ask for the zoning permit or certificate of occupancy for those units. |
| Unsafe neighbor or recent demolition next door | Inspector checks the party wall. Mention it to your insurer. |
| FEMA high-risk zone | Insurance quote before offering. |
| Historic designation | Call the Historical Commission before planning exterior work. |
