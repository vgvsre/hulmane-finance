"""Robinhood transaction-history importer.

Robinhood's account export CSV ('Activity Date', 'Process Date', ..., 'Trans Code',
'Quantity', 'Price', 'Amount') contains years of transactions, one row per event.
Quirks:
- Multi-line cells (Description includes embedded newlines and a 'CUSIP: ...' line)
- Money values like '$1,463.65' or '($1,463.65)' for debits
- Many event types beyond Buy/Sell — see TRANS_CODES below

We keep only rows that affect cost basis at this broker:
    Buy, Sell                     -> emitted (Sell as negative quantity)

A Buy whose Description says "Dividend Reinvestment" (a DRIP — dividend cash
auto-reinvested into shares) is still emitted as a Buy (it is real cost basis),
but tagged via ``row_type="dividend_reinvestment"`` so reports/tags can single
it out. Plain trades carry ``row_type="trade"``.

We deliberately drop:
    CDIV, DTAX, DFEE, SLIP        -> dividend / lending cash events
    ACH, RTP, ABIP                -> bank transfers / promo cash
    ITRF                          -> internal transfers between RH accounts
    ACATI                         -> incoming ACAT shares with no cost basis

Multiple files in one import = multiple Robinhood accounts. Each row carries
an ``account`` label derived from the source filename's stem (truncated UUID).
You can supply friendly names via data/robinhood/_accounts.json:
    { "738c29e7-...": "Roth IRA", "bc3eb275-...": "Individual" }

Each row also carries:
    action       — "Buy" or "Sell" (for human-readable display alongside signed qty)
    source_file  — the CSV file the row came from (traceability)

A summary of skipped rows is returned alongside the parsed frame so the caller
can surface what was dropped.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

APP_COLS = ["ticker", "quantity", "purchase_price", "purchase_date", "broker",
            "account", "action", "row_type", "source_file"]

KEEP_CODES = {"Buy", "Sell"}
SPLIT_CODE = "SPL"  # stock-split share distribution: extra shares added, no cash
DRIP_MARKER = "dividend reinvestment"  # matched case-insensitively in Description
SKIP_CODES = {
    "CDIV", "DTAX", "DFEE", "SLIP",
    "ACH", "RTP",
    "ABIP",
    "ITRF",
    "ACATI",
}

ACCOUNT_MAP_FILENAME = "_accounts.json"
ACCOUNT_LABEL_LEN = 8  # how many UUID chars to use as default account label

_MONEY_RE = re.compile(r"[\$,]")


@dataclass
class ImportSummary:
    rows_emitted: int
    skipped_by_code: dict[str, int]
    unrecognized_codes: dict[str, int]
    accounts_seen: dict[str, int]
    dividend_reinvestments: int = 0


def _load_account_map(robinhood_dir: Path) -> dict[str, str]:
    p = robinhood_dir / ACCOUNT_MAP_FILENAME
    if not p.exists():
        return {}
    try:
        return {str(k): str(v) for k, v in json.loads(p.read_text()).items()}
    except Exception:
        return {}


def _account_label(file_path: Path, account_map: dict[str, str]) -> str:
    stem = file_path.stem
    return account_map.get(stem) or stem[:ACCOUNT_LABEL_LEN]


def _money(s) -> float:
    if s is None or pd.isna(s) or s == "":
        return float("nan")
    s = str(s).strip()
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    s = _MONEY_RE.sub("", s)
    try:
        v = float(s)
    except ValueError:
        return float("nan")
    return -v if neg else v


def _parse_date(s) -> date | None:
    if not s or pd.isna(s):
        return None
    try:
        return pd.to_datetime(str(s), format="%m/%d/%Y").date()
    except ValueError:
        return None


def _read_raw(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path, encoding="utf-8-sig", dtype=str, keep_default_na=False,
        engine="python", on_bad_lines="warn",
    )


def parse(path: Path, account_label: str) -> tuple[pd.DataFrame, ImportSummary]:
    raw = _read_raw(path)
    expected = {"Activity Date", "Instrument", "Trans Code", "Quantity", "Price"}
    missing = expected - set(raw.columns)
    if missing:
        raise ValueError(f"{path}: missing expected columns: {missing}")

    out_rows: list[dict] = []
    skipped: Counter[str] = Counter()
    unrecognized: Counter[str] = Counter()
    n_drip = 0

    for _, r in raw.iterrows():
        code = str(r.get("Trans Code", "")).strip()
        if not code:
            continue
        if code in SKIP_CODES:
            skipped[code] += 1
            continue
        # Stock split: Robinhood books the extra shares as an SPL row whose
        # Quantity is the *added* shares (e.g. AMZN 20:1 → 19× the held qty) and
        # whose Price/Amount are blank — no cash changes hands. Emitting it as a
        # zero-cost share addition makes the running share count match the broker
        # without distorting cost basis (invested $ unchanged, avg cost drops).
        if code == SPLIT_CODE:
            sym = str(r.get("Instrument", "")).strip().upper()
            qty = _money(r.get("Quantity"))
            d = _parse_date(r.get("Activity Date"))
            if not sym or pd.isna(qty) or qty == 0 or d is None:
                skipped[f"{code}:incomplete"] += 1
                continue
            out_rows.append(
                {
                    "ticker": sym,
                    "quantity": round(qty, 6),
                    "purchase_price": 0.0,
                    "purchase_date": d.isoformat(),
                    "broker": "robinhood",
                    "account": account_label,
                    "action": "Split",
                    "row_type": "split",
                    "source_file": path.name,
                }
            )
            continue
        if code not in KEEP_CODES:
            unrecognized[code] += 1
            continue

        sym = str(r.get("Instrument", "")).strip().upper()
        qty = _money(r.get("Quantity"))
        price = _money(r.get("Price"))
        d = _parse_date(r.get("Activity Date"))

        if not sym or pd.isna(qty) or pd.isna(price) or d is None or qty == 0 or price == 0:
            skipped[f"{code}:incomplete"] += 1
            continue

        # A Buy flagged "Dividend Reinvestment" in its Description is a DRIP.
        is_drip = code == "Buy" and DRIP_MARKER in str(r.get("Description", "")).lower()
        if is_drip:
            n_drip += 1

        signed_qty = qty if code == "Buy" else -qty
        out_rows.append(
            {
                "ticker": sym,
                "quantity": round(signed_qty, 6),
                "purchase_price": round(price, 4),
                "purchase_date": d.isoformat(),
                "broker": "robinhood",
                "account": account_label,
                "action": code,
                "row_type": "dividend_reinvestment" if is_drip else "trade",
                "source_file": path.name,
            }
        )

    df = pd.DataFrame(out_rows, columns=APP_COLS)
    summary = ImportSummary(
        rows_emitted=len(df),
        skipped_by_code=dict(skipped),
        unrecognized_codes=dict(unrecognized),
        accounts_seen={account_label: len(df)} if len(df) else {},
        dividend_reinvestments=n_drip,
    )
    return df, summary


def import_to_tag(app_root: Path, source: Path, tag: str) -> tuple[Path, ImportSummary]:
    source = Path(source)
    if source.is_dir():
        files = sorted(source.glob("*.csv"))
        account_map = _load_account_map(source)
    else:
        files = [source]
        account_map = _load_account_map(source.parent)
    if not files:
        raise FileNotFoundError(f"No CSV files at {source}")

    frames: list[pd.DataFrame] = []
    total_skipped: Counter[str] = Counter()
    total_unrecognized: Counter[str] = Counter()
    accounts_seen: Counter[str] = Counter()
    total_drip = 0

    for p in files:
        label = _account_label(p, account_map)
        df, summary = parse(p, account_label=label)
        frames.append(df)
        total_skipped.update(summary.skipped_by_code)
        total_unrecognized.update(summary.unrecognized_codes)
        accounts_seen.update(summary.accounts_seen)
        total_drip += summary.dividend_reinvestments

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=APP_COLS)
    if df.empty:
        raise ValueError(f"No Buy/Sell rows found in {[str(f) for f in files]}")

    # Cross-file dedupe: when multiple exports overlap (e.g. an "all-history"
    # export plus an incremental one for the same account), the same trade can
    # appear under different account labels. We keep the row whose source_file
    # contributed the most rows (the canonical, most-complete export).
    dup_keys = ["broker", "purchase_date", "ticker", "action",
                "quantity", "purchase_price"]
    file_size_rank = (
        df.groupby("source_file").size().rename("rank")
        .sort_values(ascending=False).reset_index()
    )
    rank_lookup = {row["source_file"]: i for i, row in file_size_rank.iterrows()}
    df["_rank"] = df["source_file"].map(rank_lookup)
    df = df.sort_values("_rank").drop_duplicates(subset=dup_keys, keep="first")
    n_dropped = sum(accounts_seen.values()) - len(df)
    df = df.drop(columns=["_rank"]).copy()

    df = df.sort_values(["purchase_date", "account", "ticker"], kind="stable").reset_index(drop=True)

    dest = app_root / "data" / "formated" / f"{tag}.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)

    if n_dropped > 0:
        total_skipped[f"duplicate-cross-file"] = n_dropped

    summary = ImportSummary(
        rows_emitted=len(df),
        skipped_by_code=dict(total_skipped),
        unrecognized_codes=dict(total_unrecognized),
        accounts_seen=dict(accounts_seen),
        dividend_reinvestments=total_drip,
    )
    return dest, summary
