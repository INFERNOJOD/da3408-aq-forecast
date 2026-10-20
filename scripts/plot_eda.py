"""Draw the EDA figures from the CSV files made by ``python -m src.pipeline.eda``.

Run: ``python scripts/plot_eda.py [csv_dir] [out_dir]``
Defaults: reports/eda  ->  docs/img

Colours: the first seven slots of the reference categorical palette (fixed
order), one blue ramp for magnitude, gray for "everything else". Every figure
has a text version (table) in docs/eda.md, so colour is never the only channel.
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

CITIES = ["Delhi", "Chennai", "Lucknow", "Hyderabad", "Bengaluru", "Jaipur", "Kolkata"]
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
CITY_COLOR = dict(zip(CITIES, SERIES, strict=True))
BLUE, GRAY = "#2a78d6", "#9a9a95"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
RAMP = LinearSegmentedColormap.from_list("blue", ["#eaf2fc", "#2a78d6", "#0d3b73"])
LOCKDOWN = pd.Timestamp("2020-03-25")
MONTHS = list("JFMAMJJASOND")


def style() -> None:
    """Apply one calm look to every figure."""
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK2,
            "axes.titlecolor": INK,
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "xtick.color": INK2,
            "ytick.color": INK2,
            "text.color": INK,
            "legend.frameon": False,
            "font.size": 9,
            "lines.linewidth": 2,
        }
    )


def save(fig, out_dir: Path, name: str) -> Path:
    """Save a figure as PNG and close it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_missing_heatmap(csv_dir: Path, out_dir: Path) -> Path:
    """Missing PM2.5 share by city and year (all cities)."""
    df = pd.read_csv(csv_dir / "missing_by_city_year.csv")
    df["missing"] = 1 - df["pm25_present"] / df["hours"]
    grid = df.pivot(index="City", columns="year", values="missing")
    order = df.groupby("City")["pm25_present"].sum().sort_values(ascending=False).index
    grid = grid.loc[order]
    fig, ax = plt.subplots(figsize=(7, 8))
    ax.grid(False)
    img = ax.imshow(grid.values, cmap=RAMP, vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(grid.columns)), grid.columns)
    ax.set_yticks(range(len(grid.index)), grid.index)
    for label in ax.get_yticklabels():
        if label.get_text() in CITIES:
            label.set_fontweight("bold")
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            v = grid.values[i, j]
            text = "no data" if pd.isna(v) else f"{v:.0%}"
            color = "white" if not pd.isna(v) and v > 0.55 else INK2
            ax.text(j, i, text, ha="center", va="center", fontsize=7, color=color)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.colorbar(img, ax=ax, label="Share of hours with PM2.5 missing", shrink=0.6)
    ax.set_title("PM2.5 is often missing in early years (bold = selected cities)")
    return save(fig, out_dir, "eda_missing_heatmap.png")


def plot_coverage(csv_dir: Path, out_dir: Path) -> Path:
    """Hours of PM2.5 data per city, selected cities highlighted."""
    df = pd.read_csv(csv_dir / "coverage_by_city.csv").sort_values("pm25_present")
    colors = [BLUE if c in CITIES else GRAY for c in df["City"]]
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.barh(df["City"], df["pm25_present"], color=colors, height=0.7)
    ax.set_xlim(0, df["pm25_present"].max() * 1.12)
    for y, v in enumerate(df["pm25_present"]):
        ax.text(v + 400, y, f"{v:,}", va="center", fontsize=7, color=INK2)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Hours with a PM2.5 reading")
    ax.set_title("Cities differ a lot in how much data they have")
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=BLUE),
        plt.Rectangle((0, 0), 1, 1, color=GRAY),
    ]
    ax.legend(handles, ["Selected for the model", "Not used"], loc="lower right")
    return save(fig, out_dir, "eda_coverage.png")


def plot_seasonality(csv_dir: Path, out_dir: Path) -> Path:
    """Average PM2.5 by hour of day and by month (data before 2020)."""
    df = pd.read_csv(csv_dir / "seasonality.csv")
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, kind, title in zip(
        axes, ["hour", "month"], ["By hour of day", "By month of year"], strict=True
    ):
        for city in CITIES:
            part = df[(df["kind"] == kind) & (df["City"] == city)]
            ax.plot(part["x"], part["mean_pm25"], color=CITY_COLOR[city], label=city)
        ax.set_title(title)
        ax.set_ylabel("Mean PM2.5 (µg/m³)")
    axes[0].set_xlabel("Hour of day (IST)")
    axes[1].set_xticks(range(1, 13), MONTHS)
    axes[1].set_xlabel("Month")
    axes[1].legend(ncol=2, fontsize=8)
    fig.suptitle(
        "PM2.5 has a strong winter peak and a daily cycle (data before 2020)",
        x=0.01,
        ha="left",
        fontweight="bold",
        fontsize=11,
    )
    fig.subplots_adjust(top=0.8)
    return save(fig, out_dir, "eda_seasonality.png")


