"""Hulmane US Stocks — CLI.

Usage:
    python app.py snapshot                     Rebuild data files from data/live/raw (MCP snapshot)
    python app.py price <TICKER> [<TICKER>...] Live price lookup
    python app.py report [<tag>]               Per-tag report (or summary if omitted)
    python app.py dashboard                     Launch the Streamlit dashboard

Data flow:
    Robinhood MCP (agent) -> data/live/raw/*.json
        -> [python app.py snapshot] -> data/formated/robinhood.csv + data/live/positions.json
        -> dashboard / reports read from those files; yfinance supplies live prices.
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

from src import pricing, report, snapshot  # noqa: E402


def cmd_snapshot(_args: argparse.Namespace) -> int:
    meta = snapshot.build(APP_ROOT)
    print(f"Ledger rows : {meta['ledger_rows']}  -> data/formated/robinhood.csv")
    print(f"Positions   : {meta['positions']}    -> data/live/positions.json")
    print("By account  : " + ", ".join(f"{k}={v}" for k, v in meta["accounts"].items()))
    print(f"Refreshed   : {meta['refreshed_at']}")
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
            print("No tags found. Run: python app.py snapshot")
            return 0
        print(tabulate(df, headers="keys", showindex=False, floatfmt=",.2f"))
        out = report.write_summary_report(APP_ROOT)
    print(f"\nSaved -> {out}")
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

    s = sub.add_parser("snapshot", help="Rebuild data files from data/live/raw MCP snapshot")
    s.set_defaults(func=cmd_snapshot)

    s = sub.add_parser("price", help="Live price lookup")
    s.add_argument("tickers", nargs="+")
    s.set_defaults(func=cmd_price)

    s = sub.add_parser("report", help="Per-tag report (omit tag for summary)")
    s.add_argument("tag", nargs="?")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("dashboard", help="Launch Streamlit dashboard")
    s.set_defaults(func=cmd_dashboard)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
