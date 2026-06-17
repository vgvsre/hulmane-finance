"""Build the app's data files from a live Robinhood snapshot.

The container can't reach the Robinhood MCP connector (it's agent-only), so the
agent pulls Venu's positions + orders via MCP and saves the raw JSON under
``data/live/raw/``; this module transforms those into the files the dashboard
reads:

    data/live/raw/orders_<acct>*.json   (in)  one or more order pages per account
    data/live/raw/positions_<acct>.json (in)  current holdings w/ avg cost
    data/live/raw/splits.json           (in)  stock splits (no order record exists)
        |  python -m src.snapshot
        v
    data/formated/robinhood.csv   transaction ledger (portfolio.load_tag schema)
    data/live/positions.json      current holdings (qty + avg cost) per account
    data/live/_refreshed_at.json  refresh timestamp + per-account counts

Only the four accounts under Venu's Robinhood login are included. Holdings and
returns use Robinhood's average_buy_price (correct even for transferred-in
shares); the ledger drives the Transactions page and invested-vs-sold-by-year.
"""
from __future__ import annotations

import csv
import glob
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

NICK = {
    "575947536": "Venu Main",
    "632375721": "Hulmane",
    "756962569": "VMware",
    "971012356": "Agentic",
}

# placed_agent -> (txn_source, row_type)
AGENT_MAP = {
    "drip": ("dividend_reinvested", "dividend_reinvestment"),
    "recurring": ("recurring_cash", "trade"),
    "user": ("manual_cash", "trade"),
    "agentic": ("agentic", "trade"),
    "": ("cash", "trade"),
}

LEDGER_COLS = [
    "txn_id", "ticker", "quantity", "purchase_price", "purchase_date",
    "broker", "account", "action", "txn_source", "row_type", "source_file",
]


def _d(x) -> Decimal:
    try:
        return Decimal(str(x))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _num(x: Decimal) -> str:
    """Compact numeric string (no trailing zeros / dangling point)."""
    s = f"{x:f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _synth_id(*parts) -> str:
    """Deterministic, stable txn_id for rows with no Robinhood order id
    (DRIP/recurring rows seeded inline, splits). Stable across refreshes as
    long as the underlying fields don't change, so tags re-attach after a
    re-snapshot or a fresh git clone."""
    return "x" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:15]


def raw_dir(app_root: Path) -> Path:
    return Path(app_root) / "data" / "live" / "raw"


def live_dir(app_root: Path) -> Path:
    return Path(app_root) / "data" / "live"


def formated_dir(app_root: Path) -> Path:
    return Path(app_root) / "data" / "formated"


def _row_from_order(o: dict, account_no: str) -> dict:
    qty = _d(o.get("cumulative_quantity") or o.get("quantity"))
    price = _d(o.get("average_price") or o.get("price"))
    agent = o.get("placed_agent") or ""
    src, rtype = AGENT_MAP.get(agent, ("cash", "trade"))
    ts = o.get("last_transaction_at") or o.get("created_at") or ""
    signed = qty if o.get("side") == "buy" else -qty
    txn_id = o.get("id") or _synth_id(account_no, o.get("symbol", ""), ts[:10],
                                      _num(signed), _num(price), o.get("side", ""))
    return {
        "txn_id": txn_id,
        "ticker": o.get("symbol", ""),
        "quantity": _num(signed),
        "purchase_price": _num(price) if price else "0",
        "purchase_date": ts[:10],
        "broker": "robinhood",
        "account": NICK.get(account_no, account_no),
        "action": "Buy" if o.get("side") == "buy" else "Sell",
        "txn_source": src,
        "row_type": rtype,
        "source_file": f"mcp:{account_no}",
    }


def build(app_root: Path) -> dict:
    app_root = Path(app_root)
    rd = raw_dir(app_root)
    rows: list[dict] = []
    counts: dict[str, int] = {}

    for acct in NICK:
        n = 0
        for f in sorted(glob.glob(str(rd / f"orders_{acct}*.json"))):
            data = json.loads(Path(f).read_text())
            for o in data.get("data", {}).get("orders", []):
                rows.append(_row_from_order(o, acct))
                n += 1
        counts[NICK[acct]] = n

    # splits (no order record) -> positive share-adjustment rows
    splits_path = rd / "splits.json"
    n_split = 0
    if splits_path.exists():
        for s in json.loads(splits_path.read_text()).get("splits", []):
            acct = s["account_no"]
            rows.append({
                "txn_id": _synth_id(acct, s["ticker"], s["date"], "split"),
                "ticker": s["ticker"], "quantity": _num(_d(s["quantity"])),
                "purchase_price": "0", "purchase_date": s["date"], "broker": "robinhood",
                "account": NICK.get(acct, acct), "action": "Split",
                "txn_source": "split", "row_type": "split", "source_file": f"mcp:{acct}",
            })
            n_split += 1

    rows.sort(key=lambda r: (r["account"], r["purchase_date"], r["ticker"]))
    formated_dir(app_root).mkdir(parents=True, exist_ok=True)
    out_csv = formated_dir(app_root) / "robinhood.csv"
    with out_csv.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_COLS)
        w.writeheader()
        w.writerows(rows)

    # positions.json: flat list of holdings w/ avg cost
    positions: list[dict] = []
    for acct in NICK:
        pf = rd / f"positions_{acct}.json"
        if not pf.exists():
            continue
        for p in json.loads(pf.read_text()).get("data", {}).get("positions", []):
            positions.append({
                "account_no": acct,
                "nickname": NICK[acct],
                "symbol": p["symbol"],
                "quantity": float(_d(p.get("quantity"))),
                "average_buy_price": float(_d(p.get("average_buy_price"))),
            })
    live_dir(app_root).mkdir(parents=True, exist_ok=True)
    (live_dir(app_root) / "positions.json").write_text(json.dumps(positions, indent=2))

    meta = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "accounts": counts,
        "splits": n_split,
        "ledger_rows": len(rows),
        "positions": len(positions),
    }
    (live_dir(app_root) / "_refreshed_at.json").write_text(json.dumps(meta, indent=2))
    return meta


def main() -> int:
    app_root = Path(__file__).resolve().parent.parent
    meta = build(app_root)
    print(f"Ledger rows : {meta['ledger_rows']}  -> data/formated/robinhood.csv")
    print(f"Positions   : {meta['positions']}    -> data/live/positions.json")
    print(f"Splits      : {meta['splits']}")
    print("By account  : " + ", ".join(f"{k}={v}" for k, v in meta["accounts"].items()))
    print(f"Refreshed   : {meta['refreshed_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
