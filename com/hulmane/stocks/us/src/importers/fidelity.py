"""Fidelity 'Portfolio Positions' export importer.

Fidelity's Portfolio_Positions_<date>.csv has these columns:
    Account Number, Account Name, Symbol, Description, Quantity,
    Last Price, Last Price Change, Current Value, Today's Gain/Loss Dollar,
    Today's Gain/Loss Percent, Total Gain/Loss Dollar, Total Gain/Loss Percent,
    Percent Of Account, Cost Basis Total, Average Cost Basis, Type

We map to the app schema:
    ticker  <- Symbol (cash symbols ending in '**' are kept verbatim)
    quantity <- Quantity (for cash: synthetic 1.0 unit valued at Current Value)
    purchase_price <- Average Cost Basis (for cash: Current Value)
    purchase_date  <- export date parsed from filename ('May-28-2026' -> 2026-05-28)
    broker <- 'fidelity'

Position exports do not contain individual lot purchase dates; using the export
date as a snapshot date is a deliberate compromise.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

EXPECTED_HEADER_PREFIX = "Account Number,Account Name,Symbol"
APP_COLS = ["ticker", "quantity", "purchase_price", "purchase_date", "broker", "account"]
_DATE_RE = re.compile(r"([A-Za-z]{3})-(\d{1,2})-(\d{4})")


def _parse_export_date_from_name(path: Path) -> date | None:
    m = _DATE_RE.search(path.name)
    if not m:
        return None
    mon, day, year = m.groups()
    try:
        return pd.to_datetime(f"{year}-{mon}-{day}", format="%Y-%b-%d").date()
    except ValueError:
        return None


def _money(s) -> float:
    if pd.isna(s) or s == "":
        return float("nan")
    return float(str(s).replace("$", "").replace(",", "").replace("+", ""))


def _read_positions(path: Path) -> pd.DataFrame:
    """Read just the tabular section, ignoring the trailing disclaimer text."""
    rows: list[str] = []
    with path.open(encoding="utf-8-sig") as fh:
        for line in fh:
            if not rows:
                if line.startswith(EXPECTED_HEADER_PREFIX):
                    rows.append(line)
                continue
            if line.strip() == "":
                break
            rows.append(line)
    if not rows:
        raise ValueError(f"{path}: header row not found — is this a Fidelity Positions export?")
    from io import StringIO
    return pd.read_csv(StringIO("".join(rows)), index_col=False)


def _normalize(df: pd.DataFrame, export_date: date) -> pd.DataFrame:
    out_rows: list[dict] = []
    for _, r in df.iterrows():
        sym = str(r.get("Symbol", "")).strip()
        if not sym or sym.lower() == "nan":
            continue
        acct = str(r.get("Account Number", "")).strip()
        is_cash = sym.endswith("**")
        if is_cash:
            current_value = _money(r.get("Current Value"))
            if pd.isna(current_value) or current_value == 0:
                continue
            # Cash sweeps trade at $1.00. Encode quantity = dollar amount so
            # cost_basis (qty * price) and current_value (qty * $1) both equal
            # the dollar holding — i.e. P&L is always zero.
            out_rows.append(
                {
                    "ticker": sym,
                    "quantity": round(current_value, 2),
                    "purchase_price": 1.0,
                    "purchase_date": export_date.isoformat(),
                    "broker": "fidelity",
                    "account": acct,
                }
            )
            continue

        qty = r.get("Quantity")
        avg = _money(r.get("Average Cost Basis"))
        if pd.isna(qty) or pd.isna(avg):
            continue
        out_rows.append(
            {
                "ticker": sym.upper(),
                "quantity": float(qty),
                "purchase_price": round(avg, 4),
                "purchase_date": export_date.isoformat(),
                "broker": "fidelity",
                "account": acct,
            }
        )
    return pd.DataFrame(out_rows, columns=APP_COLS)


def import_paths(paths: list[Path], fallback_export_date: date | None = None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for p in paths:
        export_date = _parse_export_date_from_name(p) or fallback_export_date or date.today()
        raw = _read_positions(p)
        frames.append(_normalize(raw, export_date))
    if not frames:
        return pd.DataFrame(columns=APP_COLS)
    return pd.concat(frames, ignore_index=True)


# ── Accounts_History (transaction-level) importer ──────────────────────────────

HISTORY_HEADER_PREFIX = "Run Date,Account,Account Number,Action,Symbol"
HISTORY_COLS = ["ticker", "quantity", "purchase_price", "purchase_date", "broker",
                "account", "action", "row_type", "source_file"]


def _read_history(path: Path) -> pd.DataFrame:
    """Read the tabular section of an Accounts_History export.

    These files have a short blank preamble, the header row, the data rows,
    then a blank line followed by a legal disclaimer that we must not parse.
    """
    from io import StringIO
    rows: list[str] = []
    with path.open(encoding="utf-8-sig") as fh:
        for line in fh:
            if not rows:
                if line.startswith(HISTORY_HEADER_PREFIX):
                    rows.append(line)
                continue
            if line.strip() == "":
                break
            rows.append(line)
    if not rows:
        raise ValueError(f"{path}: header row not found — is this an Accounts_History export?")
    return pd.read_csv(StringIO("".join(rows)), dtype=str, keep_default_na=False)


def _classify_history_action(action_text: str) -> tuple[str | None, str]:
    """Map a Fidelity Action string to (side, row_type).

    side is 'Buy'/'Sell'/None (None = skip this row). row_type tags the kind of
    event so downstream views can treat cash purchases, DRIPs and transfers
    differently (e.g. transfers are real share moves but not 'invested cash').
    """
    a = action_text.upper()
    if "YOU BOUGHT" in a:
        return "Buy", "trade"
    if "YOU SOLD" in a:
        return "Sell", "trade"
    if "TRANSFERRED FROM" in a:
        return "Buy", "transfer"      # shares received into this account
    if "TRANSFERRED TO" in a:
        return "Sell", "transfer"     # shares sent out of this account
    if a.startswith("DISTRIBUTION"):
        return "Buy", "distribution"  # shares distributed in
    if a.startswith("REINVESTMENT"):
        return "Buy", "drip"          # dividend reinvested into the security
    # DIVIDEND RECEIVED / INTEREST EARNED / Electronic Funds / etc. -> cash, skip
    return None, ""


def parse_history(path: Path) -> tuple[pd.DataFrame, dict[str, int], dict[str, int]]:
    """Parse an Accounts_History CSV into Buy/Sell transaction rows.

    Returns (frame, accounts_seen, skipped_by_reason). Cash-only rows (dividends,
    interest, cash sweeps) and rows without a real security symbol are skipped.
    """
    raw = _read_history(path)
    expected = {"Run Date", "Account Number", "Action", "Symbol", "Quantity", "Price ($)"}
    missing = expected - set(raw.columns)
    if missing:
        raise ValueError(f"{path}: missing columns: {missing}")

    out_rows: list[dict] = []
    accounts: dict[str, int] = {}
    skipped: dict[str, int] = {}
    for _, r in raw.iterrows():
        side, row_type = _classify_history_action(str(r.get("Action", "")))
        sym = str(r.get("Symbol", "")).strip().upper()
        # A real security has an alphabetic ticker; cash sweeps use a numeric id.
        if not sym or sym.isdigit():
            skipped["cash/non-security"] = skipped.get("cash/non-security", 0) + 1
            continue
        if side is None:
            skipped["non-trade action"] = skipped.get("non-trade action", 0) + 1
            continue
        qty = _money(r.get("Quantity"))
        if pd.isna(qty) or qty == 0:
            skipped["zero/blank quantity"] = skipped.get("zero/blank quantity", 0) + 1
            continue
        d = _parse_history_date(r.get("Run Date"))
        if d is None:
            skipped["bad date"] = skipped.get("bad date", 0) + 1
            continue
        price = _money(r.get("Price ($)"))
        amount = _money(r.get("Amount ($)"))
        if pd.isna(price) or price == 0:
            # RSU vests / transfers can lack a unit price — derive from amount.
            price = (abs(amount) / abs(qty)) if (not pd.isna(amount) and qty) else 0.0
        acct = str(r.get("Account Number", "")).strip()
        accounts[acct] = accounts.get(acct, 0) + 1
        out_rows.append({
            "ticker": sym,
            "quantity": round(abs(qty) if side == "Buy" else -abs(qty), 6),
            "purchase_price": round(price, 4),
            "purchase_date": d.isoformat(),
            "broker": "fidelity",
            "account": acct,
            "action": side,
            "row_type": row_type,
            "source_file": path.name,
        })
    return pd.DataFrame(out_rows, columns=HISTORY_COLS), accounts, skipped


def _parse_history_date(s) -> date | None:
    if s is None or pd.isna(s) or str(s).strip() == "":
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return pd.to_datetime(str(s).strip(), format=fmt).date()
        except ValueError:
            continue
    return None


def import_to_tag(app_root: Path, source: Path, tag: str) -> Path:
    """Convert one file or all CSVs in a directory into data/transactions/<tag>.csv."""
    source = Path(source)
    if source.is_dir():
        files = sorted(source.glob("*.csv"))
    else:
        files = [source]
    if not files:
        raise FileNotFoundError(f"No CSV files at {source}")
    df = import_paths(files)
    if df.empty:
        raise ValueError(f"No usable rows found in {[str(f) for f in files]}")
    dest = app_root / "data" / "transactions" / f"{tag}.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)
    return dest
