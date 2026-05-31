"""Tagged portfolio loader.

Each CSV in data/transactions/ represents one tag (cohort).
Filename stem = tag name. Example: data/transactions/jan26.csv has tag 'jan26'.

Required columns:
    ticker, quantity, purchase_price, purchase_date, broker

Optional columns (preserved if present):
    account, action, source_file  — broker importers add these for traceability

Tags are NEVER merged for cost-basis purposes — a buy of AAPL in jan26 stays
distinct from a buy of AAPL in may26 so per-cohort returns are visible.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

REQUIRED_COLS = ["ticker", "quantity", "purchase_price", "purchase_date", "broker"]
OPTIONAL_COLS = ["account", "action", "source_file"]
LT_DAYS = 365  # IRS long-term threshold: held > 1 year


def formated_dir(app_root: Path) -> Path:
    """Where the pipeline writes formatted, extracted data (one CSV per tag).

    This is the app's single source of truth at read time. It is rebuilt from
    data/source on each startup, but is self-sufficient: if data/source is
    deleted, every reader (CLI + dashboard) still works off these files.
    """
    return app_root / "data" / "formated"


def transactions_dir(app_root: Path) -> Path:
    """Backwards-compatible alias for :func:`formated_dir`."""
    return formated_dir(app_root)


def list_tags(app_root: Path) -> list[str]:
    d = transactions_dir(app_root)
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.csv"))


def load_tag(app_root: Path, tag: str) -> pd.DataFrame:
    path = transactions_dir(app_root) / f"{tag}.csv"
    if not path.exists():
        raise FileNotFoundError(f"No transactions file for tag '{tag}': {path}")
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name} missing columns: {missing}")
    df["ticker"] = df["ticker"].str.upper().str.strip()
    df["quantity"] = pd.to_numeric(df["quantity"])
    df["purchase_price"] = pd.to_numeric(df["purchase_price"])
    df["purchase_date"] = pd.to_datetime(df["purchase_date"])
    df["broker"] = df["broker"].astype(str).str.strip()
    df["tag"] = tag
    df["cost_basis"] = df["quantity"] * df["purchase_price"]
    # Derive 'action' from sign of quantity if it isn't already there.
    if "action" not in df.columns:
        df["action"] = df["quantity"].apply(lambda q: "Buy" if q >= 0 else "Sell")
    if "account" not in df.columns:
        df["account"] = ""
    if "source_file" not in df.columns:
        df["source_file"] = ""
    return df


def load_all(app_root: Path) -> pd.DataFrame:
    tags = list_tags(app_root)
    if not tags:
        return pd.DataFrame(columns=REQUIRED_COLS + ["tag", "cost_basis"])
    return pd.concat([load_tag(app_root, t) for t in tags], ignore_index=True)


def upload(app_root: Path, src_csv: Path, tag: str) -> Path:
    """Copy a user-supplied CSV into data/transactions/<tag>.csv after validating."""
    src_csv = Path(src_csv)
    df = pd.read_csv(src_csv)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Uploaded CSV missing columns: {missing}")
    dest = transactions_dir(app_root) / f"{tag}.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)
    return dest


def lots(app_root: Path, ticker: str, tag: str | None = None) -> pd.DataFrame:
    """Return every individual transaction row for a ticker, sorted by date.

    If ``tag`` is given, only rows from that tag's CSV are returned. Otherwise
    rows from every tag are concatenated. Useful for a per-stock 'when did I
    buy it / at what price' drill-down.
    """
    df = load_tag(app_root, tag) if tag else load_all(app_root)
    if df.empty:
        return df
    ticker = ticker.upper().strip()
    out = df[df["ticker"] == ticker].copy()
    out = out.sort_values("purchase_date", kind="stable").reset_index(drop=True)
    return out


def lots_global(app_root: Path, ticker: str) -> pd.DataFrame:
    """Cross-tag, cross-broker, cross-account lookup of every row for a ticker.

    Decorates the result with ``tax_term`` (long_term/short_term as of today).
    """
    df = lots(app_root, ticker, tag=None)
    if df.empty:
        return df
    return with_tax_term(df)


def with_tax_term(df: pd.DataFrame, as_of: date | None = None) -> pd.DataFrame:
    """Add a ``tax_term`` column (long_term/short_term) based on holding age.

    Uses the IRS rule: long-term if held > 365 days from ``purchase_date`` to
    ``as_of`` (default today). For sells (negative quantity) this represents
    the term the *position* would have if still held — informational only.
    """
    if df.empty or "purchase_date" not in df.columns:
        return df
    if as_of is None:
        as_of = date.today()
    out = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(out["purchase_date"]):
        out["purchase_date"] = pd.to_datetime(out["purchase_date"])
    age_days = (pd.Timestamp(as_of) - out["purchase_date"]).dt.days
    out["age_days"] = age_days
    out["tax_term"] = age_days.apply(lambda d: "long_term" if d > LT_DAYS else "short_term")
    return out


def all_tickers(app_root: Path) -> list[str]:
    """Sorted list of every distinct ticker across every tag."""
    df = load_all(app_root)
    if df.empty:
        return []
    return sorted(df["ticker"].unique().tolist())
