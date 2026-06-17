"""Streamlit dashboard for Hulmane US Stocks (Venu Robinhood, live snapshot).

Tabs:
    1. Home          — headline metrics, activity heatmap, invested-vs-sold by year,
                       portfolio-vs-market since 2019, holdings, year-by-year returns
    2. Transactions  — full buy/sell ledger with per-transaction tagging + tag report
    3. Single stock  — current position + full transaction history for one ticker

Data:
    Holdings & returns come from data/live/positions.json (Robinhood average cost,
    correct even for transferred-in shares). Activity/transaction views come from
    data/formated/robinhood.csv (real orders + splits). Market prices via yfinance.
    The agent refreshes the snapshot with `python app.py snapshot`.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

APP_ROOT = Path(os.environ.get("HULMANE_US_APP_ROOT", Path(__file__).resolve().parent))
sys.path.insert(0, str(APP_ROOT))

from src import portfolio, pricing, report  # noqa: E402
from src import media as media_mod  # noqa: E402
from src import tags as txn_tags  # noqa: E402
from src import performance as perf  # noqa: E402

st.set_page_config(page_title="Hulmane US Stocks", layout="wide", page_icon="📈")

# ── Visual styling ────────────────────────────────────────────────────────────
PALETTE = ["#7c3aed", "#ec4899", "#f59e0b", "#10b981", "#06b6d4",
           "#3b82f6", "#ef4444", "#84cc16", "#a855f7", "#14b8a6"]
GREEN = "#10b981"
RED = "#ef4444"
BLUE = "#3b82f6"
ORANGE = "#f59e0b"
GRADIENT_START = "#7c3aed"
GRADIENT_END = "#ec4899"

st.markdown(
    f"""
    <style>
      /* Trim Streamlit chrome: Deploy button, top header bar, default padding */
      [data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer {{ display: none !important; }}
      [data-testid="stHeader"] {{ height: 0; background: transparent; }}
      .block-container, [data-testid="stMainBlockContainer"] {{
        padding-top: 1.2rem; padding-bottom: 1rem; padding-left: 2rem; padding-right: 2rem;
      }}
      .hero-title {{
        font-size: 2.4rem; font-weight: 800;
        background: linear-gradient(90deg, {GRADIENT_START} 0%, {GRADIENT_END} 50%, #f59e0b 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        margin-bottom: 0.1em; letter-spacing: -0.02em;
      }}
      .hero-sub {{ color: #64748b; font-size: 0.85rem; margin-top: 0; }}
      [data-testid="stMetric"] {{
        background: linear-gradient(135deg, #faf5ff 0%, #fdf2f8 100%);
        border: 1px solid #e9d5ff; padding: 16px 16px 12px 16px;
        border-radius: 14px; box-shadow: 0 1px 3px rgba(124, 58, 237, 0.08);
      }}
      [data-testid="stMetricLabel"] {{
        color: #6b7280; font-weight: 600; text-transform: uppercase;
        font-size: 0.7rem; letter-spacing: 0.06em;
      }}
      [data-testid="stMetricValue"] {{ color: #1e293b; font-weight: 700; }}
      .stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
      .stTabs [data-baseweb="tab"] {{
        background: #f5f3ff; border-radius: 10px 10px 0 0; padding: 8px 16px; font-weight: 600;
      }}
      .stTabs [aria-selected="true"] {{
        background: linear-gradient(135deg, {GRADIENT_START}, {GRADIENT_END}); color: white !important;
      }}
      h3 {{ border-left: 4px solid {GRADIENT_START}; padding-left: 10px; margin-top: 1.2em; }}
      [data-testid="stSidebar"] {{ background: linear-gradient(180deg, #faf5ff 0%, #fdf2f8 100%); }}
      [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2 {{ color: {GRADIENT_START}; }}
      .stButton > button {{ border-radius: 10px; font-weight: 600; border: none; }}
      .stButton > button[kind="primary"] {{ background: linear-gradient(135deg, {GRADIENT_START}, {GRADIENT_END}); }}
      [class*="st-key-pick_"] button {{ padding: 1px 6px; min-height: 0; font-size: 0.72rem; font-weight: 600; border-radius: 6px; }}
      [data-testid="stDataFrame"] {{ border-radius: 12px; overflow: hidden; }}
      .status-badge {{ display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px;
        border-radius: 999px; font-size: 0.78rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; }}
      .status-badge .dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}
      .status-live {{ background: linear-gradient(135deg, #10b981, #06b6d4); color: white; }}
      .status-live .dot {{ background: white; }}
      .status-cached {{ background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }}
      .status-cached .dot {{ background: #94a3b8; }}
      .status-empty {{ background: #fef3c7; color: #92400e; border: 1px solid #fcd34d; }}
      .status-empty .dot {{ background: #f59e0b; }}
      .stock-header {{ display: flex; align-items: center; gap: 16px; padding: 16px 20px; margin: 8px 0 18px;
        border-radius: 16px; background: linear-gradient(135deg, #faf5ff 0%, #fdf2f8 100%); border: 1px solid #e9d5ff; }}
      .stock-header img {{ width: 64px; height: 64px; border-radius: 14px; background: white; padding: 4px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08); }}
      .stock-header .meta {{ font-size: 0.85rem; color: #6b7280; }}
      .stock-header .ticker {{ font-size: 1.6rem; font-weight: 800; color: #1e293b; }}
      .pill {{ display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 0.74rem; font-weight: 700; margin-right: 6px; }}
      .pill-lt {{ background: #dbeafe; color: #1e40af; }}
      .pill-st {{ background: #fed7aa; color: #9a3412; }}
      .pill-pos {{ background: #d1fae5; color: #065f46; }}
      .pill-neg {{ background: #fee2e2; color: #991b1b; }}
      .filter-row {{ background: #faf5ff; padding: 14px 18px; border-radius: 12px; border: 1px solid #e9d5ff; margin-bottom: 1em; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="hero-title">Hulmane — US Stocks</div>', unsafe_allow_html=True)


# ── Helpers ────────────────────────────────────────────────────────────────────
def _format_age(iso_ts: str | None) -> str:
    if not iso_ts:
        return "never"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        secs = int((datetime.now(timezone.utc) - dt).total_seconds())
        if secs < 60: return f"{secs}s ago"
        if secs < 3600: return f"{secs // 60}m ago"
        if secs < 86400: return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return iso_ts


def _compact_usd(v: float) -> str:
    if v is None or pd.isna(v):
        return ""
    v = float(v)
    if abs(v) >= 1_000_000: return f"${v / 1_000_000:,.1f}M"
    if abs(v) >= 1_000: return f"${v / 1_000:,.1f}K"
    return f"${v:,.0f}"


def _render_status_badge(live: bool, summary: dict) -> None:
    if live:
        html = ('<span class="status-badge status-live"><span class="dot"></span>'
                'Live · prices fetched now</span>')
    elif summary["count"] == 0:
        html = ('<span class="status-badge status-empty"><span class="dot"></span>'
                'No cached prices yet</span>')
    else:
        html = (f'<span class="status-badge status-cached"><span class="dot"></span>'
                f'Cached · {summary["count"]} tickers · newest {_format_age(summary.get("newest"))}</span>')
    st.markdown(html, unsafe_allow_html=True)


@st.cache_data(ttl=120, show_spinner=False)
def _all_transactions() -> pd.DataFrame:
    return portfolio.load_all(APP_ROOT)


@st.cache_data(ttl=120, show_spinner=False)
def _positions() -> pd.DataFrame:
    return portfolio.load_positions(APP_ROOT)


def _quotes_for(tickers: list[str], live: bool) -> dict[str, pricing.Quote]:
    if not tickers:
        return {}
    if live:
        return pricing.get_quotes_live_and_cache(APP_ROOT, tickers)
    return pricing.get_quotes_cached(APP_ROOT, tickers)


@st.cache_data(ttl=21600, show_spinner="Updating price history…")
def _topup_close_history(live: bool, _today: str) -> dict | None:
    if not live:
        return None
    import history
    try:
        return history.sync_close_history(APP_ROOT)
    except Exception as e:
        return {"built": False, "new_days": 0, "new_tickers": [],
                "last_date": None, "reason": f"error: {type(e).__name__}"}


def _apply_filters(df: pd.DataFrame, *, start: date | None, end: date | None,
                   accounts: list[str] | None) -> pd.DataFrame:
    if df.empty:
        return df
    out = df
    if start:
        out = out[out["purchase_date"] >= pd.Timestamp(start)]
    if end:
        out = out[out["purchase_date"] <= pd.Timestamp(end) + pd.Timedelta(days=1)]
    if accounts:
        out = out[out["account"].isin(accounts)]
    return out


def _period_range(label: str, min_d: date, max_d: date, today: date,
                  year: int | None = None, quarter: int | None = None) -> tuple[date, date]:
    if label == "YTD":
        return date(today.year, 1, 1), today
    if label == "QTD":
        q0 = ((today.month - 1) // 3) * 3 + 1
        return date(today.year, q0, 1), today
    if label == "Last 30 days":
        return today - timedelta(days=30), today
    if label == "Last 90 days":
        return today - timedelta(days=90), today
    if label == "Last 12 months":
        return today - timedelta(days=365), today
    if label == "Specific quarter" and year and quarter:
        start = date(year, (quarter - 1) * 3 + 1, 1)
        end = (date(year, 12, 31) if quarter == 4
               else date(year, quarter * 3 + 1, 1) - timedelta(days=1))
        return start, end
    return min_d, max_d


def _live_holdings(accounts: list[str] | None, quotes: dict) -> pd.DataFrame:
    """Per-ticker current holdings from the live snapshot (Robinhood avg cost),
    enriched with live prices. Correct for transferred-in shares."""
    pos = _positions()
    cols = ["ticker", "quantity", "avg_cost", "invested", "n_accounts",
            "current_price", "current_value", "pnl", "pnl_pct"]
    if pos.empty:
        return pd.DataFrame(columns=cols)
    if accounts:
        pos = pos[pos["nickname"].isin(accounts)]
    if pos.empty:
        return pd.DataFrame(columns=cols)
    g = (pos.groupby("ticker", as_index=False)
         .agg(quantity=("quantity", "sum"), invested=("cost_basis", "sum"),
              n_accounts=("nickname", "nunique")))
    g = g[g["quantity"].abs() > 1e-9].copy()
    g["avg_cost"] = g.apply(lambda r: r["invested"] / r["quantity"] if r["quantity"] else 0.0, axis=1)
    g["current_price"] = g["ticker"].map(lambda t: quotes[t].price if t in quotes else float("nan"))
    g["current_value"] = g["quantity"] * g["current_price"]
    g["pnl"] = g["current_value"] - g["invested"]
    g["pnl_pct"] = g.apply(lambda r: (r["pnl"] / r["invested"] * 100.0) if r["invested"] else 0.0, axis=1)
    return g[cols].sort_values("current_value", ascending=False, na_position="last").reset_index(drop=True)


# Gain-on-cost bands for the stock heatmap (return % = current value vs invested).
HEAT_BANDS = [">100%", "50–100%", "30–50%", "0–30%", "Loss", "n/a"]
HEAT_FILL = {">100%": "#166534", "50–100%": "#86efac", "30–50%": "#fde047",
             "0–30%": "#f8fafc", "Loss": "#ef4444", "n/a": "#e5e7eb"}
HEAT_TEXT = {">100%": "white", "50–100%": "#14532d", "30–50%": "#713f12",
             "0–30%": "#334155", "Loss": "white", "n/a": "#6b7280"}


def _heat_band(pct: float) -> str:
    if pd.isna(pct):
        return "n/a"
    if pct < 0:
        return "Loss"
    if pct < 30:
        return "0–30%"
    if pct < 50:
        return "30–50%"
    if pct < 100:
        return "50–100%"
    return ">100%"


HEAT_FIELDS = ["Return %", "Shares", "Current value", "Invested", "P&L"]


def _heat_field(field: str, r) -> str:
    if field == "Return %":
        return f"{r['pnl_pct']:+.0f}%" if pd.notna(r["pnl_pct"]) else "—"
    if field == "Shares":
        return f"{r['quantity']:,.2f} sh"
    if field == "Current value":
        return _compact_usd(r["current_value"])
    if field == "Invested":
        return _compact_usd(r["invested"])
    if field == "P&L":
        return _compact_usd(r["pnl"])
    return ""


def _stock_heatmap(holdings: pd.DataFrame, fields: list[str],
                   per_row: int = 8) -> alt.LayerChart | None:
    """Grid heatmap: one tile per holding, colored by gain on cost (P&L %).
    ``fields`` chooses which metric line(s) print on each tile."""
    if holdings.empty or holdings["pnl_pct"].isna().all():
        return None
    df = holdings.dropna(subset=["pnl_pct"]).copy()
    df = df.sort_values("pnl_pct", ascending=False).reset_index(drop=True)
    df["band"] = df["pnl_pct"].map(_heat_band)
    df["txt"] = df["band"].map(HEAT_TEXT)
    df["metrics_label"] = df.apply(
        lambda r: "\n".join(_heat_field(f, r) for f in fields), axis=1)
    df["row"] = df.index // per_row
    df["col"] = df.index % per_row
    n_rows = int(df["row"].max()) + 1
    tile_h = 30 + 16 * max(1, len(fields) + 1)  # +1 for the ticker line

    base = alt.Chart(df).encode(x=alt.X("col:O", axis=None), y=alt.Y("row:O", axis=None))
    rects = base.mark_rect(stroke="white", strokeWidth=3, cornerRadius=8).encode(
        color=alt.Color("band:N", scale=alt.Scale(domain=HEAT_BANDS, range=[HEAT_FILL[b] for b in HEAT_BANDS]),
                        legend=alt.Legend(orient="bottom", title="Gain on cost")),
        tooltip=[alt.Tooltip("ticker:N", title="Ticker"),
                 alt.Tooltip("quantity:Q", title="Shares", format=",.4f"),
                 alt.Tooltip("invested:Q", title="Invested", format="$,.0f"),
                 alt.Tooltip("current_value:Q", title="Current value", format="$,.0f"),
                 alt.Tooltip("pnl:Q", title="P&L", format="$,.0f"),
                 alt.Tooltip("pnl_pct:Q", title="Return", format="+.1f")],
    )
    tkr = base.mark_text(baseline="bottom", dy=-2, fontWeight="bold", fontSize=13).encode(
        text="ticker:N", color=alt.Color("txt:N", scale=None))
    met = base.mark_text(baseline="top", dy=3, fontSize=10, lineBreak="\n").encode(
        text="metrics_label:N", color=alt.Color("txt:N", scale=None))
    return ((rects + tkr + met).resolve_scale(color="independent")
            .properties(height=max(90, tile_h * n_rows)).configure_view(strokeWidth=0))


def _stock_header(ticker: str) -> None:
    icon_url = media_mod.icon_data_url(APP_ROOT, ticker, size=96)
    cache = pricing.load_cache(APP_ROOT)
    name = cache[ticker]["name"] if ticker in cache and cache[ticker].get("name") else ""
    has_real = media_mod.logo_path(APP_ROOT, ticker) is not None
    badge = "" if has_real else '<span class="pill" style="background:#f3e8ff;color:#9333ea;">auto-icon</span>'
    st.markdown(
        f'<div class="stock-header"><img src="{icon_url}" /><div>'
        f'<div class="ticker">{ticker}</div>'
        f'<div class="meta">{name or "&nbsp;"} {badge}</div></div></div>',
        unsafe_allow_html=True,
    )


# ── Sidebar ─────────────────────────────────────────────────────────────────────
all_tx = _all_transactions()
all_accounts = sorted(all_tx["account"].dropna().unique().tolist()) if not all_tx.empty else []
all_tickers = portfolio.all_tickers(APP_ROOT)
meta = portfolio.refreshed_meta(APP_ROOT)

with st.sidebar:
    st.header("Controls")
    live_mode = st.toggle(
        "Live prices", value=st.session_state.get("live_mode", False), key="live_mode",
        help="ON: fetch from Yahoo Finance + update cache.\nOFF: show last-known cached prices.",
    )
    cache_meta = pricing.cache_summary(APP_ROOT)
    if cache_meta["count"]:
        st.caption(f"Cache: {cache_meta['count']} tickers · newest {_format_age(cache_meta['newest'])}")
    else:
        st.caption("Cache: empty")

    _hist_status = _topup_close_history(live_mode, date.today().isoformat())
    if _hist_status and (_hist_status.get("new_days") or _hist_status.get("built")):
        st.caption(f"History: +{_hist_status['new_days']} day(s) → {_hist_status['last_date']}")
    if st.button("Refresh", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    if meta:
        st.caption(f"**Robinhood data:** {_format_age(meta.get('refreshed_at'))}")
        accts = meta.get("accounts", {})
        st.caption("· " + " · ".join(f"{k} {v}" for k, v in accts.items()))
        st.caption(f"{meta.get('ledger_rows', 0)} ledger rows · {meta.get('positions', 0)} holdings")
    else:
        st.warning("No snapshot yet. Run `python app.py snapshot`.")
    st.caption("Robinhood data is as of the last MCP refresh; prices are live via Yahoo.")

    st.divider()
    with st.expander("Filters", expanded=False):
        flt_accounts = st.multiselect("Accounts", all_accounts, default=[])
        st.caption("Empty = include all.")

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_home, tab_tx, tab_single = st.tabs(["Home", "Transactions", "Single stock"])


# ─── TAB 1: Home ─────────────────────────────────────────────────────────────
with tab_home:
    _render_status_badge(live_mode, cache_meta)

    if all_tx.empty:
        st.info("No data yet. Run `python app.py snapshot` to pull the Robinhood snapshot.")
    else:
        min_date = all_tx["purchase_date"].min().date()
        max_date = all_tx["purchase_date"].max().date()

        st.markdown('<div class="filter-row">', unsafe_allow_html=True)
        fc1, fc2, fc3 = st.columns([2, 1, 1])
        preset_options = ["All time", "Last 30 days", "Last 90 days",
                          "Last 6 months", "Last year", "YTD", "Custom"]
        preset = fc1.selectbox("Date range", preset_options, index=0, key="date_preset")
        today = date.today()
        if preset == "All time":
            ds, de = min_date, max_date
        elif preset == "Last 30 days":
            ds, de = today - timedelta(days=30), today
        elif preset == "Last 90 days":
            ds, de = today - timedelta(days=90), today
        elif preset == "Last 6 months":
            ds, de = today - timedelta(days=183), today
        elif preset == "Last year":
            ds, de = today - timedelta(days=365), today
        elif preset == "YTD":
            ds, de = date(today.year, 1, 1), today
        else:
            ds = fc2.date_input("Start", value=min_date, min_value=min_date, max_value=max_date)
            de = fc3.date_input("End", value=max_date, min_value=min_date, max_value=max_date)
        st.markdown('</div>', unsafe_allow_html=True)
        if preset != "Custom":
            st.caption(f"Window: **{ds.isoformat()}** → **{de.isoformat()}**  ·  activity charts only; "
                       "holdings & returns are always the current snapshot.")

        filtered = _apply_filters(all_tx, start=ds, end=de, accounts=flt_accounts)

        # Holdings (current snapshot) — independent of the date window.
        holdings = _live_holdings(flt_accounts, _quotes_for(all_tickers, live_mode))
        invested = float(filtered.loc[filtered["quantity"] > 0, "cost_basis"].sum())
        sells_amt = float(-filtered.loc[filtered["quantity"] < 0, "cost_basis"].sum())
        n_buys = int((filtered["quantity"] > 0).sum())
        n_sells = int((filtered["quantity"] < 0).sum())
        cur_val = float(holdings["current_value"].sum(skipna=True)) if not holdings.empty else 0.0
        cost_now = float(holdings["invested"].sum()) if not holdings.empty else 0.0
        has_live = cur_val > 0 and not pd.isna(cur_val)
        pnl = cur_val - cost_now if has_live else float("nan")

        mc = st.columns(5)
        mc[0].metric("Invested (buys, window)", f"${invested:,.0f}")
        mc[1].metric("Sells (proceeds, window)", f"${sells_amt:,.0f}")
        mc[2].metric("Holdings", f"{len(holdings)}")
        mc[3].metric("Current value", f"${cur_val:,.0f}" if has_live else "—",
                     help=None if has_live else "Enable Live prices in the sidebar.")
        if has_live:
            pct = (pnl / cost_now * 100.0) if cost_now else 0.0
            mc[4].metric("Unrealized P&L", f"${pnl:,.0f}", f"{pct:+.1f}%")
        else:
            mc[4].metric("Unrealized P&L", "—")

        # Stock heatmap — gain on cost, colored by return band
        st.subheader("Stock heatmap — gain on cost")
        st.caption("One tile per holding, colored by total return on what you invested: "
                   "🟩 dark green > 100% · 🟢 light green 50–100% · 🟨 yellow 30–50% · "
                   "⬜ neutral 0–30% · 🟥 red = loss.")
        heat_fields = st.multiselect(
            "Show on each tile", HEAT_FIELDS, default=["Return %", "Shares"],
            key="heat_fields", help="Pick any combination (or none for ticker-only).")
        _heat = _stock_heatmap(holdings, heat_fields)
        if _heat is None:
            st.info("Turn on **Live prices** in the sidebar to color stocks by return.")
        else:
            st.altair_chart(_heat, use_container_width=True)

        # Activity heatmap (year × month)
        st.subheader("Heatmap of investment")
        mo = report.monthly_activity(filtered)
        if mo.empty:
            st.caption("No buys in this window.")
        else:
            months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
            mo["month_label"] = pd.Categorical(mo["month"].apply(lambda m: months[m-1]),
                                               categories=months, ordered=True)
            mo["year_str"] = mo["year"].astype(str)
            mo["invested_label"] = mo["invested"].apply(_compact_usd)
            label_mid = float(mo["invested"].max()) * 0.55
            base = alt.Chart(mo).encode(
                x=alt.X("month_label:O", title=None, axis=alt.Axis(labelFontWeight="bold")),
                y=alt.Y("year_str:O", title=None, sort="descending", axis=alt.Axis(labelFontWeight="bold")),
            )
            rects = base.mark_rect(stroke="white", strokeWidth=2, cornerRadius=4).encode(
                color=alt.Color("invested:Q", scale=alt.Scale(scheme="plasma"), title="Invested",
                                legend=alt.Legend(orient="bottom", gradientLength=240)),
                tooltip=[alt.Tooltip("year:O"), alt.Tooltip("month_label:O", title="Month"),
                         alt.Tooltip("invested:Q", format="$,.2f"),
                         alt.Tooltip("n_trades:Q", title="Trades")],
            )
            labels = base.mark_text(fontWeight="bold", fontSize=12).encode(
                text=alt.Text("invested_label:N"),
                color=alt.condition(alt.datum.invested > label_mid, alt.value("#1e293b"), alt.value("white")),
            )
            st.altair_chart(
                (rects + labels).resolve_scale(color="independent")
                .properties(height=max(120, 40 * mo["year"].nunique()))
                .configure_view(strokeWidth=0)
                .configure_axis(domainColor="#cbd5e1", tickColor="#cbd5e1"),
                use_container_width=True,
            )

        # Invested vs sold, by year
        st.subheader("Invested vs sold, by year")
        yr = report.yearly_activity(filtered)
        if yr.empty:
            st.caption("No buys or sells in this window.")
        else:
            yr["year_str"] = yr["year"].astype(int).astype(str)
            yr_long = yr.melt(id_vars=["year_str"], value_vars=["invested", "sold"],
                              var_name="flow", value_name="usd")
            yr_long["flow"] = yr_long["flow"].map({"invested": "Invested (buys)", "sold": "Sold (proceeds)"})
            yr_bars = (
                alt.Chart(yr_long).mark_bar(cornerRadiusEnd=3)
                .encode(
                    x=alt.X("year_str:O", title=None, axis=alt.Axis(labelFontWeight="bold")),
                    xOffset=alt.XOffset("flow:N"),
                    y=alt.Y("usd:Q", title="USD"),
                    color=alt.Color("flow:N", title=None,
                                    scale=alt.Scale(domain=["Invested (buys)", "Sold (proceeds)"], range=[GREEN, RED]),
                                    legend=alt.Legend(orient="top")),
                    tooltip=[alt.Tooltip("year_str:O", title="Year"), alt.Tooltip("flow:N", title=None),
                             alt.Tooltip("usd:Q", format="$,.2f")],
                ).properties(height=260).configure_view(strokeWidth=0)
                .configure_axis(grid=True, gridColor="#f1f5f9", domainColor="#cbd5e1", tickColor="#cbd5e1")
            )
            st.altair_chart(yr_bars, use_container_width=True)
            yr_tbl = yr.copy()
            yr_tbl["net"] = yr_tbl["invested"] - yr_tbl["sold"]
            st.dataframe(
                yr_tbl[["year", "invested", "sold", "net", "n_buys", "n_sells"]].rename(columns={
                    "year": "Year", "invested": "Invested (buys)", "sold": "Sold (proceeds)",
                    "net": "Net invested", "n_buys": "Buys", "n_sells": "Sells"}),
                hide_index=True, use_container_width=True,
                column_config={
                    "Year": st.column_config.NumberColumn(format="%d"),
                    "Invested (buys)": st.column_config.NumberColumn(format="$%.2f"),
                    "Sold (proceeds)": st.column_config.NumberColumn(format="$%.2f"),
                    "Net invested": st.column_config.NumberColumn(format="$%.2f"),
                },
            )
            st.caption("Cash buys/sells from order history only. Shares transferred in "
                       "(e.g. from another account) have no buy row, so 'invested' can understate them.")

        # Portfolio vs the market since 2019
        st.subheader("Portfolio vs the market, since 2019")
        st.caption("Your picks vs the S&P 500 (VOO) and Nasdaq-100 (QQQ). End-of-day "
                   "history; respects the account filter but always spans the full timeline.")
        bench_tx = _apply_filters(all_tx, start=None, end=None, accounts=flt_accounts)
        close_hist = perf.load_close_history(APP_ROOT)
        rebased = perf.rebased_growth(bench_tx, close_hist)
        growth = perf.growth_vs_benchmarks(bench_tx, close_hist)
        if rebased.empty:
            st.info("Needs price history including VOO and QQQ — run `python history.py`.")
        else:
            MARKET_COLORS = {perf.PORTFOLIO_LABEL: "#6366f1", "S&P 500": ORANGE,
                             "Nasdaq 100": GREEN, perf.INVESTED_LABEL: "#94a3b8"}
            summ = perf.comparison_summary(rebased)
            dollar_finals = (growth.sort_values("date").groupby("series").tail(1)
                             .set_index("series")["value"])
            summ_show = summ.assign(final_value=summ["series"].map(dollar_finals)).rename(columns={
                "series": "Series", "total_return_pct": "Total return %",
                "annualized_pct": "Annualized %/yr", "alpha_pp": "vs S&P500 (pp/yr)",
                "final_value": "Your $ today"})
            st.dataframe(
                summ_show, hide_index=True, use_container_width=True,
                column_config={
                    "Total return %": st.column_config.NumberColumn(format="%.1f%%"),
                    "Annualized %/yr": st.column_config.NumberColumn(format="%.1f%%"),
                    "vs S&P500 (pp/yr)": st.column_config.NumberColumn(format="%+.1f"),
                    "Your $ today": st.column_config.NumberColumn(format="$%.0f"),
                },
            )

            def _market_chart(long_df, y_title):
                order = [perf.PORTFOLIO_LABEL, "S&P 500", "Nasdaq 100", perf.INVESTED_LABEL]
                present = [s for s in order if s in set(long_df["series"])]
                return (
                    alt.Chart(long_df[long_df["series"].isin(present)])
                    .mark_line(interpolate="monotone", strokeWidth=2)
                    .encode(
                        x=alt.X("date:T", title=None),
                        y=alt.Y("value:Q", title=y_title),
                        color=alt.Color("series:N", title=None,
                                        scale=alt.Scale(domain=present, range=[MARKET_COLORS[s] for s in present]),
                                        legend=alt.Legend(orient="top")),
                        tooltip=[alt.Tooltip("date:T", title="Date"), alt.Tooltip("series:N", title=None),
                                 alt.Tooltip("value:Q", title=y_title, format="$,.0f")],
                    ).properties(height=300).configure_view(strokeWidth=0)
                    .configure_axis(grid=True, gridColor="#f1f5f9", domainColor="#cbd5e1", tickColor="#cbd5e1")
                )

            gc1, gc2 = st.columns(2, gap="medium")
            with gc1:
                st.markdown("##### Pure return — growth of $100")
                st.caption("Time-weighted: strips out *when* you added money.")
                st.altair_chart(_market_chart(rebased, "Growth of $100"), use_container_width=True)
            with gc2:
                st.markdown("##### Dollar outcome — your contributions")
                st.caption("Money-weighted: what your dated contributions are worth vs the index.")
                st.altair_chart(_market_chart(growth, "Value (USD)"), use_container_width=True)

        # Holdings table (live snapshot)
        st.subheader("Holdings")
        if holdings.empty:
            st.caption("No current holdings in the snapshot.")
        else:
            view = holdings.copy()
            view["Logo"] = view["ticker"].apply(lambda t: media_mod.icon_data_url(APP_ROOT, t, size=48))
            view = view.rename(columns={
                "ticker": "Ticker", "quantity": "Qty", "avg_cost": "Avg cost", "invested": "Invested",
                "current_price": "Last price", "current_value": "Current value",
                "pnl": "P&L", "pnl_pct": "P&L %", "n_accounts": "# accts"})
            st.dataframe(
                view[["Logo", "Ticker", "Qty", "Avg cost", "Invested", "Last price",
                      "Current value", "P&L", "P&L %", "# accts"]],
                hide_index=True, use_container_width=True,
                column_config={
                    "Logo": st.column_config.ImageColumn("•", width="small"),
                    "Qty": st.column_config.NumberColumn(format="%.4f"),
                    "Avg cost": st.column_config.NumberColumn(format="$%.2f"),
                    "Invested": st.column_config.NumberColumn(format="$%.2f"),
                    "Last price": st.column_config.NumberColumn(format="$%.2f"),
                    "Current value": st.column_config.NumberColumn(format="$%.2f"),
                    "P&L": st.column_config.NumberColumn(format="$%.2f"),
                    "P&L %": st.column_config.NumberColumn(format="%.2f%%"),
                },
            )

        # How each stock returned, year by year
        st.subheader("How each stock returned, year by year")
        if close_hist.empty:
            st.info("No price history yet. Run `python history.py` to build close_prices.csv.")
        elif holdings.empty:
            st.caption("No holdings to chart.")
        else:
            held = [t for t in holdings["ticker"] if t in close_hist.columns]
            ymat = perf.yearly_return_matrix(close_hist, held)
            if ymat.empty:
                st.caption("Not enough history to compute yearly returns.")
            else:
                long = (ymat.reset_index().melt(id_vars="index", var_name="year", value_name="ret")
                        .rename(columns={"index": "ticker"}).dropna(subset=["ret"]))
                long["label"] = long["ret"].map(lambda v: f"{v:+.0f}%")
                heat = (
                    alt.Chart(long).mark_rect(stroke="white", strokeWidth=1).encode(
                        x=alt.X("year:O", title=None, axis=alt.Axis(labelFontWeight="bold", orient="top")),
                        y=alt.Y("ticker:N", title=None, sort=held),
                        color=alt.Color("ret:Q", title="Year return %",
                                        scale=alt.Scale(scheme="redyellowgreen", domainMid=0),
                                        legend=alt.Legend(orient="bottom", gradientLength=240)),
                        tooltip=[alt.Tooltip("ticker:N"), alt.Tooltip("year:O", title="Year"),
                                 alt.Tooltip("ret:Q", title="Return %", format="+.1f")],
                    ).properties(height=max(180, 24 * len(held)))
                )
                text = (
                    alt.Chart(long).mark_text(fontSize=10).encode(
                        x=alt.X("year:O"), y=alt.Y("ticker:N", sort=held), text="label:N",
                        color=alt.condition("abs(datum.ret) > 60", alt.value("white"), alt.value("#1e293b")),
                    )
                )
                st.altair_chart(
                    (heat + text).resolve_scale(color="independent").configure_view(strokeWidth=0),
                    use_container_width=True,
                )


# ─── TAB 2: Transactions ─────────────────────────────────────────────────────
with tab_tx:
    _render_status_badge(live_mode, cache_meta)
    st.markdown("### Transactions")
    st.caption("Every buy / sell / split / dividend-reinvestment across the Venu Robinhood accounts.")

    trades = all_tx
    if trades.empty:
        st.info("No transactions yet. Run `python app.py snapshot`.")
    else:
        tmin = trades["purchase_date"].min().date()
        tmax = trades["purchase_date"].max().date()
        today = date.today()

        st.markdown('<div class="filter-row">', unsafe_allow_html=True)
        pc1, pc2, pc3 = st.columns([2, 1, 1])
        period_opts = ["All time", "YTD", "QTD", "Last 30 days", "Last 90 days",
                       "Last 12 months", "Specific quarter", "Custom"]
        period = pc1.selectbox("Period", period_opts, index=0, key="tx_period")
        yr = qt = None
        if period == "Specific quarter":
            years = list(range(tmax.year, tmin.year - 1, -1))
            yr = pc2.selectbox("Year", years, key="tx_year")
            qt = pc3.selectbox("Quarter", [1, 2, 3, 4], format_func=lambda q: f"Q{q}", key="tx_quarter")
            ds, de = _period_range(period, tmin, tmax, today, yr, qt)
        elif period == "Custom":
            ds = pc2.date_input("Start", value=tmin, min_value=tmin, max_value=tmax, key="tx_start")
            de = pc3.date_input("End", value=tmax, min_value=tmin, max_value=tmax, key="tx_end")
        else:
            ds, de = _period_range(period, tmin, tmax, today)
        st.markdown('</div>', unsafe_allow_html=True)

        store = txn_tags.load(APP_ROOT)
        known_tags = txn_tags.all_tag_names(store)

        f1, f2, f3 = st.columns(3)
        accts = sorted(trades["account"].dropna().unique().tolist())
        tkrs = sorted(trades["ticker"].dropna().unique().tolist())
        sel_accounts = f1.multiselect("Accounts", accts, default=[], key="tx_acct")
        sel_tickers = f2.multiselect("Tickers", tkrs, default=[], key="tx_tkr")
        sel_tagfilter = f3.multiselect("Tags", known_tags, default=[], key="tx_tagfilter")

        view = _apply_filters(trades, start=ds, end=de, accounts=sel_accounts or None)
        if sel_tickers:
            view = view[view["ticker"].isin(sel_tickers)]

        act1, _ = st.columns([1, 3])
        action_choice = act1.radio("Show", ["All", "Buy", "Sell"], horizontal=True, key="tx_action")
        if action_choice != "All":
            view = view[view["action"] == action_choice]

        if sel_tagfilter and "txn_id" in view.columns:
            wanted = {tid for tid, tg in store.items() if set(tg) & set(sel_tagfilter)}
            view = view[view["txn_id"].isin(wanted)]

        view = view.copy()
        view["amount"] = view["quantity"] * view["purchase_price"]
        view = view.sort_values("purchase_date", ascending=False)

        # Cash totals exclude splits (no cash moves).
        cash = view[~view["row_type"].isin(["split"])] if "row_type" in view.columns else view
        bought = cash.loc[cash["quantity"] > 0, "amount"].sum()
        sold = -cash.loc[cash["quantity"] < 0, "amount"].sum()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Transactions", f"{len(view):,}")
        m2.metric("Bought (cash)", f"${bought:,.0f}")
        m3.metric("Sold (cash)", f"${sold:,.0f}")
        m4.metric("Net invested", f"${bought - sold:,.0f}")
        st.caption(f"Range: {ds:%Y-%m-%d} → {de:%Y-%m-%d}  ·  {len(view):,} rows  ·  "
                   "cash totals exclude stock-split rows")

        ids = view["txn_id"].tolist() if "txn_id" in view.columns else [""] * len(view)

        st.markdown("#### Tags")
        st.caption("Tags are saved to data/_txn_tags.json and survive restarts & snapshots. "
                   "Edit the **Tags** column inline (comma-separated) and click *Save tags*, "
                   "or bulk-apply a tag to every row in view.")
        bc1, bc2, bc3 = st.columns([2, 1, 1])
        bulk_tag = bc1.text_input("Tag", key="tx_bulk_tag", placeholder="e.g. long-term, RSU, review").strip()
        if bc2.button(f"➕ Add to {len(ids)} rows", use_container_width=True, disabled=not (bulk_tag and ids)):
            n = txn_tags.add_to_many(store, ids, bulk_tag)
            txn_tags.save(APP_ROOT, store)
            st.success(f"Added '{bulk_tag}' to {n} transactions.")
            st.rerun()
        if bc3.button(f"➖ Remove from {len(ids)} rows", use_container_width=True, disabled=not (bulk_tag and ids)):
            n = txn_tags.remove_from_many(store, ids, bulk_tag)
            txn_tags.save(APP_ROOT, store)
            st.success(f"Removed '{bulk_tag}' from {n} transactions.")
            st.rerun()

        cols = ["purchase_date", "account", "ticker", "action", "row_type",
                "txn_source", "quantity", "purchase_price", "amount"]
        cols = [c for c in cols if c in view.columns]
        disp = view[cols].rename(columns={
            "purchase_date": "Date", "account": "Account", "ticker": "Ticker",
            "action": "Action", "row_type": "Type", "txn_source": "Source",
            "quantity": "Qty", "purchase_price": "Price", "amount": "Amount"})
        disp.insert(0, "Tags", [", ".join(store.get(t, [])) for t in ids])
        locked = [c for c in disp.columns if c != "Tags"]
        edited = st.data_editor(
            disp, hide_index=True, use_container_width=True, height=520,
            num_rows="fixed", disabled=locked, key="tx_editor",
            column_config={
                "Tags": st.column_config.TextColumn("Tags", help="Comma-separated. Empty clears the row's tags.", width="medium"),
                "Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "Qty": st.column_config.NumberColumn(format="%+.4f"),
                "Price": st.column_config.NumberColumn(format="$%.4f"),
                "Amount": st.column_config.NumberColumn(format="$%.2f"),
            },
        )
        sc1, _ = st.columns([1, 3])
        if sc1.button("💾 Save tags", type="primary", use_container_width=True):
            for tid, val in zip(ids, edited["Tags"].tolist()):
                if not tid:
                    continue
                parsed = [p.strip() for p in str(val).replace(";", ",").split(",")]
                txn_tags.set_for(store, tid, parsed)
            txn_tags.save(APP_ROOT, store)
            st.success("Tags saved.")
            st.rerun()

        st.download_button("Download CSV (with tags)", disp.to_csv(index=False).encode("utf-8"),
                           file_name=f"transactions_{ds:%Y%m%d}_{de:%Y%m%d}.csv", mime="text/csv")

        with st.expander("Tag report (cash buys/sells per tag, all dates)"):
            if not known_tags:
                st.caption("No tags yet. Add some above to start building tag-based reports.")
            else:
                rows = []
                for name in known_tags:
                    tids = [tid for tid, tg in store.items() if name in tg]
                    sub = trades[trades["txn_id"].isin(tids)].copy()
                    sub["amount"] = sub["quantity"] * sub["purchase_price"]
                    c = sub[~sub["row_type"].isin(["split"])] if "row_type" in sub.columns else sub
                    rows.append({
                        "Tag": name, "Transactions": len(sub),
                        "Bought": round(c.loc[c["quantity"] > 0, "amount"].sum(), 2),
                        "Sold": round(-c.loc[c["quantity"] < 0, "amount"].sum(), 2),
                    })
                st.dataframe(
                    pd.DataFrame(rows), hide_index=True, use_container_width=True,
                    column_config={"Bought": st.column_config.NumberColumn(format="$%.2f"),
                                   "Sold": st.column_config.NumberColumn(format="$%.2f")},
                )


# ─── TAB 3: Single stock ─────────────────────────────────────────────────────
def _render_single_stock(ticker: str) -> None:
    _stock_header(ticker)
    lots = portfolio.lots_global(APP_ROOT, ticker)
    pos = _positions()
    prow = pos[pos["ticker"] == ticker] if not pos.empty else pos

    quotes = _quotes_for([ticker], live_mode)
    q = quotes.get(ticker)
    price = q.price if q else float("nan")

    held_qty = float(prow["quantity"].sum()) if not prow.empty else 0.0
    invested = float(prow["cost_basis"].sum()) if not prow.empty else 0.0
    avg_cost = (invested / held_qty) if held_qty else 0.0
    current_value = held_qty * price if pd.notna(price) else float("nan")
    unrealized = (current_value - invested) if pd.notna(current_value) else float("nan")
    unreal_pct = (unrealized / invested * 100.0) if (invested and pd.notna(unrealized)) else float("nan")

    # Realized P&L from order-history sells, costed at the live average.
    realized = float("nan"); sold_qty = 0.0
    if not lots.empty:
        disp = lots[lots["quantity"] < 0]
        sold_qty = float(-disp["quantity"].sum())
        if sold_qty > 0:
            proceeds = float(-disp["cost_basis"].sum())
            realized = proceeds - avg_cost * sold_qty

    mc = st.columns(5)
    mc[0].metric("Holding", f"{held_qty:,.4f}")
    mc[1].metric("Avg cost", f"${avg_cost:,.2f}")
    mc[2].metric("Invested", f"${invested:,.2f}")
    mc[3].metric("Current value", f"${current_value:,.2f}" if pd.notna(current_value) else "—")
    if held_qty > 0 and pd.notna(unrealized):
        mc[4].metric("Unrealized P&L", f"${unrealized:,.2f}",
                     f"{unreal_pct:+.2f}%" if pd.notna(unreal_pct) else None)
    else:
        mc[4].metric("Unrealized P&L", "—", help="No shares currently held." if held_qty == 0 else None)

    if sold_qty > 0 and pd.notna(realized):
        st.caption(f"Realized (order-history sells, costed at live avg): **${realized:,.2f}** "
                   f"on {sold_qty:,.4f} sh sold.")

    if prow is not None and not prow.empty:
        st.subheader("Per-account holdings")
        pa = prow.rename(columns={"nickname": "Account", "quantity": "Qty",
                                  "average_buy_price": "Avg cost", "cost_basis": "Invested"})
        st.dataframe(
            pa[["Account", "Qty", "Avg cost", "Invested"]],
            hide_index=True, use_container_width=True,
            column_config={"Qty": st.column_config.NumberColumn(format="%.4f"),
                           "Avg cost": st.column_config.NumberColumn(format="$%.2f"),
                           "Invested": st.column_config.NumberColumn(format="$%.2f")},
        )

    st.subheader("All transactions")
    if lots.empty:
        st.info(f"No order history for {ticker}. (Shares may have been transferred in.)")
        return
    store = txn_tags.load(APP_ROOT)
    ids = lots["txn_id"].tolist() if "txn_id" in lots.columns else [""] * len(lots)
    cols_tx = [c for c in ["purchase_date", "action", "row_type", "txn_source",
                           "quantity", "purchase_price", "cost_basis", "account"] if c in lots.columns]
    tx_show = lots.sort_values("purchase_date", ascending=False)[cols_tx].rename(columns={
        "purchase_date": "Date", "action": "Action", "row_type": "Type", "txn_source": "Source",
        "quantity": "Qty", "purchase_price": "Price", "cost_basis": "Cost", "account": "Account"})
    st.dataframe(
        tx_show, hide_index=True, use_container_width=True,
        column_config={"Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                       "Qty": st.column_config.NumberColumn(format="%+.4f"),
                       "Price": st.column_config.NumberColumn(format="$%.4f"),
                       "Cost": st.column_config.NumberColumn(format="$%.2f")},
    )

    if len(lots) > 1:
        scatter_df = lots.assign(Side=lots["action"], AbsQty=lots["quantity"].abs())
        scatter = (
            alt.Chart(scatter_df)
            .mark_point(opacity=0.85, stroke="white", strokeWidth=1.2, filled=True)
            .encode(
                x=alt.X("purchase_date:T", title="Date"),
                y=alt.Y("purchase_price:Q", title="Price (USD)"),
                size=alt.Size("AbsQty:Q", title="Qty", scale=alt.Scale(range=[60, 700])),
                color=alt.Color("Side:N", scale=alt.Scale(domain=["Buy", "Sell"], range=[GREEN, RED]),
                                legend=alt.Legend(title="Action")),
                tooltip=[alt.Tooltip("purchase_date:T", title="Date"), "Side",
                         alt.Tooltip("AbsQty:Q", title="Qty", format=",.4f"),
                         alt.Tooltip("purchase_price:Q", title="Price", format="$,.2f"),
                         "account"],
            ).properties(height=320, title=alt.TitleParams(
                text=f"{ticker} — every transaction across all accounts",
                fontSize=14, fontWeight="bold", color="#1e293b"))
            .configure_view(strokeWidth=0)
            .configure_axis(grid=True, gridColor="#f1f5f9", domainColor="#cbd5e1", tickColor="#cbd5e1")
        )
        st.altair_chart(scatter, use_container_width=True)


with tab_single:
    _render_status_badge(live_mode, cache_meta)
    if not all_tickers:
        st.info("No data yet.")
    else:
        if st.session_state.get("single_stock") not in all_tickers:
            st.session_state["single_stock"] = all_tickers[0]
        flt = st.text_input("Filter tickers", key="single_filter", placeholder="Type to narrow…").strip().upper()
        shown = [t for t in all_tickers if flt in t] if flt else all_tickers
        st.caption(f"Click a ticker to see its full details — {len(shown)} shown.")
        per_row = 12
        for i in range(0, len(shown), per_row):
            cols = st.columns(per_row)
            for col, tkr in zip(cols, shown[i:i + per_row]):
                is_sel = tkr == st.session_state["single_stock"]
                if col.button(tkr, key=f"pick_{tkr}", use_container_width=True,
                              type="primary" if is_sel else "secondary"):
                    st.session_state["single_stock"] = tkr
                    st.rerun()
        st.divider()
        _render_single_stock(st.session_state["single_stock"])