def plot_lockdown(csv_dir: Path, out_dir: Path) -> Path:
    """Delhi weekly PM2.5 in 2019 vs 2020, and the fair vs naive lockdown drop."""
    weekly = pd.read_csv(csv_dir / "weekly_series.csv", parse_dates=["week"])
    delhi = weekly[weekly["City"] == "Delhi"]
    y19 = delhi[delhi["week"] < "2019-07-01"].copy()
    y19["week"] = y19["week"] + pd.Timedelta(days=364)  # align Monday to Monday
    y20 = delhi[delhi["week"] >= "2020-01-01"]
    means = pd.read_csv(csv_dir / "period_means.csv").pivot(
        index="City", columns="period", values="mean_pm25"
    )
    naive = means["2020_mar25_to_jun"] / means["2020_jan_to_mar24"] - 1
    fair = means["2020_mar25_to_jun"] / means["2019_mar25_to_jun"] - 1
    order = fair.sort_values().index

    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.2))
    left.plot(y19["week"], y19["mean_pm25"], color=GRAY, label="2019")
    left.plot(y20["week"], y20["mean_pm25"], color=BLUE, label="2020")
    left.axvline(LOCKDOWN, color=INK2, linestyle="--", linewidth=1)
    left.text(
        LOCKDOWN, left.get_ylim()[1] * 0.97, " lockdown\n starts", fontsize=8, va="top"
    )
    left.set_ylabel("Weekly mean PM2.5 (µg/m³)")
    left.set_title("Delhi: 2020 against the same weeks of 2019")
    left.legend(loc="upper right")
    left.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b"))

    pos = list(range(len(order)))
    height = 0.38
    right.barh(
        [p - height / 2 for p in pos],
        naive[order] * 100,
        height,
        color=GRAY,
        label="Naive: before vs after, same year",
    )
    right.barh(
        [p + height / 2 for p in pos],
        fair[order] * 100,
        height,
        color=BLUE,
        label="Fair: 2020 vs 2019, same dates",
    )
    for p, city in zip(pos, order, strict=True):
        right.text(
            naive[city] * 100 - 1.5,
            p - height / 2,
            f"{naive[city]:.0%}",
            ha="right",
            va="center",
            fontsize=7,
            color=INK2,
        )
        right.text(
            fair[city] * 100 - 1.5,
            p + height / 2,
            f"{fair[city]:.0%}",
            ha="right",
            va="center",
            fontsize=7,
        )
    right.set_yticks(pos, order)
    right.invert_yaxis()
    right.set_xlim(-95, 2)
    right.set_xlabel("Change in mean PM2.5 (%)")
    right.set_title("The season explains part of the drop")
    right.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), fontsize=8)
    right.grid(axis="y", visible=False)
    return save(fig, out_dir, "eda_lockdown.png")


def plot_stations(csv_dir: Path, out_dir: Path) -> Path:
    """Plot stations reporting PM2.5 per year for the selected cities."""
    df = pd.read_csv(csv_dir / "stations_per_year.csv")
    fig, ax = plt.subplots(figsize=(7, 4))
    for city in CITIES:
        part = df[df["City"] == city]
        ax.plot(
            part["year"],
            part["stations"],
            color=CITY_COLOR[city],
            marker="o",
            markersize=5,
            label=city,
        )
    ax.set_ylabel("Stations with PM2.5 data")
    ax.set_title("The measuring network grows: city averages change meaning")
    ax.set_xticks(sorted(df["year"].unique()))
    ax.legend(ncol=2, fontsize=8)
    return save(fig, out_dir, "eda_stations.png")


def plot_distribution(csv_dir: Path, out_dir: Path) -> Path:
    """Share of hours per PM2.5 bin: before the lockdown vs during it."""
    df = pd.read_csv(csv_dir / "histogram.csv")
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    for ax, city in zip(axes, ["Delhi", "Chennai"], strict=True):
        for period, color, label in [
            ("before_lockdown", GRAY, "Before 25 Mar 2020"),
            ("lockdown", BLUE, "Lockdown replay period"),
        ]:
            part = df[(df["City"] == city) & (df["period"] == period)]
            ax.step(
                part["bin"],
                part["n"] / part["n"].sum() * 100,
                where="post",
                color=color,
                label=label,
            )
        ax.set_title(city)
        ax.set_xlabel("PM2.5 (µg/m³, last bin = 500 and above)")
    axes[0].set_ylabel("Share of hours (%)")
    axes[0].legend(fontsize=8)
    fig.suptitle(
        "The whole level shifts down in the lockdown",
        x=0.01,
        ha="left",
        fontweight="bold",
        fontsize=11,
    )
    fig.subplots_adjust(top=0.8)
    return save(fig, out_dir, "eda_distribution.png")


def main(csv_dir: str = "reports/eda", out_dir: str = "docs/img") -> list[Path]:
    """Draw all figures and return their paths."""
    style()
    src, dst = Path(csv_dir), Path(out_dir)
    plots = [
        plot_missing_heatmap,
        plot_coverage,
        plot_seasonality,
        plot_lockdown,
        plot_stations,
        plot_distribution,
    ]
    return [plot(src, dst) for plot in plots]


if __name__ == "__main__":
    for p in main(*sys.argv[1:3]):
        print(p)
