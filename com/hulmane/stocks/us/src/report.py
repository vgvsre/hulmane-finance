"""Per-tag P&L reports.

Reports are generated per tag so that a $10K invested in jan26 is evaluated
on its own — not commingled with a later may26 buy of the same ticker.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from . import portfolio, pricing


def holdings_base(df: pd.DataFrame) -> pd.DataFrame:
    """Pick the right rows for current-holdings math, avoiding double counting.

    Some accounts are represented BOTH by a position snapshot (e.g. Fidelity
    Portfolio Positions, dated the export day) and by transaction history. For
    those accounts the snapshot is the source of truth for what is held now, so
    we drop the account's movement rows (trades/transfers/DRIPs) here. Accounts
    that only have transaction history keep those rows, and their net quantity
    is the holding — exactly like Robinhood/E*TRADE.
    """
    if df.empty or "row_type" not in df.columns:
        return df
    if "account" not in df.columns:
        return df
    snapshot_accounts = set(df.loc[df["row_type"] == "position", "account"].unique())
    if not snapshot_accounts:
        return df
    keep = (df["row_type"] == "position") | (~df["account"].isin(snapshot_accounts))
    return df[keep]



def reports_dir(app_root: Path) -> Path:
    d = app_root / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _enrich_with_prices(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.assign(current_price=[], current_value=[], pnl=[], pnl_pct=[])
    quotes = pricing.get_quotes(df["ticker"].unique().tolist())
    df = df.copy()
    df["current_price"] = df["ticker"].map(lambda t: quotes[t].price)
    df["current_value"] = df["quantity"] * df["current_price"]
    df["pnl"] = df["current_value"] - df["cost_basis"]
    df["pnl_pct"] = (df["pnl"] / df["cost_basis"]) * 100.0
    return df


def tag_report(app_root: Path, tag: str) -> pd.DataFrame:
    df = portfolio.load_tag(app_root, tag)
    return _enrich_with_prices(df)


def tag_holdings_offline(app_root: Path, tag: str) -> pd.DataFrame:
    """Per-ticker rollup with NO network calls — returns immediately.

    Columns: ticker, quantity, invested, avg_cost, current_price (NaN),
    current_value (NaN), pnl (NaN), pnl_pct (NaN). Use this for the first
    paint, then call enrich_with_prices() to fill in the live columns.
    """
    df = portfolio.load_tag(app_root, tag)
    df = holdings_base(df)
    if df.empty:
        return pd.DataFrame(
            columns=["ticker", "quantity", "invested", "avg_cost",
                     "current_price", "current_value", "pnl", "pnl_pct"]
        )
    grouped = (
        df.groupby("ticker", as_index=False)
        .agg(quantity=("quantity", "sum"), invested=("cost_basis", "sum"))
    )
    grouped = grouped[grouped["quantity"].abs() > 1e-9].copy()
    grouped["avg_cost"] = grouped.apply(
        lambda r: (r["invested"] / r["quantity"]) if r["quantity"] else 0.0, axis=1
    )
    nan = float("nan")
    grouped["current_price"] = nan
    grouped["current_value"] = nan
    grouped["pnl"] = nan
    grouped["pnl_pct"] = nan
    return grouped.sort_values("invested", ascending=False, kind="stable").reset_index(drop=True)


def enrich_with_prices(
    holdings: pd.DataFrame,
    quotes: dict[str, "pricing.Quote"] | None = None,
) -> pd.DataFrame:
    """Take a tag_holdings_offline() frame and fill in the price-derived columns.

    Pass ``quotes`` to use a pre-fetched dict (e.g. from the disk cache or a
    deliberate live fetch). When omitted, this hits the network synchronously.
    """
    if holdings.empty:
        return holdings
    if quotes is None:
        quotes = pricing.get_quotes(holdings["ticker"].tolist())
    out = holdings.copy()
    out["current_price"] = out["ticker"].map(lambda t: quotes[t].price if t in quotes else float("nan"))
    out["price_fetched_at"] = out["ticker"].map(
        lambda t: quotes[t].fetched_at if t in quotes else None
    )
    out["current_value"] = out["quantity"] * out["current_price"]
    out["pnl"] = out["current_value"] - out["invested"]
    out["pnl_pct"] = out.apply(
        lambda r: (r["pnl"] / r["invested"] * 100.0) if r["invested"] else 0.0, axis=1
    )
    return out


def tag_holdings(app_root: Path, tag: str) -> pd.DataFrame:
    """Per-ticker rollup of a tag, with live prices and P&L.

    For transaction-level tags (e.g. Robinhood) this collapses many Buy/Sell
    rows into one row per ticker. For position-level tags (e.g. Fidelity) it
    just sums same-ticker rows. P&L is computed on the netted cost basis so
    realized + unrealized are folded together.
    """
    return enrich_with_prices(tag_holdings_offline(app_root, tag))


# ── Global (cross-tag) helpers ────────────────────────────────────────────────

GLOBAL_HOLDING_COLS = [
    "ticker", "quantity", "invested", "avg_cost",
    "n_accounts", "n_brokers", "n_tags",
    "first_buy", "last_buy",
    "current_price", "price_fetched_at",
    "current_value", "pnl", "pnl_pct",
]


def global_holdings_offline(
    app_root: Path,
    transactions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Per-ticker rollup across every tag/account/broker. No network.

    Pass ``transactions`` to roll up a pre-filtered slice (e.g. date-windowed).
    Otherwise loads everything from disk.
    """
    df = transactions if transactions is not None else portfolio.load_all(app_root)
    df = holdings_base(df)
    if df.empty:
        return pd.DataFrame(columns=GLOBAL_HOLDING_COLS)
    if "cost_basis" not in df.columns:
        df = df.copy()
        df["cost_basis"] = df["quantity"] * df["purchase_price"]

    agg = (
        df.groupby("ticker", as_index=False)
        .agg(
            quantity=("quantity", "sum"),
            invested=("cost_basis", "sum"),
            n_accounts=("account", "nunique"),
            n_brokers=("broker", "nunique"),
            n_tags=("tag", "nunique"),
            first_buy=("purchase_date", "min"),
            last_buy=("purchase_date", "max"),
        )
    )
    agg = agg[agg["quantity"].abs() > 1e-9].copy()
    agg["avg_cost"] = agg.apply(
        lambda r: (r["invested"] / r["quantity"]) if r["quantity"] else 0.0, axis=1
    )
    nan = float("nan")
    agg["current_price"] = nan
    agg["price_fetched_at"] = None
    agg["current_value"] = nan
    agg["pnl"] = nan
    agg["pnl_pct"] = nan
    return agg[GLOBAL_HOLDING_COLS].sort_values(
        "invested", ascending=False, kind="stable"
    ).reset_index(drop=True)


