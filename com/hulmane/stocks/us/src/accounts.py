"""Account registry + resolver.

``data/source/accounts.csv`` is the master list of brokerage accounts. Every
formatted transaction is linked to one of these accounts so the dashboard can
slice holdings by which account they belong to.

Registry columns:
    No, Platform, RHS Account No, Account Type, Account Desc

Each broker importer emits a raw ``account`` token derived from its source:
    fidelity  -> the Account Number from the Positions export (e.g. Z30241698)
    etrade    -> the account digits lifted from DownloadTxnHistory (e.g. 876829)
    robinhood -> the number mapped from the filename via _accounts.json

We match that token to a registry row by comparing normalized alnum strings
(substring-tolerant, since E*TRADE shows only the middle segment of a dashed
account number like 511-876829-210). Tokens with no registry match are kept
verbatim and flagged so the user can reconcile accounts.csv.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ACCOUNTS_FILENAME = "accounts.csv"

# Map an accounts.csv "Platform" value to the broker tag used by the importers.
PLATFORM_TO_BROKER = {
    "robinhood": "robinhood",
    "e-trade": "etrade",
    "etrade": "etrade",
    "fidelity": "fidelity",
}


def accounts_path(app_root: Path) -> Path:
    return app_root / "data" / "source" / ACCOUNTS_FILENAME


@dataclass
class Account:
    no: str          # the registry "No" column (1..N)
    platform: str    # e.g. "Robinhood"
    number: str      # raw "RHS Account No" (e.g. 511-876829-210, Z30241698)
    acct_type: str
    desc: str        # "Account Desc"
    norm: str        # normalized alnum (upper, no separators) for matching


@dataclass
class Resolution:
    """Outcome of linking one raw broker token to the registry."""
    account: str         # canonical label, controlled vocabulary (always set)
    account_desc: str    # human description(s) from the registry, "" if unmatched
    account_no: str      # registry "No"(s), "" if unmatched
    number: str          # registry account number, or the raw token if unmatched
    matched: bool


def _norm(s) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(s)).upper()


def load_registry(app_root: Path) -> list[Account]:
    p = accounts_path(app_root)
    if not p.exists():
        return []
    df = pd.read_csv(p, dtype=str, keep_default_na=False)
    out: list[Account] = []
    for _, r in df.iterrows():
        number = str(r.get("RHS Account No", "")).strip()
        if not number:
            continue
        out.append(
            Account(
                no=str(r.get("No", "")).strip(),
                platform=str(r.get("Platform", "")).strip(),
                number=number,
                acct_type=str(r.get("Account Type", "")).strip(),
                desc=str(r.get("Account Desc", "")).strip(),
                norm=_norm(number),
            )
        )
    return out


def _matches(token_norm: str, registry: list[Account], broker: str | None) -> list[Account]:
    if not token_norm:
        return []
    pool = registry
    if broker:
        same = [a for a in registry
                if PLATFORM_TO_BROKER.get(a.platform.lower()) == broker]
        if same:
            pool = same
    # 1) exact normalized match
    exact = [a for a in pool if a.norm == token_norm]
    if exact:
        return exact
    # 2) containment either way (E*TRADE middle-segment, len guard avoids noise)
    if len(token_norm) >= 4:
        return [a for a in pool
                if (token_norm in a.norm or a.norm in token_norm)]
    return []


def resolve(token: str, broker: str, registry: list[Account]) -> Resolution:
    """Link a raw broker account token to a registry account.

    ``broker`` narrows the search to the matching platform so a number that
    happens to collide across platforms can't cross-match.
    """
    token = (token or "").strip()
    matches = _matches(_norm(token), registry, broker)
    if matches:
        number = matches[0].number
        platform = matches[0].platform
        descs = " / ".join(sorted({m.desc for m in matches if m.desc}))
        nos = "/".join(sorted({m.no for m in matches if m.no}))
        return Resolution(
            account=f"{platform} {number}",
            account_desc=descs,
            account_no=nos,
            number=number,
            matched=True,
        )
    # Unmatched: keep the token so nothing is silently lost.
    plat = broker or "unknown"
    label = f"{plat} {token}".strip() if token else f"{plat} (unknown)"
    return Resolution(account=label, account_desc="", account_no="",
                      number=token, matched=False)
