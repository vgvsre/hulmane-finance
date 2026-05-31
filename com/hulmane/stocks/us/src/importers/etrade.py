"""E*TRADE importer.

E*TRADE exposes two distinct CSV exports, both of which we accept:

1. ``tradesdownload (N).csv`` — header row, then plain Buy/Sell trade rows:
       Trade Date, Order Type, Security, Cusip, Transaction Description,
       Quantity, Executed Price, Commission, Net Amount
   Quantity is always positive; ``Order Type`` carries the sign (Sell -> negate).
   These exports do not include the account number.

2. ``DownloadTxnHistory*.csv`` — full activity history with a 4-line preamble
   that includes ``Account Activity for ... -NNNN ...`` (we lift the -NNNN as
   the account label), followed by a header and rows:
       Activity/Trade Date, Transaction Date, Settlement Date, Activity Type,
       Description, Symbol, Cusip, Quantity #, Price $, Amount $,
       Commission, Category, Note
   Quantity for ``Sold`` rows is already negative.

Activity types kept (mapped to action):
    Bought                                -> Buy   (cost-basis trade)
    Sold                                  -> Sell  (cost-basis trade)
    Dividend with non-zero qty AND price  -> Buy   (DRIP — dividend reinvestment)

Activity types deliberately skipped (counts surfaced in the summary):
    Reorganization     — stock splits etc., no price -> would distort cost basis
    Transfer           — outgoing ACAT shares, no price
    Qualified Dividend — cash dividend
    Funds Transferred, Online Transfer    — bank cash movements
    Interest, Interest Income             — sweep/cash interest

Multiple files in one import are common (the user redownloads in chunks). We
dedupe across files on (broker, date, ticker, action, qty, price), preferring
the file that contributed the most rows — same approach as robinhood.py.

Each emitted row carries:
    account, action, source_file — for traceability.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from io import StringIO
from pathlib import Path

import pandas as pd

APP_COLS = ["ticker", "quantity", "purchase_price", "purchase_date", "broker",
            "account", "action", "source_file"]

KEEP_ACTIVITIES = {"Bought", "Sold", "Dividend"}
SKIP_ACTIVITIES = {
    "Reorganization",
    "Transfer",
    "Qualified Dividend",
    "Funds Transferred",
    "Online Transfer",
    "Interest",
    "Interest Income",
}

DEFAULT_ACCOUNT = "etrade"  # tradesdownload files carry no account number

_TRADES_HEADER_PREFIX = "Trade Date,Order Type,Security"
_HISTORY_PREAMBLE = "All Transactions"
_HISTORY_HEADER_PREFIX = "Activity/Trade Date"
_ACCOUNT_RE = re.compile(r"-(\d{4,})\b")
_MONEY_RE = re.compile(r"[\$,]")


@dataclass
class ImportSummary:
    rows_emitted: int
    skipped_by_type: dict[str, int]
    unrecognized_types: dict[str, int]
    accounts_seen: dict[str, int]


def _money(s) -> float:
    if s is None or pd.isna(s) or s == "" or s == "--":
        return float("nan")
    s = str(s).strip()
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    s = _MONEY_RE.sub("", s)
    try:
        v = float(s)
    except ValueError:
        return float("nan")
    return -v if neg else v


def _parse_date(s, fmts: tuple[str, ...]) -> date | None:
    if s is None or pd.isna(s) or s == "":
        return None
    s = str(s).strip()
    for fmt in fmts:
        try:
            return pd.to_datetime(s, format=fmt).date()
        except ValueError:
            continue
    return None


def _detect_format(path: Path) -> str:
    """Return 'trades', 'history', or 'empty'."""
    with path.open(encoding="utf-8-sig") as fh:
        first = fh.readline().strip()
    if first.startswith(_TRADES_HEADER_PREFIX):
        return "trades"
    if first.startswith(_HISTORY_PREAMBLE):
        return "history"
    if first.lower().startswith("no data"):
        return "empty"
    raise ValueError(f"{path}: unrecognized E*TRADE export — first line: {first!r}")


def _parse_trades(path: Path) -> tuple[pd.DataFrame, ImportSummary]:
    """Parse a tradesdownload (N).csv export."""
    raw = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    expected = {"Trade Date", "Order Type", "Security", "Quantity", "Executed Price"}
    missing = expected - set(raw.columns)
    if missing:
        raise ValueError(f"{path}: missing columns: {missing}")

    out_rows: list[dict] = []
    skipped: Counter[str] = Counter()
    unrecognized: Counter[str] = Counter()

    for _, r in raw.iterrows():
        order = str(r.get("Order Type", "")).strip()
        if not order:
            continue
        if order not in {"Buy", "Sell"}:
            unrecognized[order] += 1
            continue

        sym = str(r.get("Security", "")).strip().upper()
        qty = _money(r.get("Quantity"))
        price = _money(r.get("Executed Price"))
        d = _parse_date(r.get("Trade Date"), ("%m/%d/%Y", "%m/%d/%y"))

        if not sym or pd.isna(qty) or pd.isna(price) or d is None or qty == 0 or price == 0:
            skipped[f"{order}:incomplete"] += 1
            continue

        signed_qty = qty if order == "Buy" else -qty
        out_rows.append(
            {
                "ticker": sym,
                "quantity": round(signed_qty, 6),
                "purchase_price": round(price, 4),
                "purchase_date": d.isoformat(),
                "broker": "etrade",
                "account": DEFAULT_ACCOUNT,
                "action": order,
                "source_file": path.name,
            }
        )

    df = pd.DataFrame(out_rows, columns=APP_COLS)
    summary = ImportSummary(
        rows_emitted=len(df),
        skipped_by_type=dict(skipped),
        unrecognized_types=dict(unrecognized),
        accounts_seen={DEFAULT_ACCOUNT: len(df)} if len(df) else {},
    )
    return df, summary


def _read_history_section(path: Path) -> tuple[pd.DataFrame, str]:
    """Return (df, account_label). The preamble before the header carries the account #."""
    preamble: list[str] = []
    rows: list[str] = []
    with path.open(encoding="utf-8-sig") as fh:
        for line in fh:
            if not rows:
                if line.startswith(_HISTORY_HEADER_PREFIX):
                    rows.append(line)
                else:
                    preamble.append(line)
                continue
            rows.append(line)
    if not rows:
        raise ValueError(f"{path}: header row not found — is this a DownloadTxnHistory export?")

    account = DEFAULT_ACCOUNT
    for ln in preamble:
        if "Account Activity" in ln:
            m = _ACCOUNT_RE.search(ln)
            if m:
                account = m.group(1)
                break

    df = pd.read_csv(StringIO("".join(rows)), dtype=str, keep_default_na=False)
    return df, account


