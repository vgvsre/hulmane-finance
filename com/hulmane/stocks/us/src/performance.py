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
        # 1e-4, matching the single-stock view's "fully closed" cutoff: a fully
        # sold position can leave a tiny rounding remainder (e.g. SHOP nets to
        # -3.7e-5 sh after a buy + 10:1 split + full sell). A sliver that small
        # but negative yields a negative current value → total return < -100% →
        # a phantom -100%/yr rank. Drop these as closed instead.
        if abs(net_qty) < 1e-4 or invested <= 0:
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


# Index proxies used to benchmark the whole portfolio over time.
BENCHMARKS = {"S&P 500": "VOO", "Nasdaq 100": "QQQ"}
PORTFOLIO_LABEL = "My portfolio"
INVESTED_LABEL = "Net invested"


# Empty long-form shape shared by the comparison builders below.
_EMPTY_LONG = pd.DataFrame(columns=["date", "series", "value"])


def _priced_txns(transactions: pd.DataFrame, close_df: pd.DataFrame) -> pd.DataFrame:
    """Transactions limited to tickers we have a price series for, with a
    cost_basis column and a datetime purchase_date guaranteed."""
    df = transactions.copy()
    if "cost_basis" not in df.columns:
        df["cost_basis"] = df["quantity"] * df["purchase_price"]
    if not pd.api.types.is_datetime64_any_dtype(df["purchase_date"]):
        df["purchase_date"] = pd.to_datetime(df["purchase_date"])
    return df[df["ticker"].isin(close_df.columns)]


