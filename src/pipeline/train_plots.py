"""Figures logged with every training run: feature importance and residuals."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

BLUE, INK, INK2, GRID, SURFACE = "#2a78d6", "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def _style(ax) -> None:
    """Quiet axes: no top/right line, light grid."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK2)


def plot_feature_importance(
    importance: dict[int, pd.Series], out_path: str | Path, top: int = 12
) -> Path:
    """Bar chart of LightGBM gain importance, one panel per horizon.

    Values are shown as a share of the total gain, so the two horizons can be
    compared even though their raw gains differ.
    """
    fig, axes = plt.subplots(1, len(importance), figsize=(5.5 * len(importance), 4.5))
    axes = np.atleast_1d(axes)
    fig.patch.set_facecolor(SURFACE)
    for ax, (horizon, series) in zip(axes, sorted(importance.items()), strict=True):
        share = (series / series.sum()).sort_values().tail(top)
        ax.barh(share.index, share.to_numpy() * 100, color=BLUE, height=0.7)
        ax.set_title(f"{horizon} h ahead", loc="left", fontweight="bold", color=INK)
        ax.set_xlabel("Share of total gain (%)", color=INK2)
        ax.set_facecolor(SURFACE)
        _style(ax)
        ax.grid(axis="y", visible=False)
    fig.suptitle(
        "What the LightGBM models rely on", x=0.01, ha="left", fontweight="bold"
    )
    fig.tight_layout()
    path = Path(out_path)
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)
    return path


def plot_residuals(residuals: dict[int, np.ndarray], out_path: str | Path) -> Path:
    """Histogram of prediction minus actual (µg/m³) on the evaluation window."""
    fig, axes = plt.subplots(1, len(residuals), figsize=(5.5 * len(residuals), 3.8))
    axes = np.atleast_1d(axes)
    fig.patch.set_facecolor(SURFACE)
    for ax, (horizon, res) in zip(axes, sorted(residuals.items()), strict=True):
        ax.hist(res, bins=40, color=BLUE)
        ax.axvline(0, color=INK2, linewidth=1, linestyle="--")
        ax.set_title(
            f"{horizon} h ahead (median {np.median(res):+.1f})",
            loc="left",
            fontweight="bold",
            color=INK,
        )
        ax.set_xlabel("Prediction minus actual PM2.5 (µg/m³)", color=INK2)
        ax.set_ylabel("Hours", color=INK2)
        ax.set_facecolor(SURFACE)
        _style(ax)
    fig.tight_layout()
    path = Path(out_path)
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)
    return path
