#!/usr/bin/env python3
"""Before You Sign: a public-records check for any Philadelphia address.

  python philly.py analyze "1234 Example St" --for buyer --price 425000 --html report.html
  python philly.py compare "100 A St" "200 B St" --html compare.html

Prints a JSON summary to stdout. Exit codes: 0 ok, 2 address not found, 3 several matches, 4 data error.
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analysis  # noqa: E402
import report  # noqa: E402
import sources  # noqa: E402


def emit(payload, code=0):
    print(json.dumps(payload, indent=1, default=str))
    sys.exit(code)


def pick_candidate(address):
    try:
        candidate, problem = sources.resolve(address)
    except sources.SourceError as exc:
        emit({"error": "address_service_unavailable", "detail": str(exc)}, 4)
    if problem:
        emit(problem, 2 if problem["error"] in ("address_not_found", "outside_philadelphia") else 3)
    return candidate


def run_one(address, ctx):
    candidate = pick_candidate(address)
    data = sources.gather(candidate, entity_check=analysis.is_entity)
    return data, analysis.analyze(data, ctx)


def stdout_summary(result, html_path=None):
    summary = {k: result[k] for k in (
        "address", "as_of", "audience", "headline", "counts", "lenses", "flags", "questions", "tax",
        "comps", "sales", "investor", "gaps", "context")}
    summary["tax"] = {k: v for k, v in result["tax"].items() if k != "history"}
    summary["comps"] = {k: v for k, v in result["comps"].items() if k != "rows"}
    summary["open_violation_count"] = len(result["open_violations"])
    if html_path:
        summary["report"] = os.path.abspath(html_path)
    return summary


def write(path, text):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def cmd_analyze(args):
    claims = [c.strip() for c in (args.claims or "").split(",") if c.strip()]
    unknown = [c for c in claims if c not in analysis.CLAIM_PERMITS]
    if unknown:
        emit({"error": "unknown_claims", "unknown": unknown, "valid": sorted(analysis.CLAIM_PERMITS)}, 4)
    ctx = {"audience": args.audience, "price": args.price, "seller": args.seller, "claims": claims,
           "rent": args.rent, "rate": args.rate, "down": args.down, "term": args.term,
           "vacancy": args.vacancy, "maintenance": args.maintenance, "management": args.management,
           "insurance": args.insurance}
    try:
        data, result = run_one(args.address, ctx)
    except sources.SourceError as exc:
        emit({"error": "data_error", "detail": str(exc)}, 4)
    if args.html:
        write(args.html, report.render(data, result, redact=args.redact))
    if args.json:
        write(args.json, json.dumps({"data": data, "result": result}, indent=1, default=str))
    emit(stdout_summary(result, args.html))


def cmd_compare(args):
    ctx = {"audience": args.audience}
    if len(args.addresses) < 2:
        emit({"error": "need_two_addresses"}, 4)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            pairs = list(pool.map(lambda a: run_one(a, ctx), args.addresses))
    except sources.SourceError as exc:
        emit({"error": "data_error", "detail": str(exc)}, 4)
    results = [pair[1] for pair in pairs]
    if args.html:
        write(args.html, report.render_compare(results))
    emit({"compared": [{
        "address": r["address"], "headline": r["headline"], "counts": r["counts"],
        "lenses": {l["key"]: l["status"] for l in r["lenses"]},
        "tax_now": r["tax"]["current_bill"], "tax_full": r["tax"]["full_bill"],
        "comps_mid": r["comps"].get("mid"), "open_violations": len(r["open_violations"]),
        "top_flags": [f["title"] for f in r["flags"] if f["severity"] in ("critical", "warn")][:6],
    } for r in results], "report": os.path.abspath(args.html) if args.html else None})


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    one = sub.add_parser("analyze", help="Check one address")
    one.add_argument("address")
    one.add_argument("--for", dest="audience", choices=["buyer", "renter", "investor", "owner"], default="buyer")
    one.add_argument("--price", type=float, help="Asking or offer price")
    one.add_argument("--seller", help="Name of the person or company claiming to sell or rent it")
    one.add_argument("--claims", help="Listing claims, comma separated: " + ",".join(sorted(analysis.CLAIM_PERMITS)))
    one.add_argument("--rent", type=float, help="Expected monthly rent")
    one.add_argument("--rate", type=float, help="Annual mortgage rate as a decimal, e.g. 0.07")
    one.add_argument("--down", type=float, help="Down payment as a decimal, e.g. 0.25")
    one.add_argument("--term", type=int, default=30)
    one.add_argument("--vacancy", type=float, default=0.05)
    one.add_argument("--maintenance", type=float, default=0.08)
    one.add_argument("--management", type=float, default=0.0)
    one.add_argument("--insurance", type=float, default=1500.0)
    one.add_argument("--html", help="Write the HTML report here")
    one.add_argument("--json", help="Write the full raw data here")
    one.add_argument("--redact", action="store_true", help="Hide private individuals' names in the HTML report")
    one.set_defaults(func=cmd_analyze)

    many = sub.add_parser("compare", help="Compare two or more addresses")
    many.add_argument("addresses", nargs="+")
    many.add_argument("--for", dest="audience", choices=["buyer", "renter", "investor", "owner"], default="buyer")
    many.add_argument("--html", help="Write the comparison here")
    many.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
