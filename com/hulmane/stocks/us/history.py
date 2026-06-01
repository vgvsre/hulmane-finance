"""Day-end (close) price history for every ticker in the portfolio.

Standalone program — reads the start date (and optional end date) from
``config.json``, collects every distinct ticker across all tags in
``data/formated/``, and fetches the daily closing price from that start date
to today via yfinance. The result is written as a wide CSV: a ``Date`` column
plus one column per ticker holding its end-of-day close.

Usage:
    python history.py                       Use dates/paths from config.json
    python history.py --start 2020-01-01    Override the start date
    python history.py --end 2024-12-31      Override the end date (default: today)
    python history.py --out prices.csv      Override the output CSV path
    python history.py --config other.json   Use a different config file

Config (config.json):
    {
      "start_date": "2019-06-01",   # ISO date; first day of close history
      "end_date": null,             # ISO date or null = up to today
      "interval": "1d",             # yfinance interval (1d, 1wk, 1mo)
      "output_csv": "data/history/close_prices.csv"
    }

Cash sweeps / money-market symbols (FCASH, FDRXX, SPAXX, ...) are skipped —
they have no market price history.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT))

from src import portfolio, pricing  # noqa: E402

DEFAULT_CONFIG = APP_ROOT / "config.json"


def load_config(path: Path) -> dict:
    """Read config.json, applying defaults for any missing keys."""
    cfg = {
        "start_date": "2019-06-01",
        "end_date": None,
        "interval": "1d",
        "output_csv": "data/history/close_prices.csv",
    }
    if path.exists():
        cfg.update(json.loads(path.read_text()))
    return cfg


def to_yahoo(ticker: str) -> str:
    """Map a portfolio ticker to its Yahoo Finance symbol.

    Yahoo uses '-' where brokers use '.' for share classes (BRK.B -> BRK-B),
    and we strip Fidelity's trailing '**' cash marker.
    """
    return ticker.rstrip("*").replace(".", "-").upper()


def portfolio_tickers(app_root: Path) -> list[str]:
    """Every distinct, non-cash ticker held across all tags."""
    return [t for t in portfolio.all_tickers(app_root) if not pricing._is_cash(t)]


def fetch_close_history(
    tickers: list[str], start: str, end: str | None, interval: str
) -> pd.DataFrame:
    """Return a wide DataFrame of daily closes (rows = dates, cols = tickers).

    Columns are labelled with the original portfolio tickers, not the Yahoo
    symbols. Tickers Yahoo has no data for come back as all-NaN columns.
    """
    yahoo_for = {t: to_yahoo(t) for t in tickers}
    symbols = sorted(set(yahoo_for.values()))

    raw = yf.download(
        symbols,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=False,
        progress=False,
        group_by="column",
        threads=True,
    )
    if raw.empty:
        return pd.DataFrame()

    # With multiple symbols yfinance returns a column MultiIndex (field, symbol);
    # with a single symbol it's a flat frame. Normalise to a per-symbol close map.
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw[["Close"]].rename(columns={"Close": symbols[0]})

    # Re-label Yahoo symbols back to portfolio tickers (one Yahoo symbol may
    # map from exactly one portfolio ticker here, so this is unambiguous).
    out = pd.DataFrame(index=close.index)
    for ticker, sym in yahoo_for.items():
        out[ticker] = close[sym] if sym in close.columns else pd.NA

    out = out.reindex(sorted(out.columns), axis=1)
    out.index.name = "Date"
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Day-end close price history for the portfolio")
    p.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to config.json")
    p.add_argument("--start", help="Start date (ISO); overrides config")
    p.add_argument("--end", help="End date (ISO); overrides config (default: today)")
    p.add_argument("--out", help="Output CSV path; overrides config")
    p.add_argument("--interval", help="yfinance interval (1d/1wk/1mo); overrides config")
    args = p.parse_args(argv)

    cfg = load_config(Path(args.config))
    start = args.start or cfg["start_date"]
    end = args.end or cfg["end_date"]
    interval = args.interval or cfg["interval"]
    out_path = Path(args.out or cfg["output_csv"])
    if not out_path.is_absolute():
        out_path = APP_ROOT / out_path

    tickers = portfolio_tickers(APP_ROOT)
    if not tickers:
        print("No tickers found in data/formated/. Run `python app.py rebuild` first.")
        return 1

    print(f"Fetching daily closes for {len(tickers)} tickers")
    print(f"  from {start} to {end or date.today().isoformat()} (interval {interval})")

    df = fetch_close_history(tickers, start, end, interval)
    if df.empty:
        print("No price data returned (network blocked, or all tickers delisted).")
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, float_format="%.4f")

    got = [c for c in df.columns if df[c].notna().any()]
    missing = [c for c in df.columns if not df[c].notna().any()]
    print(f"\nWrote {len(df):,} trading days x {len(got)} tickers -> {out_path}")
    print(f"  date range in data: {df.index.min().date()} .. {df.index.max().date()}")
    if missing:
        print(f"  no data for {len(missing)}: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
