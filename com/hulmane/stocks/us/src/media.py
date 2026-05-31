"""Logo / icon lookup for tickers.

The dashboard checks for a user-supplied logo at media/<TICKER>.{png,svg,jpg,jpeg,webp}.
If none is found, a deterministic gradient letter-avatar SVG is generated as a fallback,
so every ticker has *some* colorful icon even before any logo files are dropped in.
"""
from __future__ import annotations

import base64
import hashlib
import mimetypes
from functools import lru_cache
from pathlib import Path

# Same palette used elsewhere in the dashboard.
PALETTE = ["#7c3aed", "#ec4899", "#f59e0b", "#10b981", "#06b6d4",
           "#3b82f6", "#ef4444", "#84cc16", "#a855f7", "#14b8a6"]

SUPPORTED_EXTS = ("png", "svg", "jpg", "jpeg", "webp")


def media_dir(app_root: Path) -> Path:
    d = app_root / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logo_path(app_root: Path, ticker: str) -> Path | None:
    base = ticker.upper().rstrip("*")
    d = media_dir(app_root)
    for ext in SUPPORTED_EXTS:
        p = d / f"{base}.{ext}"
        if p.exists():
            return p
    return None


@lru_cache(maxsize=512)
def letter_avatar_svg(ticker: str, size: int = 64) -> str:
    label = ticker.upper().rstrip("*") or "?"
    short = label[:2] if len(label) > 2 else label
    h = int(hashlib.md5(label.encode()).hexdigest(), 16)
    color1 = PALETTE[h % len(PALETTE)]
    color2 = PALETTE[(h // 7) % len(PALETTE)]
    font_size = int(size * 0.42)
    grad_id = f"g{h % 100000}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">'
        f'<defs><linearGradient id="{grad_id}" x1="0%" y1="0%" x2="100%" y2="100%">'
        f'<stop offset="0%" stop-color="{color1}"/>'
        f'<stop offset="100%" stop-color="{color2}"/>'
        f'</linearGradient></defs>'
        f'<circle cx="{size/2}" cy="{size/2}" r="{size/2 - 1}" fill="url(#{grad_id})"/>'
        f'<text x="{size/2}" y="{size/2 + 1}" text-anchor="middle" '
        f'dominant-baseline="central" fill="white" '
        f'font-family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" '
        f'font-size="{font_size}" font-weight="700">{short}</text>'
        f'</svg>'
    )


def as_data_url(content: bytes | str, mime: str = "image/svg+xml") -> str:
    if isinstance(content, str):
        content = content.encode()
    b64 = base64.b64encode(content).decode()
    return f"data:{mime};base64,{b64}"


def icon_data_url(app_root: Path, ticker: str, size: int = 64) -> str:
    """Best-effort icon as a data URL: real logo if available, gradient letter avatar otherwise."""
    p = logo_path(app_root, ticker)
    if p is not None:
        mime = mimetypes.guess_type(str(p))[0] or "image/png"
        return as_data_url(p.read_bytes(), mime)
    return as_data_url(letter_avatar_svg(ticker, size=size))
