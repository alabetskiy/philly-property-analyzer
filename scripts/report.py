"""Renders a self-contained HTML report. No external requests, so it works offline and prints cleanly."""
import html
import re

from analysis import is_entity

STATUS = {
    "stop": ("Stop &amp; verify", "stop"),
    "look": ("Look closer", "look"),
    "note": ("Worth noting", "note"),
    "clear": ("Nothing found", "clear"),
    "unknown": ("Couldn't check", "unknown"),
}
SEVERITY = {"critical": "Stop &amp; verify", "warn": "Look closer", "info": "Note", "good": "Good sign"}

CSS = """
:root{--bg:#f6f3ec;--paper:#fffdf8;--ink:#1d2430;--muted:#5d6675;--line:#ddd6c8;--accent:#1f4e79;
--stop:#a32a1f;--stop-bg:#fbe9e6;--look:#8a5a00;--look-bg:#fbf1da;--note:#1f4e79;--note-bg:#e7eff7;
--clear:#2c6e49;--clear-bg:#e5f2ea;--unknown:#5d6675;--unknown-bg:#eceae4}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#14181f;--paper:#1c222b;--ink:#ebe7df;
--muted:#a3abb8;--line:#333b47;--accent:#8fbce6;--stop:#f2a095;--stop-bg:#3c211e;--look:#e5bd6c;--look-bg:#362c17;
--note:#9cc5ea;--note-bg:#1d2d3d;--clear:#8fd0aa;--clear-bg:#1b3226;--unknown:#a3abb8;--unknown-bg:#2a2f37}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 Georgia,'Times New Roman',serif}
main{max-width:880px;margin:0 auto;padding:40px 16px 64px}
.sans,h2,h3,table,.pill,.stat,.lens{font-family:'Segoe UI',system-ui,-apple-system,Helvetica,Arial,sans-serif}
.kicker{font:600 12px/1 'Segoe UI',system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
h1{font-size:clamp(30px,6vw,46px);line-height:1.1;margin:10px 0 6px;font-weight:700}
.sub{color:var(--muted);margin:0 0 20px}
.headline{font-size:clamp(19px,3vw,24px);line-height:1.3;border-left:4px solid var(--accent);padding:2px 0 2px 14px;margin:24px 0}
.headline.stop{border-color:var(--stop)}.headline.look{border-color:var(--look)}.headline.clear{border-color:var(--clear)}
h2{font-size:21px;margin:42px 0 12px;padding-bottom:7px;border-bottom:1px solid var(--line)}
.lenses{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:9px}
.lens{background:var(--paper);border:1px solid var(--line);border-radius:7px;padding:11px 13px}
.lens b{display:block;font-size:14px;margin-bottom:6px}
.pill{display:inline-block;font-size:12px;font-weight:600;padding:2px 9px;border-radius:99px;white-space:nowrap}
.stop-c{color:var(--stop);background:var(--stop-bg)}.look-c{color:var(--look);background:var(--look-bg)}
.note-c{color:var(--note);background:var(--note-bg)}.clear-c{color:var(--clear);background:var(--clear-bg)}
.unknown-c{color:var(--unknown);background:var(--unknown-bg)}
.flag{background:var(--paper);border:1px solid var(--line);border-radius:7px;padding:14px 16px;margin:10px 0;break-inside:avoid}
.flag.critical{border-left:4px solid var(--stop)}.flag.warn{border-left:4px solid var(--look)}
.flag h3{font-size:16px;margin:7px 0 4px}.flag p{margin:5px 0}
.evidence{font:14px/1.45 'Segoe UI',system-ui,sans-serif;color:var(--muted);overflow-wrap:anywhere}
.ask{font-weight:600}
ol.questions{padding-left:22px}ol.questions li{margin:7px 0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:9px;margin:12px 0}
.stat{background:var(--paper);border:1px solid var(--line);border-radius:7px;padding:11px 13px}
.stat span{display:block;font-size:12px;color:var(--muted)}.stat strong{font-size:21px}
.bar-row{display:grid;grid-template-columns:minmax(100px,170px) 1fr 76px;gap:8px;align-items:center;margin:7px 0;font:14px 'Segoe UI',system-ui,sans-serif}
.bar-track{background:var(--unknown-bg);border-radius:3px;height:14px}.bar{height:14px;border-radius:3px;background:var(--accent)}
.bar.alt{background:var(--look)}.bar-row em{font-style:normal;text-align:right}
.wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
a{color:var(--accent)}
footer{margin-top:44px;padding-top:14px;border-top:1px solid var(--line);font:13px/1.5 'Segoe UI',system-ui,sans-serif;color:var(--muted)}
@media print{body{background:#fff}main{max-width:none;padding:0}.flag,.lens,.stat{border-color:#bbb}}
"""


