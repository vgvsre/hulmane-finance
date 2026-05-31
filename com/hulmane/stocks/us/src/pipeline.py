"""Startup data pipeline: rebuild data/formated from data/source, from scratch.

Called once per app start (CLI `rebuild` or dashboard bootstrap). On every run
it wipes data/formated and regenerates one formatted CSV per broker tag from the
raw exports under data/source/<broker>/. Each file is processed independently so
one bad file can't sink the rest, and a per-file status report is written to
logs/ (logs/latest.log + a timestamped copy).

Every emitted transaction is linked to an account from data/source/accounts.csv
via :mod:`src.accounts`; unmatched account tokens are flagged in the log.

The formatted CSVs are self-sufficient: once written, the app reads only from
data/formated, so the raw files under data/source can be deleted.
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import accounts as accounts_mod
from . import portfolio
from .importers import etrade as etrade_imp
from .importers import fidelity as fidelity_imp
from .importers import robinhood as robinhood_imp

# source subfolder -> (tag written to data/formated, broker label, kind)
BROKERS: list[tuple[str, str, str]] = [
    ("etrade", "etrade", "etrade"),
    ("robinhood", "robinhood", "robinhood"),
    ("fedility", "fidelity", "fidelity"),  # note: source dir is spelled "fedility"
]

OUTPUT_COLS = [
    "txn_id",
    "ticker", "quantity", "purchase_price", "purchase_date", "broker",
    "account", "account_no", "account_desc", "account_src",
    "action", "row_type", "source_file",
]

# Columns that define a transaction's stable identity across rebuilds. As long
# as the source data is unchanged, the derived txn_id is reproduced exactly, so
# per-transaction tags (stored separately) survive every ground-zero rebuild.
_ID_COLS = ["broker", "account_src", "purchase_date", "ticker", "action",
            "quantity", "purchase_price", "source_file", "row_type"]

# Trade-level dedupe key (deliberately excludes account so the same trade seen
# under two account tokens collapses to the row from the most complete file).
_TRADE_DUP_KEYS = ["broker", "purchase_date", "ticker", "action",
                   "quantity", "purchase_price"]


@dataclass
class FileStatus:
    broker: str
    filename: str
    status: str          # ok | empty | skipped | error
    rows: int = 0
    message: str = ""


@dataclass
class TagResult:
    tag: str
    broker: str
    dest: str | None = None
    rows: int = 0
    duplicates_dropped: int = 0
    files: list[FileStatus] = field(default_factory=list)
    unmatched_accounts: dict[str, int] = field(default_factory=dict)


@dataclass
class RunResult:
    started_at: str
    source_dir: str
    formated_dir: str
    log_path: str
    tags: list[TagResult] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return sum(t.rows for t in self.tags)


# ── per-file parsers ──────────────────────────────────────────────────────────

def _normalize_frame(df: pd.DataFrame, filename: str, row_type: str = "trade") -> pd.DataFrame:
    """Guarantee action + source_file + row_type columns on a parsed frame."""
    if df.empty:
        return df
    df = df.copy()
    if "source_file" not in df.columns:
        df["source_file"] = filename
    else:
        df["source_file"] = df["source_file"].fillna(filename).replace("", filename)
    if "action" not in df.columns:
        df["action"] = df["quantity"].apply(lambda q: "Buy" if q >= 0 else "Sell")
    if "account" not in df.columns:
        df["account"] = ""
    if "row_type" not in df.columns:
        df["row_type"] = row_type
    return df


def _process_etrade_file(path: Path) -> tuple[pd.DataFrame, FileStatus]:
    try:
        df, summary = etrade_imp.parse(path)
    except Exception as e:  # unrecognized format, bad rows, etc.
        return pd.DataFrame(), FileStatus("etrade", path.name, "error", 0, str(e))
    df = _normalize_frame(df, path.name)
    if df.empty:
        return df, FileStatus("etrade", path.name, "empty", 0, "no Buy/Sell rows")
    skipped = ", ".join(f"{k}:{v}" for k, v in sorted(summary.skipped_by_type.items()))
    return df, FileStatus("etrade", path.name, "ok", len(df),
                          f"skipped {skipped}" if skipped else "")


def _process_robinhood_file(path: Path, account_map: dict[str, str]) -> tuple[pd.DataFrame, FileStatus]:
    label = robinhood_imp._account_label(path, account_map)
    try:
        df, summary = robinhood_imp.parse(path, account_label=label)
    except Exception as e:
        return pd.DataFrame(), FileStatus("robinhood", path.name, "error", 0, str(e))
    df = _normalize_frame(df, path.name)
    if df.empty:
        return df, FileStatus("robinhood", path.name, "empty", 0, "no Buy/Sell rows")
    skipped = ", ".join(f"{k}:{v}" for k, v in sorted(summary.skipped_by_code.items()))
    return df, FileStatus("robinhood", path.name, "ok", len(df),
                          f"acct {label}" + (f"; skipped {skipped}" if skipped else ""))


def _is_fidelity_positions(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8-sig") as fh:
            for _ in range(20):
                line = fh.readline()
                if not line:
                    break
                if line.startswith(fidelity_imp.EXPECTED_HEADER_PREFIX):
                    return True
    except Exception:
        return False
    return False


def _is_fidelity_history(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8-sig") as fh:
            for _ in range(20):
                line = fh.readline()
                if not line:
                    break
                if line.startswith(fidelity_imp.HISTORY_HEADER_PREFIX):
                    return True
    except Exception:
        return False
    return False


def _process_fidelity_file(path: Path) -> tuple[pd.DataFrame, FileStatus]:
    if _is_fidelity_positions(path):
        try:
            df = fidelity_imp.import_paths([path])
        except Exception as e:
            return pd.DataFrame(), FileStatus("fidelity", path.name, "error", 0, str(e))
        df = _normalize_frame(df, path.name, row_type="position")
        if df.empty:
            return df, FileStatus("fidelity", path.name, "empty", 0, "no positions")
        return df, FileStatus("fidelity", path.name, "ok", len(df), "positions snapshot")

    if _is_fidelity_history(path):
        try:
            df, accts, skipped = fidelity_imp.parse_history(path)
        except Exception as e:
            return pd.DataFrame(), FileStatus("fidelity", path.name, "error", 0, str(e))
        df = _normalize_frame(df, path.name)  # row_type already set per row
        if df.empty:
            return df, FileStatus("fidelity", path.name, "empty", 0, "no transactions")
        skip_txt = ", ".join(f"{k}:{v}" for k, v in sorted(skipped.items()))
        acct_txt = "+".join(sorted(accts))
        return df, FileStatus("fidelity", path.name, "ok", len(df),
                              f"history acct {acct_txt}" + (f"; skipped {skip_txt}" if skip_txt else ""))

    return pd.DataFrame(), FileStatus(
        "fidelity", path.name, "skipped", 0, "unrecognized Fidelity export format")


# ── dedupe ──────────────────────────────────────────────────────────────────

def _dedupe_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Cross-file dedupe for trade brokers; keep the row from the largest file."""
    if df.empty:
        return df, 0
    before = len(df)
    rank = (df.groupby("source_file").size().rename("rank")
            .sort_values(ascending=False).reset_index())
    rank_lookup = {r["source_file"]: i for i, r in rank.iterrows()}
    df = df.assign(_rank=df["source_file"].map(rank_lookup))
    df = df.sort_values("_rank").drop_duplicates(subset=_TRADE_DUP_KEYS, keep="first")
    df = df.drop(columns=["_rank"])
    return df.reset_index(drop=True), before - len(df)