def _parse_history(path: Path) -> tuple[pd.DataFrame, ImportSummary]:
    raw, account = _read_history_section(path)
    expected = {"Activity/Trade Date", "Activity Type", "Symbol", "Quantity #", "Price $"}
    missing = expected - set(raw.columns)
    if missing:
        raise ValueError(f"{path}: missing columns: {missing}")

    out_rows: list[dict] = []
    skipped: Counter[str] = Counter()
    unrecognized: Counter[str] = Counter()

    for _, r in raw.iterrows():
        activity = str(r.get("Activity Type", "")).strip()
        if not activity:
            continue
        if activity in SKIP_ACTIVITIES:
            skipped[activity] += 1
            continue
        if activity not in KEEP_ACTIVITIES:
            unrecognized[activity] += 1
            continue

        sym = str(r.get("Symbol", "")).strip().upper()
        qty = _money(r.get("Quantity #"))
        price = _money(r.get("Price $"))
        d = _parse_date(r.get("Activity/Trade Date"), ("%m/%d/%y", "%m/%d/%Y"))

        if not sym or pd.isna(qty) or pd.isna(price) or d is None or qty == 0 or price == 0:
            # Dividend rows without a price are cash dividends, not DRIPs — skip silently.
            skipped[f"{activity}:incomplete"] += 1
            continue

        # In DownloadTxnHistory, Sold rows already carry negative quantity.
        # Bought and Dividend (DRIP) carry positive quantity. Treat all DRIPs as Buy.
        action = "Sell" if activity == "Sold" else "Buy"
        out_rows.append(
            {
                "ticker": sym,
                "quantity": round(qty, 6),
                "purchase_price": round(price, 4),
                "purchase_date": d.isoformat(),
                "broker": "etrade",
                "account": account,
                "action": action,
                "source_file": path.name,
            }
        )

    df = pd.DataFrame(out_rows, columns=APP_COLS)
    summary = ImportSummary(
        rows_emitted=len(df),
        skipped_by_type=dict(skipped),
        unrecognized_types=dict(unrecognized),
        accounts_seen={account: len(df)} if len(df) else {},
    )
    return df, summary


def parse(path: Path) -> tuple[pd.DataFrame, ImportSummary]:
    fmt = _detect_format(path)
    if fmt == "trades":
        return _parse_trades(path)
    if fmt == "history":
        return _parse_history(path)
    return pd.DataFrame(columns=APP_COLS), ImportSummary(0, {}, {}, {})


def import_to_tag(app_root: Path, source: Path, tag: str) -> tuple[Path, ImportSummary]:
    source = Path(source)
    if source.is_dir():
        files = sorted(source.glob("*.csv"))
    else:
        files = [source]
    if not files:
        raise FileNotFoundError(f"No CSV files at {source}")

    frames: list[pd.DataFrame] = []
    total_skipped: Counter[str] = Counter()
    total_unrecognized: Counter[str] = Counter()
    accounts_seen: Counter[str] = Counter()

    for p in files:
        df, summary = parse(p)
        frames.append(df)
        total_skipped.update(summary.skipped_by_type)
        total_unrecognized.update(summary.unrecognized_types)
        accounts_seen.update(summary.accounts_seen)

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=APP_COLS)
    if df.empty:
        raise ValueError(f"No Buy/Sell rows found in {[str(f) for f in files]}")

    # Cross-file dedupe: tradesdownload and DownloadTxnHistory overlap on real
    # trades. Same trade can appear with account="etrade" (tradesdownload) and
    # again with account="6829" (history). Prefer the file that contributed the
    # most rows so DownloadTxnHistory wins, carrying the real account number.
    dup_keys = ["broker", "purchase_date", "ticker", "action",
                "quantity", "purchase_price"]
    file_size_rank = (
        df.groupby("source_file").size().rename("rank")
        .sort_values(ascending=False).reset_index()
    )
    rank_lookup = {row["source_file"]: i for i, row in file_size_rank.iterrows()}
    df["_rank"] = df["source_file"].map(rank_lookup)
    df = df.sort_values("_rank").drop_duplicates(subset=dup_keys, keep="first")
    n_dropped = sum(accounts_seen.values()) - len(df)
    df = df.drop(columns=["_rank"]).copy()

    df = df.sort_values(["purchase_date", "account", "ticker"], kind="stable").reset_index(drop=True)

    dest = app_root / "data" / "formated" / f"{tag}.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)

    if n_dropped > 0:
        total_skipped["duplicate-cross-file"] = n_dropped

    summary = ImportSummary(
        rows_emitted=len(df),
        skipped_by_type=dict(total_skipped),
        unrecognized_types=dict(total_unrecognized),
        accounts_seen=dict(accounts_seen),
    )
    return dest, summary