def esc(value):
    return html.escape("" if value is None else str(value))


def money(value):
    if value is None:
        return "n/a"
    return f"-${-value:,.0f}" if value < 0 else f"${value:,.0f}"


def _private_names(data):
    names = set()
    opa = data.get("opa") or {}
    candidates = [opa.get("owner_1"), opa.get("owner_2"), opa.get("mailing_care_of")]
    for doc in data.get("documents") or []:
        candidates += (doc.get("grantors") or "").split(";") + (doc.get("grantees") or "").split(";")
    for name in candidates:
        name = (name or "").strip()
        if name and not is_entity(name):
            names.add(name)
    return sorted(names, key=len, reverse=True)


def _redact(page, names):
    for name in names:
        page = page.replace(esc(name), "[private owner]")
    return page


def _flag_card(flag):
    link = f' <a href="{esc(flag["link"])}">Check it here</a>' if flag.get("link") else ""
    ask = f'<p class="ask">Ask: {esc(flag["ask"])}</p>' if flag.get("ask") else ""
    kind = {"critical": "stop-c", "warn": "look-c", "info": "note-c", "good": "clear-c"}[flag["severity"]]
    return (f'<div class="flag {flag["severity"]}"><span class="pill {kind}">{SEVERITY[flag["severity"]]}</span>'
            f'<h3>{esc(flag["title"])}</h3><p class="evidence">{esc(flag["evidence"])}</p>'
            f'<p>{esc(flag["why"])}{link}</p>{ask}</div>')


def _tax_section(tax):
    rows = [("Bill on today's record", tax["current_bill"], "")]
    if tax["abated"] or tax["fully_exempt"]:
        rows.append(("Without exemption, with Homestead", tax["with_homestead_bill"], " alt"))
    elif tax["homestead_on_record"]:
        rows.append(("If the owner doesn't live there", tax["full_bill"], " alt"))
    else:
        rows.append(("If owner-occupied (Homestead)", tax["with_homestead_bill"], ""))
    rows.append(("Full, no exclusions", tax["full_bill"], " alt"))
    top = max(r[1] for r in rows) or 1
    bars = "".join(
        f'<div class="bar-row"><span>{esc(label)}</span><div class="bar-track">'
        f'<div class="bar{cls}" style="width:{value / top * 100:.0f}%"></div></div><em>{money(value)}</em></div>'
        for label, value, cls in rows)
    year = f" for tax year {tax['year']}" if tax.get("year") else ""
    return (f'<h2>The tax bill, three ways</h2><p class="sub">Assessed at {money(tax["market_value"])}{year}. '
            f'Rate {tax["rate"] * 100:.4f}%, checked {esc(tax["rates_checked"])}.</p>{bars}')


def _comps_section(comps):
    if "mid" not in comps:
        return ""
    rows = "".join(
        '<tr><td>{}</td><td>{}</td><td class="n">{}</td><td class="n">{}</td><td class="n">{}</td></tr>'.format(
            esc(c["date"]), esc(c["address"]), money(c["price"]),
            "{:,.0f}".format(c["area"]) if c["area"] else "n/a",
            money(c["ppsf"]) if c["ppsf"] else "n/a")
        for c in comps["rows"])
    return (f'<h2>Nearby sales</h2><div class="stats"><div class="stat"><span>Lower quarter</span><strong>{money(comps["low"])}</strong></div>'
            f'<div class="stat"><span>Middle</span><strong>{money(comps["mid"])}</strong></div>'
            f'<div class="stat"><span>Upper quarter</span><strong>{money(comps["high"])}</strong></div></div>'
            f'<p class="sub">{comps["count"]} sales within {comps.get("radius_m")} m over 2 years, using {esc(comps["method"])}. '
            f'Confidence: {esc(comps["confidence"])}. Records can\'t see condition. This is a screen, not an appraisal.</p>'
            f'<div class="wrap"><table><tr><th>Date</th><th>Address</th><th class="n">Price</th><th class="n">Sq ft</th><th class="n">$/sq ft</th></tr>{rows}</table></div>')


