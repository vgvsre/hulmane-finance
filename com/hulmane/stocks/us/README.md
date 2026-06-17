# Hulmane — US Stocks

Streamlit dashboard for tracking the **Venu Robinhood** US-stock accounts, fed
by a **live Robinhood snapshot** and live Yahoo Finance prices. Runs in a
container on **port 8182**.

## How live data works

The Robinhood MCP connector is only reachable by the Claude agent, **not** by
the running app. So the data flow is:

```
Robinhood MCP (agent) ──▶ data/live/raw/*.json   (positions + orders, 4 Venu accounts)
        │  python app.py snapshot
        ▼
   data/formated/robinhood.csv   transaction ledger (buys/sells/splits/DRIP)
   data/live/positions.json      current holdings + Robinhood average cost
        │  python history.py     (daily closes via yfinance)
        ▼
   data/history/close_prices.csv
        ▼
   dashboard (container) reads the files + fetches live prices from Yahoo
```

- **Holdings & returns** use `positions.json` (Robinhood average cost) — correct
  even for shares transferred in from another account.
- **Activity & the Transactions page** use the order ledger. Shares transferred
  in have no buy row, so "invested by year" can understate them (flagged in-app).
- To refresh Robinhood data, ask the agent to re-pull and run `python app.py
  snapshot`; the container picks it up via the bind-mounted `data/` dir.

## Layout

```
us/
├── app.py              # CLI: snapshot / price / report / dashboard
├── dashboard.py        # Streamlit UI (Home / Transactions / Single stock)
├── Dockerfile, docker-compose.yml
├── config.json         # history start date, excluded_tickers
├── data/
│   ├── live/raw/       # raw MCP dumps (orders_*, positions_*, splits.json)
│   ├── live/           # positions.json, _refreshed_at.json
│   ├── formated/       # robinhood.csv (the ledger the app reads)
│   ├── history/        # close_prices.csv
│   ├── _txn_tags.json  # per-transaction tags (survive refreshes)
│   └── _price_cache.json
└── src/
    ├── snapshot.py     # raw MCP dumps -> ledger + positions
    ├── portfolio.py    # ledger + positions loaders
    ├── pricing.py      # yfinance prices (disk-cached)
    ├── report.py       # activity aggregations
    ├── performance.py  # yearly returns + portfolio-vs-market
    ├── tags.py         # transaction tagging
    └── media.py        # ticker logos / auto-icons
```

## Run with Docker (port 8182)

```sh
cd com/hulmane/stocks/us
docker compose up -d --build
# open http://localhost:8182
```

`data/` is bind-mounted, so after a fresh snapshot the running container shows it
on the next refresh — no rebuild needed.

## Run locally (no Docker)

```sh
cd com/hulmane/stocks/us
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py snapshot        # build data files from data/live/raw
python history.py             # refresh close-price history (needs Yahoo access)
streamlit run dashboard.py    # serves on 8182 (see .streamlit/config.toml)
```

## CLI

```sh
python app.py snapshot                 # rebuild ledger + positions from data/live/raw
python app.py price AAPL MSFT NVDA     # ad-hoc live quote
python app.py report                   # tag P&L summary
python app.py dashboard                # launch Streamlit
```

## Dashboard tabs

| Tab             | What it shows |
|-----------------|---------------|
| **Home**        | Headline metrics, investment heatmap, invested-vs-sold by year, portfolio-vs-market since 2019, holdings, and how each stock returned year-by-year |
| **Transactions**| Full buy/sell/split/DRIP ledger with per-transaction tags + a tag-based cash report |
| **Single stock**| Current position (avg cost, value, unrealized P&L) + full transaction history for one ticker |

> Live prices need outbound HTTPS to `query1/query2.finance.yahoo.com`. Behind a
> proxy that blocks Yahoo, prices come back NaN — allowlist those hosts.
