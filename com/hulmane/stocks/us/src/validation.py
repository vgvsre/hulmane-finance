"""Persistent per-transaction manual-validation flags.

A user eyeballs each transaction against the broker statement and ticks it off
once it's confirmed correct. That confirmation is a permanent fact about the
transaction, so — like :mod:`src.tags` — it is stored in data/_txn_validation.json,
OUTSIDE data/formated. The ground-zero rebuild only clears data/formated/*.csv,
so this file is never touched, and because flags are keyed by the rebuild-stable
``txn_id`` they re-attach to the same transactions after every restart/rebuild.

    { "validated": ["<txn_id>", "<txn_id>", ...] }
"""
from __future__ import annotations

import json
from pathlib import Path

VALIDATION_FILENAME = "_txn_validation.json"


def validation_path(app_root: Path) -> Path:
    return app_root / "data" / VALIDATION_FILENAME


def load(app_root: Path) -> set[str]:
    """Return the set of txn_ids the user has manually validated."""
    p = validation_path(app_root)
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text())
    except Exception:
        return set()
    ids = data.get("validated") if isinstance(data, dict) else data
    if not isinstance(ids, list):
        return set()
    return {str(t) for t in ids if t}


def save(app_root: Path, validated: set[str]) -> None:
    p = validation_path(app_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"validated": sorted(validated)},
                            indent=2, ensure_ascii=False))


def set_for(validated: set[str], txn_id: str, is_valid: bool) -> None:
    """Mark one transaction validated (or clear it). Mutates ``validated``."""
    if not txn_id:
        return
    if is_valid:
        validated.add(txn_id)
    else:
        validated.discard(txn_id)
