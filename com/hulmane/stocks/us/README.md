# Hulmane — US Stocks

Python app for tracking US-market stock investments across multiple brokers
(Fidelity, E*Trade, Robinhood, …) with **tag-based cohorts** so you can see
how each batch of investments performs without merging older buys with newer
ones.

## Layout

```
us/
├── app.py              # CLI entry
├── dashboard.py        # Streamlit UI
├── requirements.txt
├── data/
│   ├── transactions/   # one CSV per tag — the app reads these
│   │   ├── jan26.csv
│   │   └── fidelity_may26.csv
│   ├── fedility/       # raw Fidelity exports go here (then run import-fidelity)
│   └── robinhood/      # raw Robinhood exports go here (then run import-robinhood)
├── reports/            # CSV + chart output (auto-created)
└── src/
    ├── pricing.py      # yfinance wrapper for live prices
    ├── portfolio.py    # tagged-CSV loader
    ├── report.py       # per-tag P&L
    ├── visualize.py    # matplotlib charts
    └── importers/
        ├── fidelity.py  # Fidelity Portfolio Positions importer
        └── robinhood.py # Robinhood transaction-history importer
```

## CSV schema (per tag)

Each file `data/transactions/<tag>.csv` represents one cohort. **Filename stem
becomes the tag.** Required columns:

```
ticker,quantity,purchase_price,purchase_date,broker
AAPL,10,185.50,2026-01-08,fidelity
```

Tags are kept distinct: an AAPL buy in `jan26.csv` is *not* averaged with an
AAPL buy in `may26.csv`.

## First-time setup

```sh
cd com/hulmane/stocks/us
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Quick start — UI

1. **Start the dashboard** (defaults to port 8501; pass `--server.port` to override):

   ```sh
   cd com/hulmane/stocks/us
   .venv/bin/streamlit run dashboard.py --server.port 44551
   ```

   You'll see:

   ```
   You can now view your Streamlit app in your browser.
   Local URL:   http://localhost:44551
   ```

2. **Open it in your browser:** http://localhost:44551
3. **Stop the server:** `Ctrl+C` in the terminal.

### Dashboard tabs

| Tab               | What it does                                                                |
|-------------------|-----------------------------------------------------------------------------|
| **Upload**        | Drop a tagged CSV (filename stem = tag) into `data/transactions/`           |
| **All-tag summary** | Live cross-tag P&L: invested vs current value, % return per cohort        |
| **Tag detail**    | Per-position breakdown for one tag, with pie chart and CSV report export    |
| **Live price**    | Ad-hoc `yfinance` lookup for any US ticker(s)                               |

> Live prices need outbound HTTPS to `query1.finance.yahoo.com` and
> `query2.finance.yahoo.com`. If you're inside a sandbox/proxy that blocks
> Yahoo Finance, you'll see "possibly delisted" errors and prices come back
> as NaN — allowlist those hosts (or run outside the sandbox).

## CLI

```sh
.venv/bin/python app.py list-tags
.venv/bin/python app.py price AAPL MSFT NVDA
.venv/bin/python app.py report                          # cross-tag summary
.venv/bin/python app.py report fidelity_may26           # detail for one tag
.venv/bin/python app.py viz                             # cross-tag charts
.venv/bin/python app.py viz fidelity_may26              # holdings breakdown
.venv/bin/python app.py upload my_export.csv may26      # generic CSV upload
.venv/bin/python app.py import-fidelity data/fedility fidelity_may26
.venv/bin/python app.py import-robinhood data/robinhood/<file>.csv robinhood_may26
.venv/bin/python app.py dashboard                       # launches Streamlit
```

Reports and charts land in `reports/` (CSV) and `reports/charts/` (PNG).

## Importing Fidelity exports

Drop the Fidelity *Portfolio Positions* CSV(s) into `data/fedility/`, then:

```sh
.venv/bin/python app.py import-fidelity data/fedility fidelity_may26
```

You can pass either a single file or the whole directory. The importer:
- handles UTF-8 BOM and trailing-comma rows Fidelity emits
- maps `Symbol → ticker`, `Quantity → quantity`, `Average Cost Basis → purchase_price`
- parses the export date from the filename (`May-28-2026` → `2026-05-28`)
- treats cash sweeps (FCASH, FDRXX, SPAXX, …) as $1.00 with no P&L

## Importing Robinhood exports

Drop the Robinhood *Account Activity* CSV into `data/robinhood/`, then:

```sh
.venv/bin/python app.py import-robinhood data/robinhood/<file>.csv robinhood_may26
```

Robinhood exports are full **transaction histories** (one row per event), not
position snapshots. The importer:
- emits one row per `Buy` (positive qty) and `Sell` (negative qty), so each
  cohort's `purchase_date` and `purchase_price` are preserved exactly as they
  occurred — sells naturally net out the cost basis
- handles multi-line cells (Robinhood embeds `CUSIP:` lines inside Description)
- skips, with a printed summary, all non-trade events:
  - `CDIV`, `DTAX`, `DFEE`, `SLIP` — dividend / lending cash
  - `ACH`, `RTP`, `ABIP` — bank transfers / promo cash
  - `ITRF` — internal Robinhood transfers
  - `ACATI` — incoming ACAT shares (no Robinhood-side cost basis)

If you want ACAT-transferred holdings tracked, look up their cost basis at the
prior broker and add a separate tagged CSV for them.
