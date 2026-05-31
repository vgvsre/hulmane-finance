"""Persistent per-transaction tags.

Users attach free-form tags to individual transactions (e.g. "long-term",
"RSU", "review") so reports can be sliced by tag. A transaction can carry many
tags.

Storage lives in data/_txn_tags.json — OUTSIDE data/formated, so the ground-zero
rebuild (which only clears data/formated/*.csv) never touches it. Tags are keyed
by the rebuild-stable ``txn_id`` assigned in the pipeline, so they re-attach to
the same transactions after every restart/rebuild.

    { "<txn_id>": ["long-term", "RSU"], ... }
"""
from __future__ import annotations

import json
from pathlib import Path

TAGS_FILENAME = "_txn_tags.json"


def tags_path(app_root: Path) -> Path:
    return app_root / "data" / TAGS_FILENAME


def load(app_root: Path) -> dict[str, list[str]]:
    p = tags_path(app_root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except Exception:
        return {}
    out: dict[str, list[str]] = {}
    for k, v in (data.items() if isinstance(data, dict) else []):
        if isinstance(v, list):
            out[str(k)] = [str(t) for t in v]
    return out


def save(app_root: Path, store: dict[str, list[str]]) -> None:
    p = tags_path(app_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Drop empty tag lists so the file stays tidy.
    clean = {k: sorted(set(v)) for k, v in store.items() if v}
    p.write_text(json.dumps(clean, indent=2, sort_keys=True, ensure_ascii=False))


def all_tag_names(store: dict[str, list[str]]) -> list[str]:
    names: set[str] = set()
    for tags in store.values():
        names.update(tags)
    return sorted(names)


def set_for(store: dict[str, list[str]], txn_id: str, tags: list[str]) -> None:
    clean = sorted({t.strip() for t in tags if t and t.strip()})
    if clean:
        store[txn_id] = clean
    else:
        store.pop(txn_id, None)


def add_to_many(store: dict[str, list[str]], txn_ids, tag: str) -> int:
    """Add one tag to many transactions. Returns the number changed."""
    tag = tag.strip()
    if not tag:
        return 0
    n = 0
    for tid in txn_ids:
        if not tid:
            continue
        cur = set(store.get(tid, []))
        if tag not in cur:
            cur.add(tag)
            store[tid] = sorted(cur)
            n += 1
    return n


def remove_from_many(store: dict[str, list[str]], txn_ids, tag: str) -> int:
    """Remove one tag from many transactions. Returns the number changed."""
    tag = tag.strip()
    if not tag:
        return 0
    n = 0
    for tid in txn_ids:
        if not tid:
            continue
        cur = set(store.get(tid, []))
        if tag in cur:
            cur.discard(tag)
            set_for(store, tid, sorted(cur))
            n += 1
    return n
