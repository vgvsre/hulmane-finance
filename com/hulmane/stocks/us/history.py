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
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT))

from src import portfolio, pricing  # noqa: E402

DEFAULT_CONFIG = APP_ROOT / "config.json"

# Index proxies always fetched alongside the held tickers so the dashboard can
# benchmark the portfolio against the broad market (VOO = S&P 500, QQQ =
# Nasdaq-100), even in years when neither ETF was actually held.
BENCHMARK_TICKERS = ["VOO", "QQQ"]


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
    """Every distinct, non-cash ticker held across all tags, plus the index
    benchmark proxies (so VOO/QQQ history is always available to the dashboard).
    """
    held = [t for t in portfolio.all_tickers(app_root) if not pricing._is_cash(t)]
    return sorted(set(held) | set(BENCHMARK_TICKERS))


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


def history_csv_path(app_root: Path, config_path: Path | None = None) -> Path:
    """Resolve the stored close-history CSV path from config.json."""
    cfg = load_config(config_path or DEFAULT_CONFIG)
    out = Path(cfg["output_csv"])
    return out if out.is_absolute() else app_root / out


def _write_history(df: pd.DataFrame, out_path: Path) -> None:
    df = df.reindex(sorted(df.columns), axis=1).sort_index()
    df.index.name = "Date"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, float_format="%.4f")


def sync_close_history(
    app_root: Path,
    end: date | None = None,
    interval: str | None = None,
    config_path: Path | None = None,
) -> dict:
    """Bring ``close_prices.csv`` up to date — the standalone daily job.

    Resumable and self-healing, always writing the same file:
    - **No file yet** → full backfill from the config start (2019) for every
      portfolio ticker (+ VOO/QQQ benchmarks).
    - **File exists** → fetch only the gap: (last stored date + 1 .. today) for
      the columns already on file, AND backfill any newly-added portfolio ticker
      from the start date so it gets full history. Then merge into the same sheet.
    - **Already current** → no-op.

    Restarts never re-pull what's already stored. Returns a status dict:
    ``{built, new_days, new_tickers, last_date, reason}``.
    """
    cfg = load_config(config_path or DEFAULT_CONFIG)
    interval = interval or cfg["interval"]
    start = cfg["start_date"]
    out_path = history_csv_path(app_root, config_path)
    end = end or date.today()
    end_excl = (end + timedelta(days=1)).isoformat()  # yfinance end is exclusive
    want = portfolio_tickers(app_root)
    if not want:
        return {"built": False, "new_days": 0, "new_tickers": [], "last_date": None,
                "reason": "no tickers in data/formated — run `python app.py rebuild`"}

    # ── First-ever build: full backfill from the start date. ──────────────────
    if not out_path.exists():
        df = fetch_close_history(want, start, end_excl, interval)
        if df.empty:
            return {"built": False, "new_days": 0, "new_tickers": [], "last_date": None,
                    "reason": "no price data returned (network blocked?)"}
        _write_history(df, out_path)
        return {"built": True, "new_days": int(len(df)), "new_tickers": want,
                "last_date": df.index.max().date(), "reason": "full backfill from start"}

    existing = pd.read_csv(out_path, parse_dates=["Date"], index_col="Date").sort_index()
    if existing.empty:
        df = fetch_close_history(want, start, end_excl, interval)
        if df.empty:
            return {"built": False, "new_days": 0, "new_tickers": [], "last_date": None,
                    "reason": "stored history empty and no data returned"}
        _write_history(df, out_path)
        return {"built": True, "new_days": int(len(df)), "new_tickers": want,
                "last_date": df.index.max().date(), "reason": "rebuilt empty file"}

    last_date = existing.index.max().date()
    new_tickers = [t for t in want if t not in existing.columns]
    combined = existing

    # Extend existing columns forward to today.
    if last_date < end:
        fwd_start = (last_date + timedelta(days=1)).isoformat()
        fwd = fetch_close_history(list(existing.columns), fwd_start, end_excl, interval)
        if not fwd.empty:
            fwd = fwd[fwd.index.date > last_date]
        if not fwd.empty:
            combined = pd.concat([combined, fwd])
            combined = combined[~combined.index.duplicated(keep="last")]

    # Backfill brand-new portfolio tickers from the start date (full history).
    if new_tickers:
        back = fetch_close_history(new_tickers, start, end_excl, interval)
        if not back.empty:
            combined = combined.join(back, how="outer")

    new_days = combined.index.max().date()
    if combined.equals(existing) or (new_days == last_date and not new_tickers):
        return {"built": False, "new_days": 0, "new_tickers": [], "last_date": last_date,
                "reason": "already current (no new trading days)"}

    _write_history(combined, out_path)
    return {"built": False, "new_days": int((combined.index.date > last_date).sum()),
            "new_tickers": new_tickers, "last_date": new_days, "reason": "synced"}


# Back-compat alias: the lightweight top-up the dashboard calls on Live.
update_close_history = sync_close_history


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Day-end close price history for the portfolio")
    p.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to config.json")
    p.add_argument("--start", help="Start date (ISO); overrides config")
    p.add_argument("--end", help="End date (ISO); overrides config (default: today)")
    p.add_argument("--out", help="Output CSV path; overrides config")
    p.add_argument("--interval", help="yfinance interval (1d/1wk/1mo); overrides config")
    p.add_argument("--sync", "--update", dest="sync", action="store_true",
                   help="Daily job: resume from the last stored close and fetch "
                        "only the gap to today (full backfill from the start date "
                        "if there's no file yet, or for newly-added tickers). "
                        "Restarts never re-pull what's already stored.")
    args = p.parse_args(argv)

    if args.sync:
        end = date.fromisoformat(args.end) if args.end else None
        status = sync_close_history(APP_ROOT, end=end, interval=args.interval,
                                    config_path=Path(args.config))
        if status["built"]:
            print(f"Built history from scratch: {status['new_days']} trading day(s) "
                  f"x {len(status['new_tickers'])} tickers -> last close "
                  f"{status['last_date']}")
        elif status["reason"] == "synced":
            extra = (f", backfilled {len(status['new_tickers'])} new ticker(s): "
                     f"{', '.join(status['new_tickers'])}" if status["new_tickers"] else "")
            print(f"Synced +{status['new_days']} new trading day(s) -> last close "
                  f"now {status['last_date']}{extra}")
        else:
            print(f"No change: {status['reason']} "
                  f"(last stored close {status['last_date']}).")
        return 0

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
