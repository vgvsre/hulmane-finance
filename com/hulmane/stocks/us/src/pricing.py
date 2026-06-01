"""Live US stock pricing via yfinance, with a disk-backed cache."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yfinance as yf

# Brokerage cash sweeps and money market funds priced at $1.00.
# Fidelity exports use a trailing '**' on these symbols.
CASH_SYMBOLS: set[str] = {
    "FCASH", "FDRXX", "SPAXX", "FZFXX", "FDIC", "FGCXX", "FGRXX", "FZDXX",
}

DEFAULT_TIMEOUT_SECS = 4
DEFAULT_PARALLEL = 16
PRICE_CACHE_FILENAME = "_price_cache.json"


def _is_cash(ticker: str) -> bool:
    base = ticker.rstrip("*").upper()
    return base in CASH_SYMBOLS


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Quote:
    ticker: str
    price: float
    currency: str
    name: str | None = None
    fetched_at: str | None = None  # ISO 8601 UTC; None means live, freshly fetched


def _nan_quote(ticker: str, reason: str = "") -> Quote:
    return Quote(ticker=ticker.upper(), price=float("nan"), currency="USD",
                 name=f"<{reason}>" if reason else None, fetched_at=None)


def get_quote(ticker: str) -> Quote:
    if _is_cash(ticker):
        return Quote(ticker=ticker.upper(), price=1.0, currency="USD",
                     name="Cash / money market", fetched_at=_utcnow_iso())
    t = yf.Ticker(ticker)
    fast = t.fast_info
    price = float(fast["last_price"])
    currency = fast.get("currency", "USD") or "USD"
    name = None
    try:
        name = t.info.get("shortName") or t.info.get("longName")
    except Exception:
        pass
    return Quote(ticker=ticker.upper(), price=price, currency=currency,
                 name=name, fetched_at=_utcnow_iso())


def get_quotes(
    tickers: Iterable[str],
    timeout: float = DEFAULT_TIMEOUT_SECS,
    max_workers: int = DEFAULT_PARALLEL,
) -> dict[str, Quote]:
    """Concurrent live fetch with a hard timeout. NaN entries on failure."""
    uniq = sorted({t.upper() for t in tickers})
    out: dict[str, Quote] = {t: _nan_quote(t, "pending") for t in uniq}
    if not uniq:
        return out

    with ThreadPoolExecutor(max_workers=min(max_workers, len(uniq))) as pool:
        futures = {pool.submit(get_quote, t): t for t in uniq}
        try:
            for fut in as_completed(futures, timeout=timeout):
                tk = futures[fut]
                try:
                    out[tk] = fut.result()
                except Exception as e:
                    out[tk] = _nan_quote(tk, f"error: {type(e).__name__}")
        except FuturesTimeoutError:
            for fut, tk in futures.items():
                if not fut.done():
                    out[tk] = _nan_quote(tk, "timeout")
                    fut.cancel()
    return out


# ── Disk-persistent cache ─────────────────────────────────────────────────────

def cache_path(app_root: Path) -> Path:
    return app_root / "data" / PRICE_CACHE_FILENAME


def load_cache(app_root: Path) -> dict[str, dict]:
    p = cache_path(app_root)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def save_cache(app_root: Path, cache: dict[str, dict]) -> None:
    p = cache_path(app_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, indent=2, sort_keys=True))


def _cache_to_quote(tk: str, entry: dict) -> Quote:
    return Quote(
        ticker=tk,
        price=float(entry.get("price", float("nan"))),
        currency=entry.get("currency", "USD") or "USD",
        name=entry.get("name"),
        fetched_at=entry.get("fetched_at"),
    )


def get_quotes_cached(app_root: Path, tickers: Iterable[str]) -> dict[str, Quote]:
    """Cache-only lookup. Tickers absent from cache return NaN with a 'no cache' marker.
    Cash symbols are always priced at $1.00 without consulting the cache."""
    cache = load_cache(app_root)
    out: dict[str, Quote] = {}
    for t in {tk.upper() for tk in tickers}:
        if _is_cash(t):
            out[t] = Quote(ticker=t, price=1.0, currency="USD",
                           name="Cash / money market", fetched_at=None)
        elif t in cache:
            out[t] = _cache_to_quote(t, cache[t])
        else:
            out[t] = _nan_quote(t, "no cached price")
    return out


def get_quotes_live_and_cache(
    app_root: Path, tickers: Iterable[str],
    timeout: float = DEFAULT_TIMEOUT_SECS,
    max_workers: int = DEFAULT_PARALLEL,
) -> dict[str, Quote]:
    """Fetch live, save successes to disk cache, and fill failures from cache."""
    fresh = get_quotes(tickers, timeout=timeout, max_workers=max_workers)
    cache = load_cache(app_root)

    out: dict[str, Quote] = {}
    for tk, q in fresh.items():
        if q.price == q.price:  # not NaN
            cache[tk] = {
                "price": q.price,
                "currency": q.currency,
                "name": q.name,
                "fetched_at": q.fetched_at or _utcnow_iso(),
            }
            out[tk] = q
        elif tk in cache:  # fall back to last known
            out[tk] = _cache_to_quote(tk, cache[tk])
        else:
            out[tk] = q  # still NaN

    save_cache(app_root, cache)
    return out


def cache_summary(app_root: Path) -> dict:
    """Report the cache's freshness for the UI: count, oldest, newest fetched_at."""
    cache = load_cache(app_root)
    timestamps = [v.get("fetched_at") for v in cache.values() if v.get("fetched_at")]
    return {
        "count": len(cache),
        "oldest": min(timestamps) if timestamps else None,
        "newest": max(timestamps) if timestamps else None,
    }


def get_price(ticker: str) -> float:
    return get_quote(ticker).price