def _dedupe_positions(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop exact-duplicate position rows (same snapshot exported twice)."""
    if df.empty:
        return df, 0
    before = len(df)
    keys = ["broker", "account", "ticker", "purchase_date", "quantity", "purchase_price"]
    df = df.drop_duplicates(subset=keys, keep="first").reset_index(drop=True)
    return df, before - len(df)


# ── account linking ────────────────────────────────────────────────────────

def _attach_accounts(df: pd.DataFrame, broker: str,
                     registry: list[accounts_mod.Account]) -> tuple[pd.DataFrame, dict[str, int]]:
    """Resolve each row's raw account token to a registry account.

    Returns the decorated frame and a {raw_token: count} map of unmatched tokens.
    """
    df = df.copy()
    df["account_src"] = df.get("account", "").astype(str)
    cache: dict[str, accounts_mod.Resolution] = {}
    unmatched: dict[str, int] = {}
    for tok in df["account_src"].unique():
        cache[tok] = accounts_mod.resolve(tok, broker, registry)
    df["account"] = df["account_src"].map(lambda t: cache[t].account)
    df["account_no"] = df["account_src"].map(lambda t: cache[t].account_no)
    df["account_desc"] = df["account_src"].map(lambda t: cache[t].account_desc)
    for tok in df["account_src"]:
        if not cache[tok].matched:
            unmatched[tok] = unmatched.get(tok, 0) + 1
    return df, unmatched


# ── per-broker driver ─────────────────────────────────────────────────────────

def _load_file_account_map(src_dir: Path) -> dict[str, str]:
    """Read data/source/<broker>/_accounts.json: {filename_stem: account_number}.

    Lets the user pin exports that carry no account number (e.g. E*TRADE
    tradesdownload files) to a specific account. Reused by Robinhood too.
    A "*" key is a catch-all applied only to rows that still lack an account.
    """
    return robinhood_imp._load_account_map(src_dir)


def _apply_file_overrides(df: pd.DataFrame, account_map: dict[str, str]) -> pd.DataFrame:
    """Override the account token of mapped rows.

    Priority: an exact filename-stem entry always wins. A "*" catch-all only
    fills rows whose token is still a broker sentinel (empty, or == broker name
    like E*TRADE's "etrade"), so it never clobbers a real account number that a
    richer export (e.g. DownloadTxnHistory) already supplied.
    """
    if df.empty or not account_map:
        return df
    df = df.copy()
    star = account_map.get("*")

    def _override(row):
        stem = Path(str(row["source_file"])).stem
        if stem in account_map:
            return account_map[stem]
        tok = str(row["account"]).strip()
        if star and (tok == "" or tok.lower() == str(row["broker"]).lower()):
            return star
        return row["account"]

    df["account"] = df.apply(_override, axis=1)
    return df


def _process_broker(app_root: Path, src_subdir: str, tag: str, broker: str,
                    registry: list[accounts_mod.Account]) -> TagResult:
    result = TagResult(tag=tag, broker=broker)
    src_dir = app_root / "data" / "source" / src_subdir
    if not src_dir.exists():
        result.files.append(FileStatus(broker, str(src_dir), "skipped", 0, "source folder missing"))
        return result

    csvs = sorted(src_dir.glob("*.csv"))
    # surface non-CSV files (PDFs etc.) as skipped so the log is complete
    for other in sorted(p for p in src_dir.iterdir()
                        if p.is_file() and p.suffix.lower() != ".csv" and not p.name.startswith(("_", "."))):
        result.files.append(FileStatus(broker, other.name, "skipped", 0, "not a CSV"))

    account_map = _load_file_account_map(src_dir)
    frames: list[pd.DataFrame] = []
    for path in csvs:
        if path.name.startswith(("_", ".")):
            continue
        if broker == "etrade":
            df, status = _process_etrade_file(path)
        elif broker == "robinhood":
            df, status = _process_robinhood_file(path, account_map)
        else:
            df, status = _process_fidelity_file(path)
        result.files.append(status)
        if not df.empty:
            frames.append(df)

    if not frames:
        return result

    combined = pd.concat(frames, ignore_index=True)
    if broker == "fidelity":
        # Fidelity mixes position snapshots and transaction history — dedupe each
        # kind by its own rule, then recombine.
        pos = combined[combined["row_type"] == "position"]
        trd = combined[combined["row_type"] != "position"]
        pos, d1 = _dedupe_positions(pos)
        trd, d2 = _dedupe_trades(trd)
        combined = pd.concat([pos, trd], ignore_index=True)
        dropped = d1 + d2
    else:
        combined, dropped = _dedupe_trades(combined)
    result.duplicates_dropped = dropped

    combined = _apply_file_overrides(combined, account_map)
    combined, unmatched = _attach_accounts(combined, broker, registry)
    result.unmatched_accounts = unmatched

    combined = combined.reindex(columns=OUTPUT_COLS)
    combined = combined.sort_values(["purchase_date", "account", "ticker"],
                                    kind="stable").reset_index(drop=True)
    combined = _assign_txn_id(combined)

    dest = portfolio.formated_dir(app_root) / f"{tag}.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(dest, index=False)
    result.dest = str(dest)
    result.rows = len(combined)
    return result


def _assign_txn_id(df: pd.DataFrame) -> pd.DataFrame:
    """Stamp a deterministic, rebuild-stable id on every row.

    The id is a hash of the identity columns plus an occurrence index that
    disambiguates genuinely-identical rows. Because the frame is already sorted
    deterministically, the same input always yields the same ids — which is what
    lets per-transaction tags (stored by id) survive a ground-zero rebuild.
    """
    if df.empty:
        return df
    df = df.copy()
    base = df[_ID_COLS].astype(str).agg("|".join, axis=1)
    occ = base.groupby(base).cumcount().astype(str)
    df["txn_id"] = (base + "|" + occ).map(
        lambda s: hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]
    )
    return df


# ── logging ───────────────────────────────────────────────────────────────────

def _write_log(app_root: Path, run: RunResult) -> Path:
    logs_dir = app_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("Hulmane US Stocks — data rebuild")
    lines.append(f"Run at:  {run.started_at}")
    lines.append(f"Source:  {run.source_dir}")
    lines.append(f"Output:  {run.formated_dir}")
    lines.append("")
    icon = {"ok": "OK   ", "empty": "EMPTY", "skipped": "SKIP ", "error": "ERROR"}
    for tag in run.tags:
        lines.append(f"[{tag.broker}] -> {tag.tag}.csv")
        for f in tag.files:
            extra = f"  ({f.message})" if f.message else ""
            lines.append(f"  {icon.get(f.status, f.status):5s} {f.filename:48s} {f.rows:>6} rows{extra}")
        if tag.dest:
            note = f" ({tag.duplicates_dropped} duplicates dropped)" if tag.duplicates_dropped else ""
            lines.append(f"  => wrote {tag.tag}.csv : {tag.rows} rows{note}")
        else:
            lines.append(f"  => nothing written (no usable rows)")
        if tag.unmatched_accounts:
            total = sum(tag.unmatched_accounts.values())
            detail = ", ".join(f"{k!r}×{v}" for k, v in sorted(tag.unmatched_accounts.items()))
            lines.append(f"  !! {total} rows on accounts NOT in accounts.csv: {detail}")
        lines.append("")
    n_ok = sum(1 for t in run.tags for f in t.files if f.status == "ok")
    n_err = sum(1 for t in run.tags for f in t.files if f.status == "error")
    n_skip = sum(1 for t in run.tags for f in t.files if f.status == "skipped")
    lines.append(f"SUMMARY: {len(run.tags)} tags · {run.total_rows} rows · "
                 f"{n_ok} files ok, {n_skip} skipped, {n_err} errors")

    text = "\n".join(lines) + "\n"
    ts = run.started_at.replace(":", "").replace("-", "").replace(" ", "_")
    stamped = logs_dir / f"run_{ts}.log"
    stamped.write_text(text)
    (logs_dir / "latest.log").write_text(text)
    return stamped


# ── entry point ────────────────────────────────────────────────────────────────

def run(app_root: Path) -> RunResult:
    """Rebuild data/formated from data/source, from scratch. Returns a report."""
    app_root = Path(app_root)
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formated = portfolio.formated_dir(app_root)
    formated.mkdir(parents=True, exist_ok=True)

    # Ground zero: clear previously formatted CSVs so deleted/renamed tags vanish.
    for old in formated.glob("*.csv"):
        old.unlink()

    registry = accounts_mod.load_registry(app_root)
    run_result = RunResult(
        started_at=started,
        source_dir=str(app_root / "data" / "source"),
        formated_dir=str(formated),
        log_path="",
    )
    for src_subdir, tag, broker in BROKERS:
        run_result.tags.append(_process_broker(app_root, src_subdir, tag, broker, registry))

    log_path = _write_log(app_root, run_result)
    run_result.log_path = str(log_path)
    return run_result
