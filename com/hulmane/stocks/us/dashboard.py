"""Streamlit dashboard for Hulmane US Stocks.

Tabs:
    1. Dashboard            — filters, headline metrics, activity heatmap, charts
    2. All stocks           — consolidated per-ticker view across every tag/account/broker
    3. Stocks performance   — best/worst ranking, annualized-return buckets, yearly
                              returns, vs-S&P500 decision quality, lump-sum vs DCA
    4. Transactions         — consolidated buy/sell ledger with per-txn tagging
    5. Single stock         — full buy/sell history + P&L for one ticker
    6. Pinned tickers       — one tab per pinned ticker (e.g. AVGO). Edit
                              data/_pinned.json or use the sidebar to manage.

Sidebar = Live toggle, refresh, optional tag/account/broker filters, upload, pinned.
"""
from __future__ import annotations

import json
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
from src import pipeline  # noqa: E402
from src import tags as txn_tags  # noqa: E402
from src import performance as perf  # noqa: E402

st.set_page_config(page_title="Hulmane US Stocks", layout="wide", page_icon="📈")


# ── Startup: rebuild data/formated from data/source, once per server start ─────
@st.cache_resource(show_spinner="Rebuilding data from data/source …")
def _bootstrap_pipeline():
    """Runs once per app start (cached for the server's lifetime). Restarting
    Streamlit, or clicking 'Rebuild from source', reruns it from ground zero."""
    return pipeline.run(APP_ROOT)


