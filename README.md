# Before You Sign: Philly Property Analyzer

**A Claude skill that checks any Philadelphia address against public records in seconds, then tells you what the listing didn't.**

Give Claude an address or paste a listing:

> "Thinking of offering $725k on this place. It says gut renovated with all new electric. Seller is ABC Homes LLC."

You get the problems that matter, the questions to ask, and a report you can print or send to your agent. There are no accounts or API keys and nothing to subscribe to.

See a [sample report](examples/sample-report.html). GitHub shows it as code, so download the file and open it in a browser.

## What it catches

| Check | What it finds | Why it matters in Philly |
|---|---|---|
| **Ghost renovation** | A big price jump with no permit trail, or listing claims with no matching permit | New finishes can hide unchecked wiring and structure |
| **Abatement cliff** | Tax bills held low by an expiring abatement, with the bill before and after | Can add thousands a year that the monthly payment quote leaves out |
| **The real tax bill** | Today's bill, with Homestead, and with no exclusions | The seller's number may not be yours |
| **Deed-fraud signals** | Seller doesn't match the record, or a near-$0 transfer followed by a quick sale | Philadelphia has a long-running deed-theft problem |
| **Party-wall risk** | Unsafe buildings and recent demolitions within about 80 feet | Rowhouses share walls, so a neighbor's problem can become yours |
| **Code history** | Open violations, court cases, unpaid city balances, unsafe designations | These can carry fines and follow the property |
| **Rental check** | License status, lead certificate rules, and a company owner's other buildings | Renters can see whether a landlord looks compliant |
| **Illegal units** | More units on record than the zoning suggests | Can affect rent, financing, and insurance |
| **Price screen** | Asking price against nearby sales | Spot an overpriced listing or an unusually cheap one |
| **Assessment check** | City value against nearby sales, and a missing Homestead | Owners may be overpaying |
| **Site checks** | FEMA flood zone, historic designation, zoning in plain English | These affect insurance and what you can build |

## Who it's for

- **Buyers:** know what to ask before making an offer.
- **Renters:** check a landlord before handing over a deposit.
- **Small investors:** get license and unit checks plus return math at both today's tax and the full tax.
- **Homeowners:** see whether you're missing Homestead or could have a case for an appeal.
- **Agents and housing counselors:** get a fast, consistent first screen for clients.

## Install

**Claude Code:** copy this folder into your skills directory.

```bash
git clone https://github.com/alabetskiy/philly-property-analyzer.git ~/.claude/skills/philly-property-analyzer
```

**Claude apps:** download `philly-property-analyzer.skill` from the [latest release](https://github.com/alabetskiy/philly-property-analyzer/releases/latest) and upload it under Settings > Capabilities > Skills. The skill needs network access to `phl.carto.com`, `api.phila.gov`, and `hazards.fema.gov`, so check that your plan and code-execution settings allow those domains.

Requires Python 3.9 or newer. It uses the standard library only.

## Try asking

- "Check 1234 Market St before I make an offer."
- "My landlord at [address] wants a deposit. Are they licensed?"
- "Compare these three houses for me: ..."
- "If I rent [address] for $2,400 at 7% with 25% down, what does it look like after the abatement?"
- "Am I overpaying property tax on [my address]?"

Or run it without Claude:

```bash
python scripts/philly.py analyze "1234 Market St" --for buyer --html report.html
python scripts/philly.py compare "100 A St" "200 B St" --html compare.html
```

## What it won't do

- **It can't check current tax debt.** The city's delinquency data isn't open to automated access, so the skill links to the official lookup every time.
- **It isn't an inspection, appraisal, or title search.** It's what you do before paying for those. "Nothing found" means nothing is in the record.
- **It won't rate neighborhoods.** It reports raw incident counts only, with no score and no demographics, in keeping with fair housing principles.
- **It won't profile private people.** Multi-property owner lookups run for companies only, and `--redact` hides individuals' names in shared reports.
- **It won't tell you to buy.** Flags are questions, not accusations, and the investor math is arithmetic on your own assumptions. Nothing here is legal, tax, or investment advice.

## Keeping it accurate

Tax rates and deadlines live in [references/philly-playbook.md](references/philly-playbook.md) and at the top of `scripts/analysis.py`, with the date last checked. They were last checked on 2026-11-01. Limits of each dataset are in [references/data-sources.md](references/data-sources.md).

```bash
python -m unittest discover -s tests
```

Contributions are welcome, especially a reliable open source for current tax delinquency. Porting the idea to another city means replacing `sources.py` and the local rules in `analysis.py`.

## License

MIT. Data comes from the City of Philadelphia and FEMA. This project isn't affiliated with or endorsed by either.