def _sales_section(sales):
    if not sales:
        return ""
    rows = "".join(
        f'<tr><td>{esc(s["date"])}</td><td>{esc(s["kind"].title())}</td><td class="n">{money(s["price"]) if s["price"] else "$0 or none"}</td>'
        f'<td>{esc(s["grantors"])}</td><td>{esc(s["grantees"])}</td></tr>' for s in sales)
    return ('<h2>Ownership trail</h2><div class="wrap"><table><tr><th>Date</th><th>Type</th><th class="n">Amount</th>'
            f'<th>From</th><th>To</th></tr>{rows}</table></div>')


def _investor_section(inv):
    if not inv:
        return ""

    def col(case):
        cells = [money(case["annual_tax"]), money(case["noi"]), f'{case["cap_rate"] * 100:.1f}%']
        if "annual_cash_flow" in case:
            coc = f'{case["cash_on_cash"] * 100:.1f}%' if case.get("cash_on_cash") is not None else "n/a"
            cells += [money(case["annual_cash_flow"]), coc, f'{case["dscr"]:.2f}']
        return cells

    labels = ["Annual property tax", "Net operating income", "Cap rate"]
    if "annual_cash_flow" in inv["today"]:
        labels += ["Cash flow after debt", "Cash-on-cash return", "Debt coverage (DSCR)"]
    rows = "".join(f'<tr><td>{esc(l)}</td><td class="n">{a}</td><td class="n">{b}</td></tr>'
                   for l, a, b in zip(labels, col(inv["today"]), col(inv["full_tax"])))
    a = inv["assumptions"]
    return (f'<h2>The numbers on your assumptions</h2><div class="wrap"><table><tr><th></th><th class="n">Today\'s tax</th>'
            f'<th class="n">Full tax</th></tr>{rows}</table></div>'
            f'<p class="sub">Assumes {money(a["price"])} price, {money(a["monthly_rent"])}/mo rent, {a["vacancy"]:.0%} vacancy, '
            f'{a["maintenance"]:.0%} maintenance, {a["management"]:.0%} management, {money(a["insurance"])}/yr insurance. '
            f'Philadelphia transfer tax totals about {money(inv["transfer_tax_total"])}; half is {money(inv["transfer_tax_half"])}, though the split is negotiable. '
            'This is arithmetic, not investment advice. Change the inputs and it changes.</p>')


def _context_section(result):
    context = result.get("context") or {}
    crime = context.get("crime_last_12_months_quarter_mile")
    momentum = context.get("building_permits_nearby") or {}
    parts = []
    if momentum:
        parts.append(f'<p>Building and demolition permits within about 1,000 ft: <b>{esc(momentum.get("recent") or 0)}</b> in the last 2 years, '
                     f'<b>{esc(momentum.get("prior") or 0)}</b> in the 2 years before.</p>')
    if crime:
        rows = "".join(f'<tr><td>{esc(c["category"])}</td><td class="n">{esc(c["n"])}</td></tr>' for c in crime[:10])
        parts.append('<p class="sub">Police incident reports within a quarter mile in the last 12 months. Raw counts, unscored: they '
                     'reflect reporting and how busy an area is, not whether a place is right for you.</p>'
                     f'<div class="wrap"><table><tr><th>Category</th><th class="n">Reports</th></tr>{rows}</table></div>')
    if not parts:
        return ""
    return "<h2>Around the block</h2>" + "".join(parts)