BOOTSTRAP = _bootstrap_pipeline()

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
      .hero-title {{
        font-size: 2.4rem;
        font-weight: 800;
        background: linear-gradient(90deg, {GRADIENT_START} 0%, {GRADIENT_END} 50%, #f59e0b 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.1em;
        letter-spacing: -0.02em;
      }}
      .hero-sub {{
        color: #64748b;
        font-size: 0.85rem;
        margin-top: 0;
      }}
      [data-testid="stMetric"] {{
        background: linear-gradient(135deg, #faf5ff 0%, #fdf2f8 100%);
        border: 1px solid #e9d5ff;
        padding: 16px 16px 12px 16px;
        border-radius: 14px;
        box-shadow: 0 1px 3px rgba(124, 58, 237, 0.08);
        transition: transform 120ms ease, box-shadow 120ms ease;
      }}
      [data-testid="stMetric"]:hover {{
        transform: translateY(-2px);
        box-shadow: 0 8px 18px rgba(124, 58, 237, 0.12);
      }}
      [data-testid="stMetricLabel"] {{
        color: #6b7280;
        font-weight: 600;
        text-transform: uppercase;
        font-size: 0.7rem;
        letter-spacing: 0.06em;
      }}
      [data-testid="stMetricValue"] {{
        color: #1e293b;
        font-weight: 700;
      }}
      .stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
      .stTabs [data-baseweb="tab"] {{
        background: #f5f3ff;
        border-radius: 10px 10px 0 0;
        padding: 8px 16px;
        font-weight: 600;
      }}
      .stTabs [aria-selected="true"] {{
        background: linear-gradient(135deg, {GRADIENT_START}, {GRADIENT_END});
        color: white !important;
      }}
      h3 {{
        border-left: 4px solid {GRADIENT_START};
        padding-left: 10px;
        margin-top: 1.2em;
      }}
      [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, #faf5ff 0%, #fdf2f8 100%);
      }}
      [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2 {{
        color: {GRADIENT_START};
      }}
      .stButton > button {{
        border-radius: 10px;
        font-weight: 600;
        border: none;
      }}
      .stButton > button[kind="primary"] {{
        background: linear-gradient(135deg, {GRADIENT_START}, {GRADIENT_END});
      }}
      [data-testid="stDataFrame"] {{
        border-radius: 12px;
        overflow: hidden;
      }}
      .status-badge {{
        display: inline-flex; align-items: center; gap: 6px;
        padding: 4px 12px; border-radius: 999px;
        font-size: 0.78rem; font-weight: 700;
        letter-spacing: 0.04em; text-transform: uppercase;
      }}
      .status-badge .dot {{
        width: 8px; height: 8px; border-radius: 50%; display: inline-block;
      }}
      .status-live {{
        background: linear-gradient(135deg, #10b981, #06b6d4); color: white;
      }}
      .status-live .dot {{
        background: white; animation: pulse 1.6s infinite;
      }}
      .status-cached {{
        background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1;
      }}
      .status-cached .dot {{ background: #94a3b8; }}
      .status-empty {{
        background: #fef3c7; color: #92400e; border: 1px solid #fcd34d;
      }}
      .status-empty .dot {{ background: #f59e0b; }}
      @keyframes pulse {{
        0%   {{ box-shadow: 0 0 0 0 rgba(255,255,255,0.6); }}
        70%  {{ box-shadow: 0 0 0 8px rgba(255,255,255,0); }}
        100% {{ box-shadow: 0 0 0 0 rgba(255,255,255,0); }}
      }}
      .stock-header {{
        display: flex; align-items: center; gap: 16px;
        padding: 16px 20px; margin: 8px 0 18px; border-radius: 16px;
        background: linear-gradient(135deg, #faf5ff 0%, #fdf2f8 100%);
        border: 1px solid #e9d5ff;
      }}
      .stock-header img {{
        width: 64px; height: 64px; border-radius: 14px;
        background: white; padding: 4px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
      }}
      .stock-header .meta {{ font-size: 0.85rem; color: #6b7280; }}
      .stock-header .ticker {{
        font-size: 1.6rem; font-weight: 800; color: #1e293b;
      }}
      .pill {{
        display: inline-block;
        padding: 4px 10px; border-radius: 999px;
        font-size: 0.74rem; font-weight: 700; margin-right: 6px;
      }}
      .pill-lt   {{ background: #dbeafe; color: #1e40af; }}
      .pill-st   {{ background: #fed7aa; color: #9a3412; }}
      .pill-pos  {{ background: #d1fae5; color: #065f46; }}
      .pill-neg  {{ background: #fee2e2; color: #991b1b; }}
      .filter-row {{
        background: #faf5ff; padding: 14px 18px; border-radius: 12px;
        border: 1px solid #e9d5ff; margin-bottom: 1em;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="hero-title">Hulmane — US Stocks</div>', unsafe_allow_html=True)
st.markdown(
    f'<p class="hero-sub">'
    f'Data: <code>{portfolio.transactions_dir(APP_ROOT)}</code> &nbsp;•&nbsp; '
    f'Reports: <code>{report.reports_dir(APP_ROOT)}</code></p>',
    unsafe_allow_html=True,
)


# ── Helpers ────────────────────────────────────────────────────────────────────
def _format_age(iso_ts: str | None) -> str:
    if not iso_ts:
        return "never"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        secs = int(delta.total_seconds())
        if secs < 60: return f"{secs}s ago"
        if secs < 3600: return f"{secs // 60}m ago"
        if secs < 86400: return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return iso_ts


def _compact_usd(v: float) -> str:
    """Short dollar label for tight spaces: $950, $1.2K, $3.4M."""
    if v is None or pd.isna(v):
        return ""
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:,.1f}M"
    if abs(v) >= 1_000:
        return f"${v / 1_000:,.1f}K"
    return f"${v:,.0f}"


def _render_status_badge(live: bool, summary: dict) -> None:
    if live:
        html = ('<span class="status-badge status-live"><span class="dot"></span>'
                'Live · prices fetched now</span>')
    elif summary["count"] == 0:
        html = ('<span class="status-badge status-empty"><span class="dot"></span>'
                'No cached prices yet</span>')
    else:
        newest = _format_age(summary.get("newest"))
        html = (f'<span class="status-badge status-cached"><span class="dot"></span>'
                f'Cached · {summary["count"]} tickers · newest {newest}</span>')
    st.markdown(html, unsafe_allow_html=True)


@st.cache_data(ttl=120, show_spinner=False)
def _all_transactions() -> pd.DataFrame:
    return portfolio.load_all(APP_ROOT)


# ── Pinned tickers (one tab each) ─────────────────────────────────────────────
PINNED_PATH = APP_ROOT / "data" / "_pinned.json"
PINNED_DEFAULT = ["AVGO"]


def _read_pinned() -> list[str]:
    if not PINNED_PATH.exists():
        return list(PINNED_DEFAULT)
    try:
        data = json.loads(PINNED_PATH.read_text())
        if isinstance(data, list):
            return [str(t).upper() for t in data]
    except Exception:
        pass
    return list(PINNED_DEFAULT)


def _write_pinned(tickers: list[str]) -> None:
    PINNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    PINNED_PATH.write_text(json.dumps(tickers, indent=2))


def _quotes_for(tickers: list[str], live: bool) -> dict[str, pricing.Quote]:
    if not tickers:
        return {}
    if live:
        return pricing.get_quotes_live_and_cache(APP_ROOT, tickers)
    return pricing.get_quotes_cached(APP_ROOT, tickers)


def _apply_filters(df: pd.DataFrame, *, start: date | None, end: date | None,
                   tags: list[str] | None, accounts: list[str] | None,
                   brokers: list[str] | None) -> pd.DataFrame:
    if df.empty:
        return df
    out = df
    if start:
        out = out[out["purchase_date"] >= pd.Timestamp(start)]
    if end:
        out = out[out["purchase_date"] <= pd.Timestamp(end) + pd.Timedelta(days=1)]
    if tags:
        out = out[out["tag"].isin(tags)]
    if accounts:
        out = out[out["account"].isin(accounts)]
    if brokers:
        out = out[out["broker"].isin(brokers)]
    return out


def _period_range(label: str, min_d: date, max_d: date, today: date,
                  year: int | None = None, quarter: int | None = None
                  ) -> tuple[date, date]:
    """Resolve a named period (YTD, QTD, a specific quarter, …) to (start, end)."""
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
    return min_d, max_d  # "All time"


def _stock_header(ticker: str) -> None:
    icon_url = media_mod.icon_data_url(APP_ROOT, ticker, size=96)
    cache = pricing.load_cache(APP_ROOT)
    name = cache[ticker]["name"] if ticker in cache and cache[ticker].get("name") else ""
    has_real = media_mod.logo_path(APP_ROOT, ticker) is not None
    badge = "" if has_real else (
        '<span class="pill" style="background:#f3e8ff;color:#9333ea;">auto-icon</span>'
    )
    st.markdown(
        f'<div class="stock-header">'
        f'<img src="{icon_url}" />'
        f'<div>'
        f'<div class="ticker">{ticker}</div>'
        f'<div class="meta">{name or "&nbsp;"} {badge}</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )


# ── Sidebar: live toggle, refresh, filters, upload ────────────────────────────
all_tx = _all_transactions()
all_tags = portfolio.list_tags(APP_ROOT)
all_accounts = sorted(all_tx["account"].dropna().unique().tolist()) if not all_tx.empty else []
all_brokers = sorted(all_tx["broker"].dropna().unique().tolist()) if not all_tx.empty else []
all_tickers = portfolio.all_tickers(APP_ROOT)

with st.sidebar:
    st.header("Controls")
    live_mode = st.toggle(
        "Live prices",
        value=st.session_state.get("live_mode", False),
        key="live_mode",
        help=("ON: fetch from Yahoo Finance + update cache.\n"
              "OFF: show last-known cached prices."),
    )
    cache_meta = pricing.cache_summary(APP_ROOT)
    if cache_meta["count"]:
        st.caption(f"Cache: {cache_meta['count']} tickers · "
                   f"newest {_format_age(cache_meta['newest'])}")
    else:
        st.caption("Cache: empty")
    if st.button("Refresh", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    with st.expander("Data rebuild (from data/source)", expanded=False):
        st.caption(f"Last rebuilt: {BOOTSTRAP.started_at} · {BOOTSTRAP.total_rows} rows")
        n_err = sum(1 for t in BOOTSTRAP.tags for f in t.files if f.status == "error")
        n_unmatched = sum(sum(t.unmatched_accounts.values()) for t in BOOTSTRAP.tags)
        if n_err:
            st.error(f"{n_err} file(s) errored — see log below.")
        if n_unmatched:
            st.warning(f"{n_unmatched} row(s) on accounts not in accounts.csv.")
        for t in BOOTSTRAP.tags:
            note = f" · {t.duplicates_dropped} dup dropped" if t.duplicates_dropped else ""
            st.caption(f"**{t.tag}** — {t.rows} rows{note}")
        if st.button("Rebuild from source", use_container_width=True):
            _bootstrap_pipeline.clear()
            st.cache_data.clear()
            st.rerun()
        log_file = APP_ROOT / "logs" / "latest.log"
        if log_file.exists():
            with st.popover("View processing log", use_container_width=True):
                st.code(log_file.read_text(), language="text")

    st.divider()
    with st.expander("Filters", expanded=False):
        flt_tags = st.multiselect("Tags", all_tags, default=[])
        flt_accounts = st.multiselect("Accounts", all_accounts, default=[])
        flt_brokers = st.multiselect("Brokers", all_brokers, default=[])
        st.caption("Empty = include all.")

    with st.expander("Pinned tickers (own tab each)", expanded=False):
        current_pinned = _read_pinned()
        new_pin = st.text_input("Pin a ticker", key="pin_input").upper().strip()
        cpb1, cpb2 = st.columns(2)
        if cpb1.button("Add", use_container_width=True, disabled=not new_pin):
            if new_pin and new_pin not in current_pinned:
                current_pinned.append(new_pin)
                _write_pinned(current_pinned)
                st.rerun()
        if cpb2.button("Reset", use_container_width=True):
            _write_pinned(list(PINNED_DEFAULT))
            st.rerun()
        if current_pinned:
            st.caption("Currently pinned (click ✕ to remove):")
            for t in current_pinned:
                rc1, rc2 = st.columns([3, 1])
                rc1.markdown(f"`{t}`")
                if rc2.button("✕", key=f"unpin_{t}", use_container_width=True):
                    _write_pinned([x for x in current_pinned if x != t])
                    st.rerun()
        else:
            st.caption("None pinned.")

    with st.expander("Upload tagged CSV", expanded=False):
        up = st.file_uploader("CSV", type=["csv"], key="upload_csv")
        new_tag = st.text_input("Tag", key="upload_tag").strip()
        if st.button("Save", disabled=not (up and new_tag)):
            tmp = APP_ROOT / "data" / "_uploaded.csv"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(up.getvalue())
            try:
                dest = portfolio.upload(APP_ROOT, tmp, new_tag)
                st.success(f"Saved to {dest}")
                st.cache_data.clear()
            except Exception as e:
                st.error(str(e))
            finally:
                tmp.unlink(missing_ok=True)


# ── Tabs ──────────────────────────────────────────────────────────────────────
pinned_existing = [t for t in _read_pinned() if t in all_tickers]
pinned_missing = [t for t in _read_pinned() if t not in all_tickers]
_tab_labels = (["Dashboard", "All stocks", "Stocks performance", "Transactions",
                "Single stock"] + pinned_existing)
_tabs = st.tabs(_tab_labels)
tab_dash = _tabs[0]
tab_stocks = _tabs[1]
tab_perf = _tabs[2]
tab_tx = _tabs[3]
tab_single = _tabs[4]
pinned_tabs = _tabs[5:]

if pinned_missing:
    st.sidebar.caption(
        f"⚠ Pinned but no data: {', '.join(pinned_missing)}"
    )

# ─── TAB 1: Dashboard ─────────────────────────────────────────────────────────
with tab_dash:
    _render_status_badge(live_mode, cache_meta)

    if all_tx.empty:
        st.info("No data yet. Upload a CSV from the sidebar.")
    else:
        # Date range filter row
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
            ds = fc2.date_input("Start", value=min_date,
                                min_value=min_date, max_value=max_date)
            de = fc3.date_input("End", value=max_date,
                                min_value=min_date, max_value=max_date)
        st.markdown('</div>', unsafe_allow_html=True)

        if preset != "Custom":
            st.caption(f"Window: **{ds.isoformat()}** → **{de.isoformat()}**")

        filtered = _apply_filters(
            all_tx, start=ds, end=de,
            tags=flt_tags, accounts=flt_accounts, brokers=flt_brokers,
        )

        if filtered.empty:
            st.warning("No transactions match the current filters.")
        else:
            # Headline metrics
            quotes_dash = _quotes_for(
                sorted(filtered["ticker"].unique().tolist()), live_mode
            )
            holdings_view = report.global_holdings(
                APP_ROOT, quotes=quotes_dash, transactions=filtered
            )

            invested = float(filtered.loc[filtered["quantity"] > 0, "cost_basis"].sum())
            sells_amt = float(-filtered.loc[filtered["quantity"] < 0, "cost_basis"].sum())
            n_buys = int((filtered["quantity"] > 0).sum())
            n_sells = int((filtered["quantity"] < 0).sum())
            n_tickers = filtered["ticker"].nunique()

            current_value = float(holdings_view["current_value"].sum(skipna=True))
            has_live = current_value > 0 and not pd.isna(current_value)
            pnl = current_value - float(holdings_view["invested"].sum()) if has_live else float("nan")

            mc = st.columns(5)
            mc[0].metric("Invested (buys)", f"${invested:,.2f}")
            mc[1].metric("Sells (proceeds)", f"${sells_amt:,.2f}")
            mc[2].metric("Transactions", f"{n_buys + n_sells:,}",
                          f"{n_buys} buys / {n_sells} sells")
            mc[3].metric("Tickers", f"{n_tickers}")
            if has_live:
                pct = (pnl / float(holdings_view["invested"].sum()) * 100.0
                       if holdings_view["invested"].sum() else 0.0)
                mc[4].metric("P&L", f"${pnl:,.2f}", f"{pct:+.2f}%")
            else:
                mc[4].metric("P&L", "—", help="Enable Live in the sidebar.")

            # Activity heatmap (year × month)
            st.subheader("Activity heatmap")
            mo = report.monthly_activity(filtered)
            if mo.empty:
                st.caption("No buys in this window.")
            else:
                mo["month_label"] = pd.Categorical(
                    mo["month"].apply(lambda m: ["Jan","Feb","Mar","Apr","May","Jun",
                                                  "Jul","Aug","Sep","Oct","Nov","Dec"][m-1]),
                    categories=["Jan","Feb","Mar","Apr","May","Jun",
                                "Jul","Aug","Sep","Oct","Nov","Dec"], ordered=True,
                )
                mo["year_str"] = mo["year"].astype(str)
                mo["invested_label"] = mo["invested"].apply(_compact_usd)
                # Dark text on the bright (high-invested) cells, light on the dark ones.
                # Cast to plain float: a numpy scalar serializes into the Vega
                # predicate as "np.float64(...)" (invalid JS) and blanks the chart.
                label_mid = float(mo["invested"].max()) * 0.55
                base = alt.Chart(mo).encode(
                    x=alt.X("month_label:O", title=None,
                            axis=alt.Axis(labelFontWeight="bold")),
                    y=alt.Y("year_str:O", title=None, sort="descending",
                            axis=alt.Axis(labelFontWeight="bold")),
                )
                rects = base.mark_rect(
                    stroke="white", strokeWidth=2, cornerRadius=4
                ).encode(
                    color=alt.Color(
                        "invested:Q",
                        scale=alt.Scale(scheme="plasma"),
                        title="Invested",
                        legend=alt.Legend(orient="bottom", gradientLength=240),
                    ),
                    tooltip=[
                        alt.Tooltip("year:O"),
                        alt.Tooltip("month_label:O", title="Month"),
                        alt.Tooltip("invested:Q", format="$,.2f"),
                        alt.Tooltip("n_trades:Q", title="Trades"),
                    ],
                )
                labels = base.mark_text(fontWeight="bold", fontSize=12).encode(
                    text=alt.Text("invested_label:N"),
                    color=alt.condition(
                        alt.datum.invested > label_mid,
                        alt.value("#1e293b"), alt.value("white"),
                    ),
                )
                heat = (
                    (rects + labels)
                    # rects color by a quantitative scale, labels by a fixed value —
                    # keep the two color encodings from being merged into one scale.
                    .resolve_scale(color="independent")
                    .properties(height=max(120, 40 * mo["year"].nunique()))
                    .configure_view(strokeWidth=0)
                    .configure_axis(domainColor="#cbd5e1", tickColor="#cbd5e1")
                )
                st.altair_chart(heat, use_container_width=True)

            # Invested vs sold, by year
            st.subheader("Invested vs sold, by year")
            yr = report.yearly_activity(filtered)
            if yr.empty:
                st.caption("No buys or sells in this window.")
            else:
                yr["year_str"] = yr["year"].astype(int).astype(str)
                yr_long = yr.melt(
                    id_vars=["year_str"], value_vars=["invested", "sold"],
                    var_name="flow", value_name="usd",
                )
                yr_long["flow"] = yr_long["flow"].map(
                    {"invested": "Invested (buys)", "sold": "Sold (proceeds)"})
                yr_bars = (
                    alt.Chart(yr_long).mark_bar(cornerRadiusEnd=3)
                    .encode(
                        x=alt.X("year_str:O", title=None,
                                axis=alt.Axis(labelFontWeight="bold")),
                        xOffset=alt.XOffset("flow:N"),
                        y=alt.Y("usd:Q", title="USD"),
                        color=alt.Color(
                            "flow:N", title=None,
                            scale=alt.Scale(
                                domain=["Invested (buys)", "Sold (proceeds)"],
                                range=[GREEN, RED]),
                            legend=alt.Legend(orient="top")),
                        tooltip=[
                            alt.Tooltip("year_str:O", title="Year"),
                            alt.Tooltip("flow:N", title=None),
                            alt.Tooltip("usd:Q", format="$,.2f"),
                        ],
                    )
                    .properties(height=260)
                    .configure_view(strokeWidth=0)
                    .configure_axis(grid=True, gridColor="#f1f5f9",
                                    domainColor="#cbd5e1", tickColor="#cbd5e1")
                )
                st.altair_chart(yr_bars, use_container_width=True)

                yr_tbl = yr.copy()
                yr_tbl["net"] = yr_tbl["invested"] - yr_tbl["sold"]
                yr_show = yr_tbl[["year", "invested", "sold", "net",
                                  "n_buys", "n_sells"]].rename(columns={
                    "year": "Year", "invested": "Invested (buys)",
                    "sold": "Sold (proceeds)", "net": "Net invested",
                    "n_buys": "Buys", "n_sells": "Sells",
                })
                st.dataframe(
                    yr_show, hide_index=True, use_container_width=True,
                    column_config={
                        "Year": st.column_config.NumberColumn(format="%d"),
                        "Invested (buys)": st.column_config.NumberColumn(format="$%.2f"),
                        "Sold (proceeds)": st.column_config.NumberColumn(format="$%.2f"),
                        "Net invested": st.column_config.NumberColumn(format="$%.2f"),
                    },
                )

            # Cumulative invested over time
            st.subheader("Cumulative invested over time")
            line_df = filtered.copy().sort_values("purchase_date")
            line_df["cum_invested"] = line_df["cost_basis"].cumsum()
            line = (
                alt.Chart(line_df)
                .mark_area(
                    interpolate="monotone",
                    color=alt.Gradient(
                        gradient="linear",
                        stops=[alt.GradientStop(color=GRADIENT_START, offset=0),
                               alt.GradientStop(color=GRADIENT_END, offset=1)],
                        x1=0, x2=0, y1=1, y2=0,
                    ),
                    opacity=0.85,
                )
                .encode(
                    x=alt.X("purchase_date:T", title="Date"),
                    y=alt.Y("cum_invested:Q", title="Cumulative invested (USD)"),
                    tooltip=[
                        alt.Tooltip("purchase_date:T", title="Date"),
                        alt.Tooltip("cum_invested:Q", format="$,.2f"),
                        "ticker", "action", "broker", "account",
                    ],
                )
                .properties(height=260)
                .configure_view(strokeWidth=0)
                .configure_axis(grid=True, gridColor="#f1f5f9",
                                domainColor="#cbd5e1", tickColor="#cbd5e1")
            )
            st.altair_chart(line, use_container_width=True)

            # Distribution: top tickers + by broker / by account
            d1, d2, d3 = st.columns(3, gap="medium")

            with d1:
                top_tk = (
                    filtered.groupby("ticker", as_index=False)["cost_basis"].sum()
                    .sort_values("cost_basis", ascending=False).head(10)
                )
                st.caption("Top 10 tickers by invested")
                bar = (
                    alt.Chart(top_tk).mark_bar(cornerRadiusEnd=3)
                    .encode(
                        x=alt.X("cost_basis:Q", title="USD"),
                        y=alt.Y("ticker:N", sort="-x", title=None),
                        color=alt.Color("cost_basis:Q",
                                        scale=alt.Scale(scheme="purples"),
                                        legend=None),
                        tooltip=["ticker", alt.Tooltip("cost_basis:Q", format="$,.2f")],
                    ).properties(height=260)
                    .configure_view(strokeWidth=0)
                )
                st.altair_chart(bar, use_container_width=True)

            with d2:
                by_acct = (
                    filtered.groupby(["broker", "account"], as_index=False)["cost_basis"].sum()
                    .sort_values("cost_basis", ascending=False)
                )
                by_acct["label"] = by_acct["broker"] + " / " + by_acct["account"].astype(str)
                st.caption("By account")
                donut = (
                    alt.Chart(by_acct)
                    .mark_arc(innerRadius=50, outerRadius=110, padAngle=0.012,
                              cornerRadius=4, stroke="white", strokeWidth=2)
                    .encode(
                        theta=alt.Theta("cost_basis:Q"),
                        color=alt.Color("label:N", scale=alt.Scale(range=PALETTE),
                                        legend=alt.Legend(orient="bottom", title=None,
                                                          labelLimit=140)),
                        tooltip=["label",
                                  alt.Tooltip("cost_basis:Q", format="$,.2f")],
                    ).properties(height=260)
                    .configure_view(strokeWidth=0)
                )
                st.altair_chart(donut, use_container_width=True)

            with d3:
                by_act = (
                    filtered.groupby("action", as_index=False)["cost_basis"].agg(
                        invested=("cost_basis", "sum"), n=("cost_basis", "size")
                    ) if False else
                    filtered.assign(abs_cost=filtered["cost_basis"].abs())
                            .groupby("action", as_index=False)
                            .agg(usd=("abs_cost", "sum"), n=("abs_cost", "size"))
                )
                st.caption("Buy / Sell volume")
                bs = (
                    alt.Chart(by_act).mark_bar(cornerRadiusEnd=4)
                    .encode(
                        x=alt.X("action:N", title=None),
                        y=alt.Y("usd:Q", title="USD"),
                        color=alt.Color("action:N",
                                        scale=alt.Scale(domain=["Buy", "Sell"],
                                                        range=[GREEN, RED]),
                                        legend=None),
                        tooltip=["action", alt.Tooltip("usd:Q", format="$,.2f"), "n"],
                    ).properties(height=260)
                    .configure_view(strokeWidth=0)
                )
                st.altair_chart(bs, use_container_width=True)

            # Recent transactions
            st.subheader("Recent transactions")
            recent = filtered.sort_values("purchase_date", ascending=False).head(25)
            recent_show = recent[["purchase_date", "ticker", "action", "quantity",
                                   "purchase_price", "cost_basis", "broker",
                                   "account", "tag"]].rename(columns={
                "purchase_date": "Date", "ticker": "Ticker", "action": "Action",
                "quantity": "Qty", "purchase_price": "Price",
                "cost_basis": "Cost", "broker": "Broker",
                "account": "Account", "tag": "Tag",
            })

            def _row_color_recent(row):
                bg = "rgba(16,185,129,0.08)" if row["Action"] == "Buy" else "rgba(239,68,68,0.08)"
                return [f"background-color: {bg}"] * len(row)

            styler = (
                recent_show.style
                .apply(_row_color_recent, axis=1)
                .format({"Qty": "{:+.4f}", "Price": "${:,.4f}", "Cost": "${:,.2f}"})
            )
            st.dataframe(
                styler, hide_index=True, use_container_width=True,
                column_config={"Date": st.column_config.DateColumn(format="YYYY-MM-DD")},
            )


# ─── TAB 2: All stocks (consolidated) ─────────────────────────────────────────
with tab_stocks:
    _render_status_badge(live_mode, cache_meta)

    if all_tx.empty:
        st.info("No data yet.")
    else:
        filtered = _apply_filters(
            all_tx, start=None, end=None,
            tags=flt_tags, accounts=flt_accounts, brokers=flt_brokers,
        )
        if filtered.empty:
            st.warning("No data matches sidebar filters.")
        else:
            tickers = sorted(filtered["ticker"].unique().tolist())
            quotes = _quotes_for(tickers, live_mode)
            holdings = report.global_holdings(
                APP_ROOT, quotes=quotes, transactions=filtered
            )

            invested = float(holdings["invested"].sum())
            current = float(holdings["current_value"].sum(skipna=True))
            has_live = current > 0 and not pd.isna(current)
            pnl = current - invested if has_live else float("nan")

            mc = st.columns(5)
            mc[0].metric("Positions", f"{len(holdings)}")
            mc[1].metric("Invested", f"${invested:,.2f}")
            mc[2].metric("Current value", f"${current:,.2f}" if has_live else "—")
            if has_live:
                mc[3].metric("P&L", f"${pnl:,.2f}",
                             f"{pnl / invested * 100.0:+.2f}%" if invested else "—")
            else:
                mc[3].metric("P&L", "—")
            mc[4].metric("Brokers / Accounts",
                         f"{filtered['broker'].nunique()} / {filtered['account'].nunique()}")

            # Top 20 bar
            top_n = min(20, len(holdings))
            value_col = "current_value" if has_live else "invested"
            value_label = "Current value" if has_live else "Invested"
            top_df = holdings.sort_values(value_col, ascending=False).head(top_n)

            color_enc = (
                alt.Color("pnl_pct:Q",
                          scale=alt.Scale(scheme="redyellowgreen", domainMid=0),
                          title="P&L %",
                          legend=alt.Legend(orient="bottom", gradientLength=240))
                if has_live else
                alt.Color(f"{value_col}:Q",
                          scale=alt.Scale(scheme="purpleorange"),
                          title=value_label,
                          legend=alt.Legend(orient="bottom", gradientLength=240))
            )
            bar = (
                alt.Chart(top_df).mark_bar(cornerRadiusEnd=4)
                .encode(
                    x=alt.X(f"{value_col}:Q", title=f"{value_label} (USD)"),
                    y=alt.Y("ticker:N", sort="-x", title=None,
                            axis=alt.Axis(labelFontWeight="bold")),
                    color=color_enc,
                    tooltip=[
                        "ticker",
                        alt.Tooltip("quantity:Q", format=",.4f"),
                        alt.Tooltip("avg_cost:Q", format="$,.2f"),
                        alt.Tooltip("invested:Q", format="$,.2f"),
                        alt.Tooltip("current_price:Q", format="$,.2f"),
                        alt.Tooltip("current_value:Q", format="$,.2f"),
                        alt.Tooltip("pnl:Q", format="$,.2f"),
                        alt.Tooltip("pnl_pct:Q", format=".2f"),
                        alt.Tooltip("n_accounts:Q", title="# accounts"),
                    ],
                )
                .properties(
                    height=max(360, 24 * top_n),
                    title=alt.TitleParams(
                        text=f"Top {top_n} holdings (consolidated across all sources)",
                        fontSize=15, fontWeight="bold", color="#1e293b",
                    ),
                )
                .configure_view(strokeWidth=0)
                .configure_axis(grid=True, gridColor="#f1f5f9",
                                domainColor="#cbd5e1", tickColor="#cbd5e1")
            )
            st.altair_chart(bar, use_container_width=True)

            # Search box
            st.subheader("Consolidated table")
            search = st.text_input("Search ticker", "", key="stocks_search").upper().strip()
            view = holdings.copy()
            if search:
                view = view[view["ticker"].str.contains(search)]

            view["Logo"] = view["ticker"].apply(
                lambda t: media_mod.icon_data_url(APP_ROOT, t, size=48)
            )
            view = view.rename(columns={
                "ticker": "Ticker", "quantity": "Qty", "invested": "Invested",
                "avg_cost": "Avg cost", "current_price": "Last price",
                "current_value": "Current value", "pnl": "P&L", "pnl_pct": "P&L %",
                "n_accounts": "# accts", "n_brokers": "# brokers",
                "first_buy": "First buy", "last_buy": "Last buy",
            })
            cols = ["Logo", "Ticker", "Qty", "Avg cost", "Invested",
                    "Last price", "Current value", "P&L", "P&L %",
                    "# accts", "# brokers", "First buy", "Last buy"]
            st.dataframe(
                view[cols],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Logo": st.column_config.ImageColumn("•", width="small"),
                    "Ticker": st.column_config.TextColumn(width="small"),
                    "Qty": st.column_config.NumberColumn(format="%.4f"),
                    "Avg cost": st.column_config.NumberColumn(format="$%.2f"),
                    "Invested": st.column_config.NumberColumn(format="$%.2f"),
                    "Last price": st.column_config.NumberColumn(format="$%.2f"),
                    "Current value": st.column_config.NumberColumn(format="$%.2f"),
                    "P&L": st.column_config.NumberColumn(format="$%.2f"),
                    "P&L %": st.column_config.NumberColumn(format="%.2f%%"),
                    "First buy": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "Last buy": st.column_config.DateColumn(format="YYYY-MM-DD"),
                },
            )


# ─── TAB 3: Stocks performance ───────────────────────────────────────────────
with tab_perf:
    st.subheader("Stocks performance")
    st.caption("How each pick has performed, ranked best → worst. "
               "Uses your cost-weighted buy date to today; respects the sidebar "
               "Tags/Accounts/Brokers filters and the Live-prices toggle.")

    perf_tx = _apply_filters(_all_transactions(), start=None, end=None,
                             tags=flt_tags, accounts=flt_accounts, brokers=flt_brokers)
    close_hist = perf.load_close_history(APP_ROOT)

    if perf_tx.empty:
        st.info("No transactions match the current filters.")
    else:
        perf_tickers = sorted(perf_tx["ticker"].unique().tolist())
        quotes_perf = _quotes_for(perf_tickers, live_mode)
        prices_perf = {t: q.price for t, q in quotes_perf.items()}
        scored = perf.scorecard(perf_tx, prices_perf)
        scored = perf.benchmark_comparison(scored, close_hist, benchmark="VOO")

        priced = scored[scored["current_price"].notna()].copy()
        ranked = priced[priced["annualized_pct"].notna()].copy()
        n_new = int((priced["category"] == perf.CATEGORY_NEW).sum())

        if priced.empty:
            if not live_mode:
                st.warning("No current prices in the cache for these tickers. "
                           "Turn on **Live prices** in the sidebar to compute returns.")
            else:
                st.warning("Couldn't fetch live prices (network blocked?). "
                           "Returns can't be computed right now.")

        if priced.empty:
            st.info("Nothing to rank yet.")
        else:
            # ── 1. Category buckets ──────────────────────────────────────────
            st.markdown("#### Verdict on your picks (annualized return per year)")
            bc1, bc2, bc3 = st.columns(3)
            for col, cat in ((bc1, perf.CATEGORY_GOOD),
                             (bc2, perf.CATEGORY_AVERAGE),
                             (bc3, perf.CATEGORY_POOR)):
                sub = ranked[ranked["category"] == cat]
                inv = float(sub["invested"].sum())
                desc = {"Good": "≥ +20%/yr", "Average": "0–20%/yr", "Poor": "< 0%/yr"}[cat]
                col.metric(f"{cat} · {desc}", f"{len(sub)} stocks",
                           f"${inv:,.0f} invested", delta_color="off")
            if n_new:
                st.caption(f"➕ {n_new} holding(s) held under 1 year are shown in the "
                           "table below with total return only — too new to annualize.")

            if ranked.empty:
                st.info("No holding has a full year of history yet, so there's "
                        "nothing to annualize. See total returns in the table below.")

            # ── 2. Ranked bar chart (best → worst) ───────────────────────────
            if not ranked.empty:
                st.markdown("#### Ranking — best to worst")
                chart_df = ranked[["ticker", "annualized_pct", "category",
                                   "total_return_pct", "invested", "current_value"]].copy()
                bars = (
                    alt.Chart(chart_df)
                    .mark_bar(cornerRadius=3)
                    .encode(
                        x=alt.X("annualized_pct:Q", title="Annualized return (%/yr)"),
                        y=alt.Y("ticker:N", sort="-x", title=None),
                        color=alt.Color(
                            "category:N",
                            scale=alt.Scale(
                                domain=[perf.CATEGORY_GOOD, perf.CATEGORY_AVERAGE, perf.CATEGORY_POOR],
                                range=[GREEN, ORANGE, RED]),
                            legend=alt.Legend(orient="top", title=None)),
                        tooltip=[
                            alt.Tooltip("ticker:N", title="Ticker"),
                            alt.Tooltip("annualized_pct:Q", title="Annualized %/yr", format=".1f"),
                            alt.Tooltip("total_return_pct:Q", title="Total return %", format=".1f"),
                            alt.Tooltip("invested:Q", title="Invested", format="$,.0f"),
                            alt.Tooltip("current_value:Q", title="Current value", format="$,.0f"),
                        ],
                    )
                    .properties(height=max(180, 22 * len(chart_df)))
                    .configure_view(strokeWidth=0)
                )
                st.altair_chart(bars, use_container_width=True)

                # Best / worst callouts.
                best, worst = ranked.iloc[0], ranked.iloc[-1]
                wc1, wc2 = st.columns(2)
                wc1.success(f"🏆 **Best:** {best['ticker']} · "
                            f"{best['annualized_pct']:+.1f}%/yr "
                            f"({best['total_return_pct']:+.1f}% total)")
                wc2.error(f"🐢 **Worst:** {worst['ticker']} · "
                          f"{worst['annualized_pct']:+.1f}%/yr "
                          f"({worst['total_return_pct']:+.1f}% total)")

            # ── 3. Key indicators table (incl. decision quality vs S&P 500) ──
            st.markdown("#### Key indicators per stock")
            st.caption("**vs S&P 500** compares your annualized return to VOO over "
                       "the same holding window — positive means the pick beat just "
                       "buying the index (good stock-picking).")
            tbl = priced.copy()
            tbl["beat"] = tbl["beat_market"].map(
                lambda b: "✅ Beat" if b is True else ("❌ Lagged" if b is False else "—"))
            show = tbl[[
                "ticker", "category", "invested", "current_value", "pnl",
                "total_return_pct", "annualized_pct", "holding_years",
                "benchmark_annualized_pct", "alpha_pp", "beat", "weighted_buy_date",
            ]].rename(columns={
                "ticker": "Ticker", "category": "Verdict", "invested": "Invested",
                "current_value": "Current value", "pnl": "P&L",
                "total_return_pct": "Total %", "annualized_pct": "Annualized %/yr",
                "holding_years": "Years held", "benchmark_annualized_pct": "S&P500 %/yr",
                "alpha_pp": "vs S&P500 (pp)", "beat": "Decision",
                "weighted_buy_date": "Avg buy date",
            })
            st.dataframe(
                show, hide_index=True, use_container_width=True,
                column_config={
                    "Ticker": st.column_config.TextColumn(width="small"),
                    "Invested": st.column_config.NumberColumn(format="$%.0f"),
                    "Current value": st.column_config.NumberColumn(format="$%.0f"),
                    "P&L": st.column_config.NumberColumn(format="$%.0f"),
                    "Total %": st.column_config.NumberColumn(format="%.1f%%"),
                    "Annualized %/yr": st.column_config.NumberColumn(format="%.1f%%"),
                    "Years held": st.column_config.NumberColumn(format="%.2f"),
                    "S&P500 %/yr": st.column_config.NumberColumn(format="%.1f%%"),
                    "vs S&P500 (pp)": st.column_config.NumberColumn(format="%.1f"),
                    "Avg buy date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                },
            )
            beat_n = int((tbl["beat_market"] == True).sum())  # noqa: E712
            rated = int(tbl["beat_market"].isin([True, False]).sum())
            if rated:
                st.caption(f"You beat the S&P 500 on **{beat_n} of {rated}** "
                           f"rated holdings ({beat_n / rated * 100:.0f}%).")

            # ── 4. Yearly return per stock (price history) ───────────────────
            st.markdown("#### How each stock returned, year by year")
            if close_hist.empty:
                st.info("No price history yet. Run `python history.py` to build "
                        "`data/history/close_prices.csv`, then reload.")
            else:
                held = [t for t in priced["ticker"] if t in close_hist.columns]
                ymat = perf.yearly_return_matrix(close_hist, held)
                if ymat.empty:
                    st.caption("Not enough history to compute yearly returns.")
                else:
                    long = (ymat.reset_index()
                            .melt(id_vars="index", var_name="year", value_name="ret")
                            .rename(columns={"index": "ticker"}).dropna(subset=["ret"]))
                    long["label"] = long["ret"].map(lambda v: f"{v:+.0f}%")
                    heat = (
                        alt.Chart(long)
                        .mark_rect(stroke="white", strokeWidth=1)
                        .encode(
                            x=alt.X("year:O", title=None,
                                    axis=alt.Axis(labelFontWeight="bold", orient="top")),
                            y=alt.Y("ticker:N", title=None, sort=held),
                            color=alt.Color(
                                "ret:Q", title="Year return %",
                                scale=alt.Scale(scheme="redyellowgreen", domainMid=0),
                                legend=alt.Legend(orient="bottom", gradientLength=240)),
                            tooltip=[
                                alt.Tooltip("ticker:N"),
                                alt.Tooltip("year:O", title="Year"),
                                alt.Tooltip("ret:Q", title="Return %", format="+.1f"),
                            ],
                        )
                        .properties(height=max(180, 24 * len(held)))
                    )
                    text = (
                        alt.Chart(long)
                        .mark_text(fontSize=10)
                        .encode(
                            x=alt.X("year:O"), y=alt.Y("ticker:N", sort=held),
                            text="label:N",
                            color=alt.condition(
                                "abs(datum.ret) > 60", alt.value("white"), alt.value("#1e293b")),
                        )
                    )
                    st.altair_chart(
                        (heat + text).resolve_scale(color="independent")
                        .configure_view(strokeWidth=0),
                        use_container_width=True,
                    )

            # ── 5. Lump sum vs monthly DCA (the "9th of every month" question) ─
            st.markdown("#### Lump sum vs buying monthly")
            st.caption("Would investing a fixed amount on the same day each month "
                       "have beaten putting it all in at once? Simulated on actual "
                       "daily closes.")
            if close_hist.empty:
                st.info("Needs price history — run `python history.py` first.")
            else:
                sim_tickers = [t for t in (["VOO"] if "VOO" in close_hist.columns else [])
                               ] + [t for t in priced["ticker"] if t in close_hist.columns
                                    and t != "VOO"]
                if not sim_tickers:
                    st.caption("No held tickers have price history to simulate.")
                else:
                    dc1, dc2, dc3, dc4 = st.columns([2, 1, 1, 1])
                    sim_ticker = dc1.selectbox("Ticker", sim_tickers, key="dca_ticker")
                    sim_amt = dc2.number_input("Monthly $", min_value=50, value=1000,
                                               step=50, key="dca_amt")
                    hist_min = close_hist[sim_ticker].dropna().index.min().date()
                    default_start = max(hist_min, date(2020, 1, 1))
                    sim_start = dc3.date_input("Start", value=default_start,
                                               min_value=hist_min,
                                               max_value=close_hist.index.max().date(),
                                               key="dca_start")
                    sim_day = dc4.number_input("Day of month", min_value=1, max_value=28,
                                               value=9, key="dca_day")
                    comp = perf.simulate_lump_vs_dca(
                        close_hist, sim_ticker, float(sim_amt), sim_start,
                        day_of_month=int(sim_day))
                    if comp is None:
                        st.caption("Not enough price history for that window.")
                    else:
                        st.caption(f"{comp.n_buys} monthly buys of ${comp.monthly_amount:,.0f} "
                                   f"= ${comp.dca.invested:,.0f} total, "
                                   f"{comp.start} → {comp.end}.")
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Lump sum value",
                                  f"${comp.lump.final_value:,.0f}",
                                  f"{comp.lump.return_pct:+.1f}%")
                        m2.metric(f"Monthly (DCA, {comp.day_of_month}th)",
                                  f"${comp.dca.final_value:,.0f}",
                                  f"{comp.dca.return_pct:+.1f}%")
                        diff = comp.dca.final_value - comp.lump.final_value
                        m3.metric("Winner", comp.winner, f"${diff:+,.0f} vs lump",
                                  delta_color="normal" if comp.winner == "DCA" else "inverse")
                        curve = comp.curve.copy()
                        line = (
                            alt.Chart(curve)
                            .mark_line()
                            .encode(
                                x=alt.X("date:T", title=None),
                                y=alt.Y("value:Q", title="Position value (USD)"),
                                color=alt.Color("strategy:N", title=None,
                                                scale=alt.Scale(
                                                    domain=["Lump sum", "DCA"],
                                                    range=[BLUE, ORANGE]),
                                                legend=alt.Legend(orient="top")),
                                tooltip=[
                                    alt.Tooltip("date:T", title="Date"),
                                    alt.Tooltip("strategy:N", title="Strategy"),
                                    alt.Tooltip("value:Q", title="Value", format="$,.0f"),
                                ],
                            )
                            .properties(height=300)
                            .configure_view(strokeWidth=0)
                        )
                        st.altair_chart(line, use_container_width=True)
                        st.caption("Note: lump sum deploys the full total on the start "
                                   "date, so in a steadily rising market it usually wins; "
                                   "monthly buying mainly cuts the risk of a bad entry.")


# ─── TAB 4: Single stock detail ──────────────────────────────────────────────
def _render_single_stock(ticker: str) -> None:
    """Render the full per-stock view: header, metrics, LT/ST chips,
    per-account rollup, transactions, and scatter chart."""
    _stock_header(ticker)

    lots = portfolio.lots_global(APP_ROOT, ticker)
    if lots.empty:
        st.info(f"No transactions for {ticker}.")
        return

    quotes = _quotes_for([ticker], live_mode)
    q = quotes.get(ticker)

    net_qty = float(lots["quantity"].sum())
    net_invested = float(lots["cost_basis"].sum())
    avg_cost = (net_invested / net_qty) if net_qty else 0.0
    current_price = q.price if q else float("nan")
    current_value = (net_qty * current_price) if pd.notna(current_price) else float("nan")
    pnl = current_value - net_invested if pd.notna(current_value) else float("nan")
    pct = (pnl / net_invested * 100.0) if (pd.notna(pnl) and net_invested) else float("nan")
    n_buys = int((lots["quantity"] > 0).sum())
    n_sells = int((lots["quantity"] < 0).sum())

    mc = st.columns(6)
    mc[0].metric("Holding", f"{net_qty:,.4f}")
    mc[1].metric("Invested", f"${net_invested:,.2f}")
    mc[2].metric("Avg cost", f"${avg_cost:,.2f}")
    mc[3].metric("Last price", f"${current_price:,.2f}" if pd.notna(current_price) else "—")
    mc[4].metric("Current value", f"${current_value:,.2f}" if pd.notna(current_value) else "—")
    if pd.notna(pnl):
        mc[5].metric("Unrealized P&L", f"${pnl:,.2f}", f"{pct:+.2f}%")
    else:
        mc[5].metric("Unrealized P&L", "—")

    open_buys = lots[lots["quantity"] > 0]
    if "tax_term" in open_buys.columns and not open_buys.empty:
        lt_inv = float(open_buys.loc[open_buys["tax_term"] == "long_term", "cost_basis"].sum())
        st_inv = float(open_buys.loc[open_buys["tax_term"] == "short_term", "cost_basis"].sum())
        tot = lt_inv + st_inv
        if tot > 0:
            st.markdown(
                f'<div style="margin: 6px 0 18px;">'
                f'<span class="pill pill-lt">LONG-TERM '
                f'${lt_inv:,.2f} ({lt_inv/tot*100:.1f}%)</span>'
                f'<span class="pill pill-st">SHORT-TERM '
                f'${st_inv:,.2f} ({st_inv/tot*100:.1f}%)</span>'
                f'<span class="pill {"pill-pos" if pd.notna(pnl) and pnl >= 0 else "pill-neg"}">'
                f'{n_buys} buys · {n_sells} sells</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    per_acct = (
        lots.groupby(["broker", "account"], as_index=False)
        .agg(qty=("quantity", "sum"),
              invested=("cost_basis", "sum"),
              buys=("action", lambda s: int((s == "Buy").sum())),
              sells=("action", lambda s: int((s == "Sell").sum())),
              first=("purchase_date", "min"),
              last=("purchase_date", "max"))
    )
    per_acct["avg_cost"] = per_acct.apply(
        lambda r: r["invested"] / r["qty"] if r["qty"] else 0.0, axis=1
    )
    if pd.notna(current_price):
        per_acct["current_value"] = per_acct["qty"] * current_price
        per_acct["pnl"] = per_acct["current_value"] - per_acct["invested"]
        per_acct["pnl_pct"] = per_acct.apply(
            lambda r: r["pnl"] / r["invested"] * 100.0 if r["invested"] else 0.0, axis=1
        )
    st.subheader("Per-account holdings")
    cols_pa = ["broker", "account", "qty", "avg_cost", "invested",
               "buys", "sells", "first", "last"]
    if "current_value" in per_acct.columns:
        cols_pa += ["current_value", "pnl", "pnl_pct"]
    st.dataframe(
        per_acct[cols_pa],
        hide_index=True,
        use_container_width=True,
        column_config={
            "qty": st.column_config.NumberColumn("Qty", format="%.4f"),
            "avg_cost": st.column_config.NumberColumn("Avg cost", format="$%.2f"),
            "invested": st.column_config.NumberColumn("Invested", format="$%.2f"),
            "current_value": st.column_config.NumberColumn("Current", format="$%.2f"),
            "pnl": st.column_config.NumberColumn("P&L", format="$%.2f"),
            "pnl_pct": st.column_config.NumberColumn("P&L %", format="%.2f%%"),
            "first": st.column_config.DateColumn("First", format="YYYY-MM-DD"),
            "last": st.column_config.DateColumn("Last", format="YYYY-MM-DD"),
            "buys": st.column_config.NumberColumn("Buys"),
            "sells": st.column_config.NumberColumn("Sells"),
        },
    )

    st.subheader("All transactions")
    cols_tx = ["purchase_date", "action", "quantity", "purchase_price",
               "cost_basis", "broker", "account", "tag"]
    if "tax_term" in lots.columns:
        cols_tx.append("tax_term")
    tx_show = lots[cols_tx].rename(columns={
        "purchase_date": "Date", "action": "Action", "quantity": "Qty",
        "purchase_price": "Price", "cost_basis": "Cost",
        "broker": "Broker", "account": "Account",
        "tag": "Tag", "tax_term": "Tax term",
    })

    def _row_color_tx(row):
        bg = "rgba(16,185,129,0.08)" if row["Action"] == "Buy" else "rgba(239,68,68,0.08)"
        return [f"background-color: {bg}"] * len(row)

    styler_tx = (
        tx_show.style
        .apply(_row_color_tx, axis=1)
        .format({"Qty": "{:+.4f}", "Price": "${:,.4f}", "Cost": "${:,.2f}"})
    )
    st.dataframe(
        styler_tx, hide_index=True, use_container_width=True,
        column_config={"Date": st.column_config.DateColumn(format="YYYY-MM-DD")},
    )

    if len(lots) > 1:
        scatter_df = lots.assign(
            Side=lots["action"],
            AbsQty=lots["quantity"].abs(),
        )
        color_field = "tax_term:N" if "tax_term" in scatter_df.columns else "Side:N"
        color_scale = (
            alt.Scale(domain=["long_term", "short_term"], range=[BLUE, ORANGE])
            if color_field == "tax_term:N"
            else alt.Scale(domain=["Buy", "Sell"], range=[GREEN, RED])
        )
        scatter = (
            alt.Chart(scatter_df)
            .mark_point(opacity=0.85, stroke="white", strokeWidth=1.2, filled=True)
            .encode(
                x=alt.X("purchase_date:T", title="Date"),
                y=alt.Y("purchase_price:Q", title="Price (USD)"),
                size=alt.Size("AbsQty:Q", title="Qty",
                              scale=alt.Scale(range=[60, 700])),
                color=alt.Color(color_field, scale=color_scale,
                                legend=alt.Legend(title=color_field.split(":")[0])),
                shape=alt.Shape(
                    "Side:N",
                    scale=alt.Scale(domain=["Buy", "Sell"],
                                    range=["circle", "triangle-down"]),
                    legend=alt.Legend(title="Action"),
                ) if color_field == "tax_term:N" else alt.Undefined,
                tooltip=[
                    alt.Tooltip("purchase_date:T", title="Date"),
                    "Side",
                    alt.Tooltip("AbsQty:Q", title="Qty", format=",.4f"),
                    alt.Tooltip("purchase_price:Q", title="Price", format="$,.2f"),
                    alt.Tooltip("cost_basis:Q", title="Cost", format="$,.2f"),
                    "broker", "account", "tag",
                ] + (["tax_term"] if "tax_term" in scatter_df.columns else []),
            )
            .properties(
                height=320,
                title=alt.TitleParams(
                    text=f"{ticker} — every transaction across all accounts",
                    fontSize=14, fontWeight="bold", color="#1e293b",
                ),
            )
            .configure_view(strokeWidth=0)
            .configure_axis(grid=True, gridColor="#f1f5f9",
                            domainColor="#cbd5e1", tickColor="#cbd5e1")
        )
        st.altair_chart(scatter, use_container_width=True)


with tab_single:
    _render_status_badge(live_mode, cache_meta)

    if not all_tickers:
        st.info("No data yet.")
    else:
        picked = st.selectbox(
            "Pick a stock", all_tickers, key="single_stock",
            help="Search any ticker held in any account.",
        )
        _render_single_stock(picked)


# ─── Pinned ticker tabs (one per ticker in data/_pinned.json) ────────────────
for _tab, _ticker in zip(pinned_tabs, pinned_existing):
    with _tab:
        _render_status_badge(live_mode, cache_meta)
        _render_single_stock(_ticker)


# ─── TAB 3: Transactions (consolidated buy/sell ledger) ──────────────────────
with tab_tx:
    _render_status_badge(live_mode, cache_meta)
    st.markdown("### Transactions")
    st.caption("Every buy/sell across all accounts. Fidelity position snapshots "
               "are excluded — they carry no trade date.")

    trades = all_tx
    if not all_tx.empty and "row_type" in all_tx.columns:
        trades = all_tx[all_tx["row_type"] != "position"].copy()
    if trades.empty:
        st.info("No transactions yet.")
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
            qt = pc3.selectbox("Quarter", [1, 2, 3, 4],
                               format_func=lambda q: f"Q{q}", key="tx_quarter")
            ds, de = _period_range(period, tmin, tmax, today, yr, qt)
        elif period == "Custom":
            ds = pc2.date_input("Start", value=tmin, min_value=tmin,
                                max_value=tmax, key="tx_start")
            de = pc3.date_input("End", value=tmax, min_value=tmin,
                                max_value=tmax, key="tx_end")
        else:
            ds, de = _period_range(period, tmin, tmax, today)
        st.markdown('</div>', unsafe_allow_html=True)

        store = txn_tags.load(APP_ROOT)
        known_tags = txn_tags.all_tag_names(store)

        f1, f2, f3, f4 = st.columns(4)
        accts = sorted(trades["account"].dropna().unique().tolist())
        brks = sorted(trades["broker"].dropna().unique().tolist())
        tkrs = sorted(trades["ticker"].dropna().unique().tolist())
        sel_accounts = f1.multiselect("Accounts", accts, default=[], key="tx_acct")
        sel_brokers = f2.multiselect("Brokers", brks, default=[], key="tx_brk")
        sel_tickers = f3.multiselect("Tickers", tkrs, default=[], key="tx_tkr")
        sel_tagfilter = f4.multiselect("Tags", known_tags, default=[], key="tx_tagfilter")

        view = _apply_filters(trades, start=ds, end=de, tags=None,
                              accounts=sel_accounts or None,
                              brokers=sel_brokers or None)
        if sel_tickers:
            view = view[view["ticker"].isin(sel_tickers)]

        act1, _ = st.columns([1, 3])
        action_choice = act1.radio("Show", ["All", "Buy", "Sell"], horizontal=True,
                                   key="tx_action")
        if action_choice != "All":
            view = view[view["action"] == action_choice]

        if sel_tagfilter and "txn_id" in view.columns:
            wanted = {tid for tid, tg in store.items() if set(tg) & set(sel_tagfilter)}
            view = view[view["txn_id"].isin(wanted)]

        view = view.copy()
        view["amount"] = view["quantity"] * view["purchase_price"]

        # ── Quantity & amount range filters (by magnitude, so sells count too) ──
        with st.expander("Range filters — quantity & amount"):
            st.caption("Filtered by absolute size, so sells (stored negative) are "
                       "matched by their magnitude. Leave a bound at 0 to disable it.")
            rc1, rc2, rc3, rc4 = st.columns(4)
            q_lo = rc1.number_input("Min qty (shares)", min_value=0.0, value=0.0,
                                    step=1.0, key="tx_qty_lo")
            q_hi = rc2.number_input("Max qty (0 = no max)", min_value=0.0, value=0.0,
                                    step=1.0, key="tx_qty_hi")
            a_lo = rc3.number_input("Min amount ($)", min_value=0.0, value=0.0,
                                    step=100.0, key="tx_amt_lo")
            a_hi = rc4.number_input("Max amount (0 = no max)", min_value=0.0, value=0.0,
                                    step=100.0, key="tx_amt_hi")

        abs_qty = view["quantity"].abs()
        abs_amt = view["amount"].abs()
        mask = pd.Series(True, index=view.index)
        if q_lo > 0:
            mask &= abs_qty >= q_lo
        if q_hi > 0:
            mask &= abs_qty <= q_hi
        if a_lo > 0:
            mask &= abs_amt >= a_lo
        if a_hi > 0:
            mask &= abs_amt <= a_hi
        view = view[mask]

        view = view.sort_values("purchase_date", ascending=False)

        # Cash totals exclude share transfers and corporate-action distributions
        # (e.g. stock splits) — those are real rows in the ledger but not cash.
        if "row_type" in view.columns:
            cash = view[~view["row_type"].isin(["transfer", "distribution", "position"])]
        else:
            cash = view
        bought = cash.loc[cash["quantity"] > 0, "amount"].sum()
        sold = -cash.loc[cash["quantity"] < 0, "amount"].sum()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Transactions", f"{len(view):,}")
        m2.metric("Bought (cash)", f"${bought:,.0f}")
        m3.metric("Sold (cash)", f"${sold:,.0f}")
        m4.metric("Net invested", f"${bought - sold:,.0f}")
        st.caption(f"Range: {ds:%Y-%m-%d} → {de:%Y-%m-%d}  ·  {len(view):,} rows  ·  "
                   "cash totals exclude transfers & stock-split distributions")

        ids = (view["txn_id"].tolist() if "txn_id" in view.columns
               else [""] * len(view))

        # ── Bulk tagging: apply/remove one tag across the whole filtered set ──
        st.markdown("#### Tags")
        st.caption("Tags are saved to data/_txn_tags.json and survive restarts & "
                   "rebuilds. Edit the **Tags** column inline (comma-separated) and "
                   "click *Save tags*, or bulk-apply a tag to every row in view.")
        bc1, bc2, bc3 = st.columns([2, 1, 1])
        bulk_tag = bc1.text_input("Tag", key="tx_bulk_tag",
                                  placeholder="e.g. long-term, RSU, review").strip()
        if bc2.button(f"➕ Add to {len(ids)} rows", use_container_width=True,
                      disabled=not (bulk_tag and ids)):
            n = txn_tags.add_to_many(store, ids, bulk_tag)
            txn_tags.save(APP_ROOT, store)
            st.success(f"Added '{bulk_tag}' to {n} transactions.")
            st.rerun()
        if bc3.button(f"➖ Remove from {len(ids)} rows", use_container_width=True,
                      disabled=not (bulk_tag and ids)):
            n = txn_tags.remove_from_many(store, ids, bulk_tag)
            txn_tags.save(APP_ROOT, store)
            st.success(f"Removed '{bulk_tag}' from {n} transactions.")
            st.rerun()

        # ── Per-row editable table ──
        cols = ["purchase_date", "account", "broker", "ticker", "action",
                "row_type", "quantity", "purchase_price", "amount"]
        cols = [c for c in cols if c in view.columns]
        disp = view[cols].rename(columns={
            "purchase_date": "Date", "account": "Account", "broker": "Broker",
            "ticker": "Ticker", "action": "Action", "row_type": "Type",
            "quantity": "Qty", "purchase_price": "Price", "amount": "Amount",
        })
        disp.insert(0, "Tags", [", ".join(store.get(t, [])) for t in ids])
        locked = [c for c in disp.columns if c != "Tags"]

        edited = st.data_editor(
            disp, hide_index=True, use_container_width=True, height=520,
            num_rows="fixed", disabled=locked, key="tx_editor",
            column_config={
                "Tags": st.column_config.TextColumn(
                    "Tags", help="Comma-separated. Leave empty to clear all tags on the row.",
                    width="medium"),
                "Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "Qty": st.column_config.NumberColumn(format="%+.4f"),
                "Price": st.column_config.NumberColumn(format="$%.4f"),
                "Amount": st.column_config.NumberColumn(format="$%.2f"),
            },
        )
        sc1, sc2 = st.columns([1, 3])
        if sc1.button("💾 Save tags", type="primary", use_container_width=True):
            for tid, val in zip(ids, edited["Tags"].tolist()):
                if not tid:
                    continue
                parsed = [p.strip() for p in str(val).replace(";", ",").split(",")]
                txn_tags.set_for(store, tid, parsed)
            txn_tags.save(APP_ROOT, store)
            st.success("Tags saved.")
            st.rerun()

        dl = disp.copy()
        st.download_button(
            "Download CSV (with tags)", dl.to_csv(index=False).encode("utf-8"),
            file_name=f"transactions_{ds:%Y%m%d}_{de:%Y%m%d}.csv",
            mime="text/csv", use_container_width=False,
        )

        # ── Tag summary: a quick report basis across the WHOLE ledger ──
        with st.expander("Tag summary (cash buys/sells per tag, all dates)"):
            if not known_tags:
                st.caption("No tags yet. Add some above to start building tag-based reports.")
            else:
                rows = []
                for name in known_tags:
                    tids = [tid for tid, tg in store.items() if name in tg]
                    sub = trades[trades["txn_id"].isin(tids)].copy()
                    sub["amount"] = sub["quantity"] * sub["purchase_price"]
                    if "row_type" in sub.columns:
                        c = sub[~sub["row_type"].isin(["transfer", "distribution", "position"])]
                    else:
                        c = sub
                    rows.append({
                        "Tag": name,
                        "Transactions": len(sub),
                        "Bought": round(c.loc[c["quantity"] > 0, "amount"].sum(), 2),
                        "Sold": round(-c.loc[c["quantity"] < 0, "amount"].sum(), 2),
                    })
                summary_df = pd.DataFrame(rows)
                st.dataframe(
                    summary_df, hide_index=True, use_container_width=True,
                    column_config={
                        "Bought": st.column_config.NumberColumn(format="$%.2f"),
                        "Sold": st.column_config.NumberColumn(format="$%.2f"),
                    },
                )
