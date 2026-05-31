"""Hulmane US Stocks — CLI.

Usage:
    python app.py rebuild                     Rebuild data/formated from data/source + write logs/
    python app.py upload <csv> <tag>          Upload a transactions CSV under a tag
    python app.py list-tags                   List all tags found in data/formated
    python app.py price <TICKER> [<TICKER>...] Live price lookup
    python app.py report [<tag>]              Per-tag report (or summary if omitted)
    python app.py viz [<tag>]                 Generate charts
    python app.py dashboard                   Launch Streamlit dashboard (rebuilds on start)

Data flow:
    data/source/<broker>/*.csv   raw broker exports (etrade, robinhood, fedility)
        -> [rebuild pipeline] -> data/formated/<tag>.csv   formatted, account-linked
        -> reports / dashboard read ONLY from data/formated

The dashboard rebuilds from data/source on every start, so data/source can be
deleted and the app keeps working off data/formated. Per-file status lands in logs/.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from tabulate import tabulate

APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT))

from src import portfolio, pricing, report, visualize  # noqa: E402
from src import pipeline  # noqa: E402
from src.importers import etrade as etrade_importer  # noqa: E402
from src.importers import fidelity as fidelity_importer  # noqa: E402
from src.importers import robinhood as robinhood_importer  # noqa: E402


def cmd_rebuild(_args: argparse.Namespace) -> int:
    """Rebuild data/formated from data/source, from scratch, and print the log."""
    result = pipeline.run(APP_ROOT)
    for tag in result.tags:
        for f in tag.files:
            extra = f" ({f.message})" if f.message else ""
            print(f"  [{f.status:7s}] {f.broker}/{f.filename}: {f.rows} rows{extra}")
        unmatched = sum(tag.unmatched_accounts.values())
        flag = f"  !! {unmatched} rows unmatched to accounts.csv" if unmatched else ""
        print(f"=> {tag.tag}.csv: {tag.rows} rows{flag}\n")
    print(f"Total {result.total_rows} rows across {len(result.tags)} tags.")
    print(f"Formatted data -> {result.formated_dir}")
    print(f"Log -> {result.log_path}")
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    dest = portfolio.upload(APP_ROOT, Path(args.csv), args.tag)
    print(f"Uploaded -> {dest}")
    return 0


def cmd_import_fidelity(args: argparse.Namespace) -> int:
    dest = fidelity_importer.import_to_tag(APP_ROOT, Path(args.path), args.tag)
    df = portfolio.load_tag(APP_ROOT, args.tag)
    print(f"Imported {len(df)} positions from Fidelity -> {dest}")
    print(tabulate(df[["ticker", "quantity", "purchase_price", "broker"]],
                   headers="keys", showindex=False, floatfmt=",.4f"))
    return 0


def cmd_import_robinhood(args: argparse.Namespace) -> int:
    dest, summary = robinhood_importer.import_to_tag(APP_ROOT, Path(args.path), args.tag)
    print(f"Imported {summary.rows_emitted} Buy/Sell rows from Robinhood -> {dest}")
    if summary.accounts_seen:
        print("\nAccounts seen (rename via data/robinhood/_accounts.json):")
        for acct, n in sorted(summary.accounts_seen.items(), key=lambda kv: -kv[1]):
            print(f"  {acct:24s} {n} rows")
    if summary.skipped_by_code:
        print("\nSkipped (non-trade rows):")
        for code, n in sorted(summary.skipped_by_code.items()):
            print(f"  {code:20s} {n}")
    if summary.unrecognized_codes:
        print("\nUnrecognized Trans Codes (review):")
        for code, n in sorted(summary.unrecognized_codes.items()):
            print(f"  {code:20s} {n}")
    return 0


def cmd_import_etrade(args: argparse.Namespace) -> int:
    dest, summary = etrade_importer.import_to_tag(APP_ROOT, Path(args.path), args.tag)
    print(f"Imported {summary.rows_emitted} Buy/Sell rows from E*TRADE -> {dest}")
    if summary.accounts_seen:
        print("\nAccounts seen:")
        for acct, n in sorted(summary.accounts_seen.items(), key=lambda kv: -kv[1]):
            print(f"  {acct:24s} {n} rows")
    if summary.skipped_by_type:
        print("\nSkipped (non-trade rows):")
        for code, n in sorted(summary.skipped_by_type.items()):
            print(f"  {code:24s} {n}")
    if summary.unrecognized_types:
        print("\nUnrecognized Activity Types (review):")
        for code, n in sorted(summary.unrecognized_types.items()):
            print(f"  {code:24s} {n}")
    return 0


def cmd_list_tags(_args: argparse.Namespace) -> int:
    tags = portfolio.list_tags(APP_ROOT)
    if not tags:
        print("No tags found. Drop CSVs into data/transactions/<tag>.csv "
              "or run: python app.py upload <csv> <tag>")
        return 0
    for t in tags:
        print(t)
    return 0


def cmd_price(args: argparse.Namespace) -> int:
    quotes = pricing.get_quotes(args.tickers)
    rows = [(q.ticker, q.name or "", f"{q.price:,.2f}", q.currency) for q in quotes.values()]
    print(tabulate(rows, headers=["Ticker", "Name", "Price", "Ccy"]))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    if args.tag:
        df = report.tag_report(APP_ROOT, args.tag)
        if df.empty:
            print(f"Tag '{args.tag}' has no positions.")
            return 0
        print(tabulate(df, headers="keys", showindex=False, floatfmt=",.2f"))
        invested = df["cost_basis"].sum()
        current = df["current_value"].sum()
        pnl = current - invested
        pct = (pnl / invested * 100.0) if invested else 0.0
        print()
        print(f"Tag '{args.tag}': invested ${invested:,.2f}  "
              f"current ${current:,.2f}  pnl ${pnl:,.2f} ({pct:+.2f}%)")
        out = report.write_tag_report(APP_ROOT, args.tag)
    else:
        df = report.all_tags_summary(APP_ROOT)
        if df.empty:
            print("No tags found.")
            return 0
        print(tabulate(df, headers="keys", showindex=False, floatfmt=",.2f"))
        out = report.write_summary_report(APP_ROOT)
    print(f"\nSaved -> {out}")
    return 0


def cmd_viz(args: argparse.Namespace) -> int:
    if args.tag:
        path = visualize.chart_position_breakdown(APP_ROOT, args.tag)
        print(f"Saved -> {path}")
    else:
        p1 = visualize.chart_tag_pnl(APP_ROOT)
        p2 = visualize.chart_tag_invested_vs_current(APP_ROOT)
        print(f"Saved -> {p1}")
        print(f"Saved -> {p2}")
    return 0


def cmd_dashboard(_args: argparse.Namespace) -> int:
    dash = APP_ROOT / "dashboard.py"
    env = os.environ.copy()
    env["HULMANE_US_APP_ROOT"] = str(APP_ROOT)
    return subprocess.call(["streamlit", "run", str(dash)], env=env)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hulmane-stocks-us",
                                description="Hulmane US Stocks portfolio tracker")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("upload", help="Upload a transactions CSV under a tag")
    s.add_argument("csv", help="Path to source CSV")
    s.add_argument("tag", help="Tag name (e.g. jan26)")
    s.set_defaults(func=cmd_upload)

    s = sub.add_parser("import-fidelity",
                       help="Import a Fidelity Portfolio Positions CSV (file or directory)")
    s.add_argument("path", help="CSV file or directory containing CSV(s)")
    s.add_argument("tag", help="Tag name (e.g. fidelity_may26)")
    s.set_defaults(func=cmd_import_fidelity)

    s = sub.add_parser("import-robinhood",
                       help="Import a Robinhood transaction-history CSV (file or directory)")
    s.add_argument("path", help="CSV file or directory containing CSV(s)")
    s.add_argument("tag", help="Tag name (e.g. robinhood_may26)")
    s.set_defaults(func=cmd_import_robinhood)

    s = sub.add_parser("import-etrade",
                       help="Import E*TRADE tradesdownload and/or DownloadTxnHistory CSV(s)")
    s.add_argument("path", help="CSV file or directory containing CSV(s)")
    s.add_argument("tag", help="Tag name (e.g. etrade)")
    s.set_defaults(func=cmd_import_etrade)

    s = sub.add_parser("rebuild",
                       help="Rebuild data/formated from data/source (ground zero) + write logs/")
    s.set_defaults(func=cmd_rebuild)

    s = sub.add_parser("list-tags", help="List all tags")
    s.set_defaults(func=cmd_list_tags)

    s = sub.add_parser("price", help="Live price lookup")
    s.add_argument("tickers", nargs="+")
    s.set_defaults(func=cmd_price)

    s = sub.add_parser("report", help="Per-tag report (omit tag for summary)")
    s.add_argument("tag", nargs="?")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("viz", help="Generate charts")
    s.add_argument("tag", nargs="?", help="Tag for breakdown chart; omit for cross-tag charts")
    s.set_defaults(func=cmd_viz)

    s = sub.add_parser("dashboard", help="Launch Streamlit dashboard")
    s.set_defaults(func=cmd_dashboard)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