def render(data, result, redact=False):
    opa = data.get("opa") or {}
    address = data.get("address") or {}
    critical, warn = result["counts"]["critical"], result["counts"]["warn"]
    head_class = "stop" if critical else ("look" if warn else "clear")

    lens_cards = "".join(
        f'<div class="lens"><b>{esc(l["title"])}</b><span class="pill {STATUS[l["status"]][1]}-c">{STATUS[l["status"]][0]}</span></div>'
        for l in result["lenses"])
    serious = [f for f in result["flags"] if f["severity"] in ("critical", "warn")]
    other = [f for f in result["flags"] if f["severity"] in ("info", "good")]
    questions = "".join(f"<li>{esc(q)}</li>" for q in dict.fromkeys(result["questions"]).keys())

    owner = " / ".join(o for o in [opa.get("owner_1"), opa.get("owner_2")] if o) or "Unknown"
    facts = [
        ("Owner on record", owner),
        ("Type", opa.get("building_code_description_new") or opa.get("building_code_description") or opa.get("category_code_description")),
        ("Built", opa.get("year_built")),
        ("Living area", f'{float(opa.get("total_livable_area")):,.0f} sq ft' if opa.get("total_livable_area") else None),
        ("Bed / bath", f'{opa.get("number_of_bedrooms") or "?"} / {opa.get("number_of_bathrooms") or "?"}'),
        ("OPA account", address.get("opa_account_num") or opa.get("parcel_number")),
    ]
    fact_cards = "".join(f'<div class="stat"><span>{esc(k)}</span><b>{esc(v) if v else "n/a"}</b></div>' for k, v in facts)

    gaps = result.get("gaps") or {}
    gap_html = ""
    if gaps:
        items = "".join(f"<li><b>{esc(k)}</b>: {esc(v)}</li>" for k, v in gaps.items())
        gap_html = f'<h2>What couldn\'t be checked</h2><p>These sources failed during this run, so treat them as unknown, not clean. Run it again later.</p><ul>{items}</ul>'

    addr = esc(result.get("address") or opa.get("location"))
    atlas = "https://atlas.phila.gov/" + re.sub(r"\s+", "%20", str(result.get("address") or ""))
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{addr} Record Check</title><style>{CSS}</style></head><body><main>
<div class="kicker">Before You Sign &middot; Philadelphia record check</div>
<h1>{addr}</h1><p class="sub">Philadelphia, PA {esc(address.get("zip_code"))} &middot; records as of {esc(result["as_of"])}</p>
<p class="headline {head_class}">{esc(result["headline"])}</p>
<div class="lenses">{lens_cards}</div>
<div class="stats sans">{fact_cards}</div>
{"<h2>Look at these first</h2>" + "".join(_flag_card(f) for f in serious) if serious else ""}
{"<h2>Ask before you sign</h2><ol class='questions'>" + questions + "</ol>" if questions else ""}
{_tax_section(result["tax"])}
{_comps_section(result["comps"])}
{_investor_section(result.get("investor"))}
{_sales_section(result["sales"])}
{"<h2>Everything else we noticed</h2>" + "".join(_flag_card(f) for f in other) if other else ""}
{_context_section(result)}
{gap_html}
<footer>
<p>Built from Philadelphia open data (OPA, L&amp;I, Department of Records) and FEMA flood maps. Verify at <a href="{esc(atlas)}">Atlas</a>,
<a href="https://property.phila.gov/">property.phila.gov</a>, and <a href="https://li.phila.gov/">li.phila.gov</a>.</p>
<p>This is a screen of public records, not an inspection, appraisal, title search, or legal or investment advice. "Nothing found" only means nothing appears in the record.
Records lag and contain errors. Flags are questions to ask, not accusations about anyone. Get a title company, an inspector, and, where it matters, a lawyer.</p>
</footer></main></body></html>"""
    if redact:
        page = _redact(page, _private_names(data))
    return page


def render_compare(results):
    """results: list of analyze() outputs."""
    head = "".join(f"<th>{esc(r['address'])}</th>" for r in results)

    def row(label, cell):
        return f"<tr><th>{esc(label)}</th>" + "".join(f"<td>{cell(r)}</td>" for r in results) + "</tr>"

    rows = [row("Summary", lambda r: esc(r["headline"]))]
    for index, (_key, title) in enumerate([(l["key"], l["title"]) for l in results[0]["lenses"]]):
        rows.append(row(title, lambda r, i=index: (
            f'<span class="pill {STATUS[r["lenses"][i]["status"]][1]}-c">{STATUS[r["lenses"][i]["status"]][0]}</span>')))
    rows += [
        row("City's value", lambda r: money(r["tax"]["market_value"])),
        row("Tax bill today", lambda r: money(r["tax"]["current_bill"])),
        row("Tax bill, full", lambda r: money(r["tax"]["full_bill"])),
        row("Nearby sales, middle", lambda r: money(r["comps"].get("mid"))),
        row("Open violations", lambda r: esc(len(r["open_violations"]))),
    ]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Philly Address Comparison</title><style>{CSS}</style></head><body><main style="max-width:1100px">
<div class="kicker">Before You Sign &middot; Side by side</div><h1>{len(results)} addresses compared</h1>
<div class="wrap"><table><tr><th></th>{head}</tr>{"".join(rows)}</table></div>
<footer><p>A screen of public records, not an inspection, appraisal, title search, or legal or investment advice.</p></footer>
</main></body></html>"""
