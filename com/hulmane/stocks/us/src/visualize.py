"""Charts for portfolio reports."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from . import report


def _save(fig, app_root: Path, name: str) -> Path:
    out_dir = report.reports_dir(app_root) / "charts"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{name}_{ts}.png"
    fig.savefig(path, bbox_inches="tight", dpi=120)
    plt.close(fig)
    return path


def chart_tag_pnl(app_root: Path) -> Path:
    df = report.all_tags_summary(app_root)
    if df.empty:
        raise RuntimeError("No tags to chart")
    fig, ax = plt.subplots(figsize=(8, 4.5))
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in df["pnl"]]
    ax.bar(df["tag"], df["pnl"], color=colors)
    ax.axhline(0, color="black", linewidth=0.7)
    ax.set_title("P&L by tag (cohort)")
    ax.set_ylabel("P&L (USD)")
    ax.set_xlabel("Tag")
    for i, (pnl, pct) in enumerate(zip(df["pnl"], df["pnl_pct"])):
        ax.text(i, pnl, f"${pnl:,.0f}\n({pct:+.1f}%)", ha="center",
                va="bottom" if pnl >= 0 else "top", fontsize=9)
    return _save(fig, app_root, "pnl_by_tag")


def chart_tag_invested_vs_current(app_root: Path) -> Path:
    df = report.all_tags_summary(app_root)
    if df.empty:
        raise RuntimeError("No tags to chart")
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = range(len(df))
    width = 0.35
    ax.bar([i - width / 2 for i in x], df["invested"], width, label="Invested", color="#3498db")
    ax.bar([i + width / 2 for i in x], df["current_value"], width, label="Current", color="#9b59b6")
    ax.set_xticks(list(x))
    ax.set_xticklabels(df["tag"])
    ax.set_ylabel("USD")
    ax.set_title("Invested vs current value by tag")
    ax.legend()
    return _save(fig, app_root, "invested_vs_current")


def chart_position_breakdown(app_root: Path, tag: str) -> Path:
    df = report.tag_report(app_root, tag)
    if df.empty:
        raise RuntimeError(f"No positions in tag '{tag}'")
    by_ticker = df.groupby("ticker", as_index=False)["current_value"].sum()
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(by_ticker["current_value"], labels=by_ticker["ticker"],
           autopct="%1.1f%%", startangle=90)
    ax.set_title(f"Holdings breakdown — tag '{tag}' (current value)")
    return _save(fig, app_root, f"breakdown_{tag}")
