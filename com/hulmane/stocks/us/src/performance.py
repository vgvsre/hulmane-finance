"""Performance analytics for the Stocks Performance page.

Three things live here, all pure (no Streamlit, no network):

1. ``scorecard`` — per-stock total/annualized return on the user's actual
   position, bucketed into Good / Average / Poor by annualized return.
2. ``yearly_return_matrix`` — each stock's calendar-year price return, derived
   from the daily close history (data/history/close_prices.csv).
3. ``simulate_lump_vs_dca`` — invest-it-all-at-once vs invest-on-the-Nth-of-
   every-month, to answer "would monthly buying have beaten a lump sum?".

Annualized return is the cost-weighted approximation
    (current_value / invested) ** (1 / years) - 1
where ``years`` runs from the cost-weighted average purchase date to today. It
is a simplified money-weighted return — good enough to rank picks and judge
entry quality, not a full XIRR.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from .pricing import CASH_SYMBOLS

# Annualized-return thresholds (per user.txt).
GOOD_MIN = 0.20      # >= +20%/yr   -> "Good"
AVERAGE_MIN = 0.0    # 0%..20%/yr   -> "Average"; < 0%/yr -> "Poor"

# Annualizing a holding-period return only makes sense once it's run for a
# while. Below this, (1+r)**(1/years) extrapolates a few weeks into a wild
# yearly rate, so we report total return only and bucket it as "New".
MIN_ANNUALIZE_YEARS = 1.0

CATEGORY_GOOD = "Good"
CATEGORY_AVERAGE = "Average"
CATEGORY_POOR = "Poor"
CATEGORY_NEW = "New (<1yr)"
CATEGORY_NA = "n/a"

CLOSE_HISTORY_REL = Path("data") / "history" / "close_prices.csv"


def close_history_path(app_root: Path) -> Path:
    return app_root / CLOSE_HISTORY_REL


def load_close_history(app_root: Path) -> pd.DataFrame:
    """Daily close prices: DatetimeIndex rows, one column per ticker.

    Empty frame if history.py hasn't been run yet. Columns match portfolio
    tickers (e.g. 'BRK.B'); all-NaN columns (delisted) are kept as-is.
    """
    p = close_history_path(app_root)
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, parse_dates=["Date"], index_col="Date")
    return df.sort_index()


def categorize(annualized: float) -> str:
    if annualized is None or pd.isna(annualized):
        return CATEGORY_NA
    if annualized >= GOOD_MIN:
        return CATEGORY_GOOD
    if annualized >= AVERAGE_MIN:
        return CATEGORY_AVERAGE
    return CATEGORY_POOR


def annualize(total_return: float, years: float) -> float:
    """Annualized return from a holding-period total return and its length."""
    if years is None or years <= 0 or pd.isna(total_return):
        return float("nan")
    base = 1.0 + total_return
    if base <= 0:  # wiped out / >100% loss — annualizing is meaningless
        return -1.0
    return base ** (1.0 / years) - 1.0


SCORECARD_COLS = [
    "ticker", "quantity", "invested", "avg_cost", "current_price",
    "current_value", "pnl", "total_return_pct", "holding_years",
    "annualized_pct", "category", "first_buy", "weighted_buy_date",
]


def scorecard(
    transactions: pd.DataFrame,
    prices: dict[str, float],
    as_of: date | None = None,
) -> pd.DataFrame:
    """One row per currently-held ticker, ranked best→worst by annualized return.

    ``prices`` maps ticker -> current price (NaN allowed). Tickers with no net
    holding, or with non-positive invested cost (e.g. $0-basis RSU lots), are
    dropped from the ranking since a return cannot be defined for them.
    """
    if transactions.empty:
        return pd.DataFrame(columns=SCORECARD_COLS)
    as_of = as_of or date.today()
    df = transactions.copy()
    if "cost_basis" not in df.columns:
        df["cost_basis"] = df["quantity"] * df["purchase_price"]
    if not pd.api.types.is_datetime64_any_dtype(df["purchase_date"]):
        df["purchase_date"] = pd.to_datetime(df["purchase_date"])

    rows: list[dict] = []
    for ticker, g in df.groupby("ticker"):
        if str(ticker).rstrip("*").upper() in CASH_SYMBOLS:
            continue  # cash sweeps / money-market — not a performance pick
        net_qty = float(g["quantity"].sum())
        invested = float(g["cost_basis"].sum())
        if abs(net_qty) < 1e-9 or invested <= 0:
            continue
        buys = g[g["quantity"] > 0]
        weight = buys["cost_basis"].where(buys["cost_basis"] > 0, other=0.0)
        if float(weight.sum()) > 0:
            ordinals = buys["purchase_date"].map(lambda d: d.toordinal())
            w_ordinal = float((ordinals * weight).sum() / weight.sum())
            weighted_buy = date.fromordinal(round(w_ordinal))
        else:
            weighted_buy = buys["purchase_date"].min().date() if not buys.empty else as_of
        first_buy = g["purchase_date"].min().date()

        price = float(prices.get(ticker, float("nan")))
        current_value = net_qty * price
        pnl = current_value - invested
        total_return = pnl / invested
        years = max((as_of - weighted_buy).days / 365.25, 0.0)
        if pd.isna(price):
            ann, category = float("nan"), CATEGORY_NA
        elif years < MIN_ANNUALIZE_YEARS:
            # Held too briefly to annualize honestly — report total return only.
            ann, category = float("nan"), CATEGORY_NEW
        else:
            ann = annualize(total_return, years)
            category = categorize(ann)
        rows.append({
            "ticker": ticker,
            "quantity": round(net_qty, 4),
            "invested": round(invested, 2),
            "avg_cost": round(invested / net_qty, 4) if net_qty else float("nan"),
            "current_price": round(price, 4) if pd.notna(price) else float("nan"),
            "current_value": round(current_value, 2) if pd.notna(current_value) else float("nan"),
            "pnl": round(pnl, 2) if pd.notna(pnl) else float("nan"),
            "total_return_pct": round(total_return * 100.0, 2) if pd.notna(total_return) else float("nan"),
            "holding_years": round(years, 2),
            "annualized_pct": round(ann * 100.0, 2) if pd.notna(ann) else float("nan"),
            "category": category,
            "first_buy": first_buy.isoformat(),
            "weighted_buy_date": weighted_buy.isoformat(),
        })

    out = pd.DataFrame(rows, columns=SCORECARD_COLS)
    if out.empty:
        return out
    return out.sort_values("annualized_pct", ascending=False, na_position="last").reset_index(drop=True)


def category_summary(scored: pd.DataFrame) -> pd.DataFrame:
    """Count + invested + current value per category, in Good→Poor order."""
    order = [CATEGORY_GOOD, CATEGORY_AVERAGE, CATEGORY_POOR, CATEGORY_NEW, CATEGORY_NA]
    if scored.empty:
        return pd.DataFrame(columns=["category", "stocks", "invested", "current_value"])
    g = (scored.groupby("category")
         .agg(stocks=("ticker", "size"),
              invested=("invested", "sum"),
              current_value=("current_value", "sum"))
         .reindex(order).dropna(how="all").reset_index())
    g["stocks"] = g["stocks"].fillna(0).astype(int)
    return g


def price_cagr(close_df: pd.DataFrame, ticker: str,
               start, end=None) -> float:
    """Annualized price return of ``ticker`` between two dates (NaN if no data)."""
    if close_df.empty or ticker not in close_df.columns:
        return float("nan")
    s = close_df[ticker].dropna()
    if s.empty:
        return float("nan")
    s = s[s.index >= pd.Timestamp(start)]
    if end is not None:
        s = s[s.index <= pd.Timestamp(end)]
    if len(s) < 2:
        return float("nan")
    p0, p1 = float(s.iloc[0]), float(s.iloc[-1])
    if p0 <= 0:
        return float("nan")
    years = max((s.index[-1] - s.index[0]).days / 365.25, 1e-9)
    return annualize(p1 / p0 - 1.0, years)


def benchmark_comparison(scored: pd.DataFrame, close_df: pd.DataFrame,
                         benchmark: str = "VOO") -> pd.DataFrame:
    """Add benchmark (S&P 500 proxy) columns so picks can be judged vs the index.

    For each holding, computes the benchmark's annualized price return over the
    SAME window (the holding's weighted buy date → today), the difference
    (``alpha_pp``, in percentage points), and whether the pick beat the market.
    """
    if scored.empty:
        return scored
    out = scored.copy()
    if close_df.empty or benchmark not in close_df.columns:
        out["benchmark_annualized_pct"] = float("nan")
        out["alpha_pp"] = float("nan")
        out["beat_market"] = pd.NA
        return out
    bench = out["weighted_buy_date"].map(
        lambda d: price_cagr(close_df, benchmark, d) * 100.0
    )
    out["benchmark_annualized_pct"] = bench.round(2)
    out["alpha_pp"] = (out["annualized_pct"] - out["benchmark_annualized_pct"]).round(2)
    # Undefined (NA) when there's no annualized return to compare (e.g. holdings
    # under a year) — so they aren't miscounted as having lagged the market.
    out["beat_market"] = out["alpha_pp"].map(lambda a: pd.NA if pd.isna(a) else bool(a > 0))
    return out


def yearly_return_matrix(close_df: pd.DataFrame, tickers: list[str] | None = None) -> pd.DataFrame:
    """Calendar-year price return per ticker (rows=ticker, cols=year, values=%).

    Year return = last close of the year vs last close of the prior year. The
    most recent (incomplete) year is a year-to-date figure. NaN where a ticker
    has no prior-year price (e.g. listed mid-history).
    """
    if close_df.empty:
        return pd.DataFrame()
    cols = [t for t in (tickers or close_df.columns) if t in close_df.columns]
    if not cols:
        return pd.DataFrame()
    year_end = close_df[cols].resample("YE").last()
    pct = year_end.pct_change() * 100.0
    pct.index = pct.index.year
    pct.index.name = "year"
    # Drop the first row (no prior year to compare) and fully-empty rows.
    out = pct.iloc[1:].dropna(how="all")
    return out.T  # rows = ticker, cols = year


@dataclass
class StrategyResult:
    invested: float
    shares: float
    final_value: float
    final_price: float

    @property
    def return_pct(self) -> float:
        return (self.final_value / self.invested - 1.0) * 100.0 if self.invested else float("nan")


@dataclass
class DcaComparison:
    ticker: str
    start: date
    end: date
    monthly_amount: float
    day_of_month: int
    n_buys: int
    lump: StrategyResult
    dca: StrategyResult
    curve: pd.DataFrame  # columns: date, strategy, value

    @property
    def winner(self) -> str:
        if self.dca.final_value > self.lump.final_value:
            return "DCA"
        if self.lump.final_value > self.dca.final_value:
            return "Lump sum"
        return "Tie"


def _buy_dates(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp,
               day_of_month: int) -> list[pd.Timestamp]:
    """First trading day on/after the Nth of each month within [start, end]."""
    months = pd.date_range(start.normalize().replace(day=1), end, freq="MS")
    picks: list[pd.Timestamp] = []
    for m in months:
        try:
            target = m.replace(day=day_of_month)
        except ValueError:
            target = m  # month shorter than day_of_month — fall back to month start
        pos = index.searchsorted(target, side="left")
        if pos < len(index):
            d = index[pos]
            if start <= d <= end and (not picks or d != picks[-1]):
                picks.append(d)
    return picks


def simulate_lump_vs_dca(
    close_df: pd.DataFrame,
    ticker: str,
    monthly_amount: float,
    start: date,
    end: date | None = None,
    day_of_month: int = 9,
) -> DcaComparison | None:
    """Compare investing the whole budget at ``start`` vs ``monthly_amount`` on
    the ``day_of_month`` of every month, both held to ``end``.

    The lump sum equals monthly_amount × number of monthly buys, so both
    strategies deploy the same total capital. Returns None if there's no usable
    price series for the ticker in the window.
    """
    if close_df.empty or ticker not in close_df.columns:
        return None
    series = close_df[ticker].dropna()
    if series.empty:
        return None
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end) if end else series.index.max()
    series = series[(series.index >= start_ts) & (series.index <= end_ts)]
    if len(series) < 2:
        return None

    buys = _buy_dates(series.index, series.index.min(), series.index.max(), day_of_month)
    if not buys:
        return None
    final_price = float(series.iloc[-1])

    # DCA: buy monthly_amount of shares on each buy date.
    dca_shares_each = {d: monthly_amount / float(series.loc[d]) for d in buys}
    dca_total_shares = float(sum(dca_shares_each.values()))
    dca_invested = monthly_amount * len(buys)
    dca = StrategyResult(dca_invested, dca_total_shares,
                         dca_total_shares * final_price, final_price)

    # Lump sum: deploy the same total on the first buy date.
    lump_price = float(series.loc[buys[0]])
    lump_shares = dca_invested / lump_price
    lump = StrategyResult(dca_invested, lump_shares, lump_shares * final_price, final_price)

    # Value-over-time curve for both strategies (cumulative shares × price).
    buy_index = pd.DatetimeIndex(buys)
    cum_shares = pd.Series([dca_shares_each[d] for d in buys], index=buy_index).cumsum()
    held = cum_shares.reindex(series.index, method="ffill").fillna(0.0)
    dca_curve = held * series
    lump_held = pd.Series(0.0, index=series.index)
    lump_held[series.index >= buys[0]] = lump_shares
    lump_curve = lump_held * series
    curve = pd.concat([
        pd.DataFrame({"date": series.index, "value": dca_curve.values, "strategy": "DCA"}),
        pd.DataFrame({"date": series.index, "value": lump_curve.values, "strategy": "Lump sum"}),
    ], ignore_index=True)

    return DcaComparison(
        ticker=ticker, start=series.index.min().date(), end=series.index.max().date(),
        monthly_amount=monthly_amount, day_of_month=day_of_month, n_buys=len(buys),
        lump=lump, dca=dca, curve=curve,
    )