def global_holdings(
    app_root: Path,
    quotes: dict[str, "pricing.Quote"] | None = None,
    transactions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    return enrich_with_prices(global_holdings_offline(app_root, transactions=transactions),
                              quotes=quotes)


def monthly_activity(transactions: pd.DataFrame) -> pd.DataFrame:
    """Aggregate Buy-only invested by (year, month) for a heatmap.

    Sells are ignored so the heat captures *purchase activity* rather than
    net flow. Position-snapshot rows (e.g. Fidelity exports, all stamped with
    the export date) are excluded — they are not real purchases and would
    otherwise pile a whole portfolio's cost basis onto the export month.
    """
    if transactions.empty:
        return pd.DataFrame(columns=["year", "month", "invested", "n_trades"])
    df = transactions.copy()
    if "row_type" in df.columns:
        # Keep only real purchases. Exclude position snapshots (dated the export
        # day), share transfers, and corporate-action distributions (e.g. stock
        # splits) — they move/create shares but are not invested cash.
        df = df[~df["row_type"].isin(["position", "transfer", "distribution"])]
    if not pd.api.types.is_datetime64_any_dtype(df["purchase_date"]):
        df["purchase_date"] = pd.to_datetime(df["purchase_date"])
    if "cost_basis" not in df.columns:
        df["cost_basis"] = df["quantity"] * df["purchase_price"]
    buys = df[df["quantity"] > 0].copy()
    if buys.empty:
        return pd.DataFrame(columns=["year", "month", "invested", "n_trades"])
    buys["year"] = buys["purchase_date"].dt.year
    buys["month"] = buys["purchase_date"].dt.month
    out = (
        buys.groupby(["year", "month"], as_index=False)
        .agg(invested=("cost_basis", "sum"), n_trades=("ticker", "size"))
    )
    return out


def all_tags_summary(app_root: Path) -> pd.DataFrame:
    """One row per tag: invested, current value, P&L, %."""
    rows = []
    for tag in portfolio.list_tags(app_root):
        df = tag_report(app_root, tag)
        invested = df["cost_basis"].sum()
        current = df["current_value"].sum()
        pnl = current - invested
        pct = (pnl / invested * 100.0) if invested else 0.0
        rows.append(
            {
                "tag": tag,
                "positions": len(df),
                "invested": round(invested, 2),
                "current_value": round(current, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pct, 2),
            }
        )
    return pd.DataFrame(rows)


def write_tag_report(app_root: Path, tag: str) -> Path:
    df = tag_report(app_root, tag)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = reports_dir(app_root) / f"{tag}_{ts}.csv"
    df.to_csv(out, index=False)
    return out


def write_summary_report(app_root: Path) -> Path:
    df = all_tags_summary(app_root)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = reports_dir(app_root) / f"summary_{ts}.csv"
    df.to_csv(out, index=False)
    return out