def _cum_asof(per_date: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    """Cumulative running total of dated amounts, as of each trading day in idx."""
    s = per_date.groupby(level=0).sum().sort_index().cumsum()
    return s.reindex(idx, method="ffill").fillna(0.0)


def _invest_value(price: pd.Series, dated_cash: pd.Series,
                  idx: pd.DatetimeIndex) -> pd.Series:
    """Value over time of investing each dated dollar amount into one price series.

    Each cash flow buys ``cash / close(on-or-before that day)`` shares; value is
    cumulative shares × close. Crucially this is **scale-robust**: because the buy
    price and the valuation price come from the same series, any constant error in
    that series' level (e.g. a ticker whose history got back-adjusted for reverse
    splits to ~3000× its real price) cancels in the ratio, and split adjustments
    are handled by the adjusted price rather than by counting split shares.
    """
    buy_px = price.reindex(dated_cash.index, method="ffill")
    shares = (dated_cash / buy_px).replace([float("inf"), float("-inf")], float("nan")).dropna()
    cum = shares.groupby(level=0).sum().sort_index().cumsum()
    return cum.reindex(idx, method="ffill").fillna(0.0) * price


def _portfolio_value(df: pd.DataFrame, prices: pd.DataFrame,
                     idx: pd.DatetimeIndex) -> pd.Series:
    """Daily market value of the holdings, each lot valued by its own ticker's
    return on the dollars invested (scale-robust; see ``_invest_value``)."""
    port = pd.Series(0.0, index=idx)
    for tkr, g in df.groupby("ticker"):
        port = port.add(
            _invest_value(prices[tkr], g.set_index("purchase_date")["cost_basis"], idx),
            fill_value=0.0)
    return port


def _resample_long(frame: pd.DataFrame, freq: str | None) -> pd.DataFrame:
    """Optionally weekly-resample a wide value frame, then melt to long form."""
    if freq:
        # Each bucket keeps its last value. resample() labels weekly buckets by
        # the (future) week-ending Sunday, so relabel the final bucket to the
        # real last trading day — no future-dated point on the x-axis.
        sampled = frame.resample(freq).last().dropna(how="all")
        sampled = sampled.rename(index={sampled.index[-1]: frame.index[-1]})
        # Anchor the true first observation too (e.g. the rebased base of 100),
        # which the week-end sampling would otherwise skip past.
        if frame.index[0] not in sampled.index:
            sampled.loc[frame.index[0]] = frame.iloc[0]
        frame = sampled.sort_index()
    return (frame.reset_index(names="date")
            .melt(id_vars="date", var_name="series", value_name="value")
            .dropna(subset=["value"]))


def _comparison_window(df: pd.DataFrame, close_df: pd.DataFrame,
                       start: date | None):
    """(idx, prices) for the comparison window, or (None, None) if too short."""
    lo = pd.Timestamp(start) if start is not None else df["purchase_date"].min()
    idx = close_df.index[close_df.index >= lo]
    if len(idx) < 2:
        return None, None
    return idx, close_df.reindex(idx).ffill()


def growth_vs_benchmarks(
    transactions: pd.DataFrame,
    close_df: pd.DataFrame,
    benchmarks: dict[str, str] | None = None,
    start: date | None = None,
    freq: str | None = "W",
) -> pd.DataFrame:
    """Cumulative market value over time: the actual portfolio vs the SAME dated
    cash flows invested in each benchmark index instead (money-weighted).

    The idea (same spirit as ``simulate_lump_vs_dca``): every buy/sell is a dated
    dollar cash flow. The portfolio line is the daily market value of the shares
    actually held; each benchmark line answers "what if I'd put those exact same
    dollars into the index on those exact same days?". All lines therefore share
    one contribution schedule and are directly comparable. ``Net invested`` is the
    running cost basis (cash in minus proceeds out) — the no-growth baseline.

    Only tickers that have price history are counted (both for the portfolio value
    and for the cash flows fed to the benchmarks), so neither side is credited
    money the other can't see. The series is resampled to ``freq`` (weekly by
    default) so a multi-year chart stays light; pass ``freq=None`` for daily.
    Long-form output: columns ``date``, ``series``, ``value`` — empty if there's
    nothing priceable to plot.
    """
    benchmarks = benchmarks or BENCHMARKS
    if transactions.empty or close_df.empty:
        return _EMPTY_LONG.copy()
    df = _priced_txns(transactions, close_df)
    if df.empty:
        return _EMPTY_LONG.copy()
    idx, prices = _comparison_window(df, close_df, start)
    if idx is None:
        return _EMPTY_LONG.copy()

    out = {PORTFOLIO_LABEL: _portfolio_value(df, prices, idx)}

    # ── Net invested (cost basis still at work): the no-growth baseline. ──────
    cash = df.set_index("purchase_date")["cost_basis"]
    out[INVESTED_LABEL] = _cum_asof(cash, idx)

    # ── Each benchmark fed the identical dated cash flows. ────────────────────
    for name, sym in benchmarks.items():
        if sym in prices.columns:
            out[name] = _invest_value(prices[sym], cash, idx)

    return _resample_long(pd.DataFrame(out, index=idx), freq)


def rebased_growth(
    transactions: pd.DataFrame,
    close_df: pd.DataFrame,
    benchmarks: dict[str, str] | None = None,
    start: date | None = None,
    base: float = 100.0,
    freq: str | None = "W",
) -> pd.DataFrame:
    """Time-weighted "growth of ``base``" (default $100): portfolio vs each index,
    all starting at ``base`` on the first investment date.

    Unlike ``growth_vs_benchmarks`` (money-weighted dollars), this strips out the
    effect of WHEN cash was added. Each day's return uses the start-of-day flow
    convention ``value / (prior_value + cash_flow) − 1`` chained over time, where
    ``cash_flow`` is the day's REAL money in/out (cost basis). Two reasons that
    convention matters here: (1) putting the new cash in the denominator stops a
    big buy on top of tiny prior capital from manufacturing a fake spike; (2)
    $0-cost stock-split shares carry no cash flow, so the split-day price drop in
    the unadjusted history is cancelled by the matching share increase (≈0% that
    day) instead of looking like a crash. Benchmarks are just their price rebased
    to ``base`` at the same start — a fair "did my picks beat the index per dollar".
    Long-form output: ``date``, ``series``, ``value`` (index level, not dollars).
    """
    benchmarks = benchmarks or BENCHMARKS
    if transactions.empty or close_df.empty:
        return _EMPTY_LONG.copy()
    df = _priced_txns(transactions, close_df)
    if df.empty:
        return _EMPTY_LONG.copy()
    idx, prices = _comparison_window(df, close_df, start)
    if idx is None:
        return _EMPTY_LONG.copy()

    port = _portfolio_value(df, prices, idx)
    invested_cum = _cum_asof(df.set_index("purchase_date")["cost_basis"], idx)
    net_flow = invested_cum.diff()
    net_flow.iloc[0] = invested_cum.iloc[0]
    # Start-of-day convention: today's cash sits in the denominator. Flat (0) when
    # there's no capital at work (denominator ~0), e.g. before the first buy.
    denom = port.shift(1) + net_flow
    ret = (port / denom - 1.0).where(denom > 1e-9, 0.0).fillna(0.0)
    out = {PORTFOLIO_LABEL: base * (1.0 + ret).cumprod()}

    for name, sym in benchmarks.items():
        if sym not in prices.columns:
            continue
        bp = prices[sym]
        if pd.isna(bp.iloc[0]) or bp.iloc[0] <= 0:
            continue
        out[name] = base * bp / float(bp.iloc[0])

    return _resample_long(pd.DataFrame(out, index=idx), freq)


def comparison_summary(rebased_long: pd.DataFrame, base: float = 100.0,
                       benchmark: str = "S&P 500") -> pd.DataFrame:
    """Per-series total & annualized (CAGR) return from a ``rebased_growth`` frame.

    Columns: ``series``, ``total_return_pct``, ``annualized_pct``, ``alpha_pp``
    (annualized return minus ``benchmark``'s, in percentage points; NaN for the
    benchmark row). Ordered portfolio first, then by annualized return.
    """
    if rebased_long.empty:
        return pd.DataFrame(columns=["series", "total_return_pct",
                                     "annualized_pct", "alpha_pp"])
    span_days = (rebased_long["date"].max() - rebased_long["date"].min()).days
    years = max(span_days / 365.25, 1e-9)
    finals = rebased_long.sort_values("date").groupby("series")["value"].last()

    rows = []
    for series, final in finals.items():
        total = final / base - 1.0
        ann = (final / base) ** (1.0 / years) - 1.0
        rows.append({"series": series,
                     "total_return_pct": round(total * 100.0, 1),
                     "annualized_pct": round(ann * 100.0, 1)})
    out = pd.DataFrame(rows)
    bench_ann = out.loc[out["series"] == benchmark, "annualized_pct"]
    base_ann = float(bench_ann.iloc[0]) if not bench_ann.empty else float("nan")
    out["alpha_pp"] = (out["annualized_pct"] - base_ann).round(1)
    out.loc[out["series"] == benchmark, "alpha_pp"] = float("nan")
    # Portfolio pinned first, then best annualized return downward.
    out["_rank"] = out["series"].map(lambda s: (0 if s == PORTFOLIO_LABEL else 1))
    out = (out.sort_values(["_rank", "annualized_pct"], ascending=[True, False])
           .drop(columns="_rank").reset_index(drop=True))
    return out


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
