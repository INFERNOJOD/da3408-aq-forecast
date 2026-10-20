"""Offline drift replay: the Stage 11 acceptance test.

Replays the replay window (25 March to 30 June) hour by hour, for the 2020
lockdown and for the same calendar weeks of every reference year (2016-2019),
and applies the drift rule of ``src.monitoring.drift`` at every hour.

- 2020 is scored against the saved reference (``reports/baseline_stats.json``).
- A reference year Y is scored against a reference built from the other years
  only (leave-one-year-out), the same way the thresholds were computed.

The test passes when the lockdown triggers drift at least once and no hour of
a reference year does. Results go to ``reports/drift_replay.json``.

Usage:
    python -m scripts.replay              # PSI rule only
    python -m scripts.replay --with-mae   # also the pooled 72 h MAE ratio of
                                          # the champion (needs the registry)
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from src.common.config import PROJECT_ROOT, load_env, load_params
from src.common.logging_setup import configure_logging, get_logger
from src.common.schema import FEATURE_COLUMNS
from src.monitoring.drift import DriftDetector, reference_bins

log = get_logger(__name__)

MAE_WINDOW_H = 72


def load_frames(features_dir: Path) -> pd.DataFrame:
    """Training rows before the replay year plus the serving rows, one frame."""
    train = pd.read_parquet(features_dir / "train.parquet")
    serving = pd.read_parquet(features_dir / "serving.parquet")
    frame = pd.concat([train, serving], ignore_index=True)
    frame["Datetime"] = pd.to_datetime(frame["Datetime"])
    return frame.drop_duplicates(["City", "Datetime"], keep="last").reset_index(
        drop=True
    )


def add_replay_hour(frame: pd.DataFrame, start: datetime, n_hours: int) -> pd.DataFrame:
    """Keep rows inside the replay's calendar window of their year; add ``rh``."""
    anchor = pd.to_datetime(
        {
            "year": frame["Datetime"].dt.year,
            "month": start.month,
            "day": start.day,
            "hour": start.hour,
        }
    )
    frame = frame.assign(
        year=frame["Datetime"].dt.year,
        rh=((frame["Datetime"] - anchor).dt.total_seconds() // 3600).astype(int),
    )
    return frame[(frame["rh"] >= 0) & (frame["rh"] < n_hours)].reset_index(drop=True)


def loyo_reference(
    frame: pd.DataFrame,
    city: str,
    year: int,
    years: list[int],
    n_bins: int,
    week_h: int,
) -> list[dict]:
    """Build the reference blocks of ``city`` from every year except ``year``."""
    other = frame[
        (frame["City"] == city)
        & frame["year"].isin([y for y in years if y != year])
        & frame["pm25_lag_1"].notna()
    ]
    blocks = []
    for block in range(int(frame["rh"].max()) // week_h + 1):
        values = other.loc[other["rh"] // week_h == block, "pm25_lag_1"].to_numpy()
        if len(values) == 0:
            blocks.append({"edges": [], "proportions": [1.0]})
            continue
        edges, props = reference_bins(values, n_bins)
        blocks.append({"edges": edges, "proportions": props})
    return blocks


def episodes(flags: pd.Series, start: datetime) -> list[dict]:
    """Group consecutive drift hours into runs of {first, last, hours}."""
    out, run = [], []
    for h, on in flags.items():
        if on:
            run.append(h)
        elif run:
            out.append(run)
            run = []
    if run:
        out.append(run)
    return [
        {
            "first": str(start + pd.Timedelta(hours=r[0])),
            "last": str(start + pd.Timedelta(hours=r[-1])),
            "hours": len(r),
        }
        for r in out
    ]


def replay_year(
    frame: pd.DataFrame,
    year: int,
    detector: DriftDetector,
    start: datetime,
    n_hours: int,
) -> dict:
    """Apply the rule at every hour of one year's window; summarise the result."""
    rows = frame[frame["year"] == year]
    lag = rows.pivot(index="rh", columns="City", values="pm25_lag_1").reindex(
        range(n_hours)
    )
    cities = [c for c in lag.columns if lag[c].notna().sum() > 0]
    scored = []
    for h in range(detector.window_h - 1, n_hours):
        windows = {
            c: lag[c].to_numpy()[h - detector.window_h + 1 : h + 1] for c in cities
        }
        out = detector.evaluate(windows, h)
        scored.append(
            {"h": h, "n": out["cities_exceeding"], "exceeding": out["exceeding"]}
        )
    table = pd.DataFrame(scored).set_index("h")
    drift = table["n"] >= detector.min_cities
    year_start = start.replace(year=year)
    per_city = {
        c: int(sum(c in e for e in table["exceeding"]))
        for c in cities
        if c in detector.thresholds
    }
    return {
        "year": year,
        "voting_cities": sorted(per_city),
        "hours_scored": len(table),
        "drift_hours": int(drift.sum()),
        "first_drift": str(year_start + pd.Timedelta(hours=int(drift.idxmax())))
        if drift.any()
        else None,
        "episodes": episodes(drift, year_start),
        "max_cities_exceeding": int(table["n"].max()),
        "hours_with_at_least_k_cities": {
            str(k): int((table["n"] >= k).sum()) for k in range(1, 7)
        },
        "exceed_hours_per_city": per_city,
    }


def mae_ratios(frame: pd.DataFrame, n_hours: int, model_name: str) -> dict:
    """Pooled 72 h MAE ratio of the champion's 1 h forecast, per year."""
    import mlflow
    from src.pipeline.registry import ModelRegistryClient

    registry = ModelRegistryClient(model_name)
    version = registry.champion_version()
    tags = next(v["tags"] for v in registry.versions() if v["version"] == version)
    denominator = float(tags["mae_1h"])
    model = mlflow.pyfunc.load_model(f"models:/{model_name}@champion")
    x = frame.assign(horizon_h=1)[["horizon_h", *FEATURE_COLUMNS]]
    err = (model.predict(x)["pm25"].to_numpy() - frame["y_1h"]).abs()
    frame = frame.assign(err=err)
    out = {"champion_version": version, "denominator_mae_1h": denominator}
    for year, rows in frame.groupby("year"):
        piv = rows.pivot(index="rh", columns="City", values="err").reindex(
            range(n_hours)
        )
        ratios = []
        for h in range(24, n_hours):
            window = piv.iloc[max(0, h - MAE_WINDOW_H) : h].to_numpy().ravel()
            window = window[~np.isnan(window)]
            if len(window):
                ratios.append(window.mean() / denominator)
        s = pd.Series(ratios)
        out[str(year)] = {
            "median": round(float(s.median()), 3),
            "p95": round(float(s.quantile(0.95)), 3),
            "max": round(float(s.max()), 3),
            "hours_above_1_5": int((s > 1.5).sum()),
        }
    return out


def run(params: dict, with_mae: bool) -> dict:
    """Run the replay for every year and return the report."""
    paths = params["paths"]
    reports = PROJECT_ROOT / paths["reports_dir"]
    baseline = json.loads((reports / "baseline_stats.json").read_text())
    thresholds_doc = json.loads((reports / "drift_thresholds.json").read_text())
    thresholds = {c: v["psi_threshold"] for c, v in thresholds_doc["cities"].items()}
    fp = params["features"]
    min_cities = params["drift"]["min_cities"]
    week_h, n_bins = baseline["week_hours"], baseline["n_bins"]
    start = datetime.fromisoformat(params["replay"]["start"])
    n_hours = baseline["replay_hours"]
    first, last = fp["baseline_years"]
    years = list(range(first, last + 1))

    frame = add_replay_hour(
        load_frames(PROJECT_ROOT / paths["features_dir"]), start, n_hours
    )
    results = []
    for year in years:
        reference = {
            c: loyo_reference(frame, c, year, years, n_bins, week_h)
            for c in params["cities"]
        }
        detector = DriftDetector(reference, thresholds, min_cities, week_h)
        results.append(replay_year(frame, year, detector, start, n_hours))
        log.info("Year %d: %d drift hours", year, results[-1]["drift_hours"])
    live = {c: v["weeks"] for c, v in baseline["cities"].items()}
    detector = DriftDetector(live, thresholds, min_cities, week_h)
    lockdown = replay_year(frame, start.year, detector, start, n_hours)
    log.info("Lockdown %d: %d drift hours", start.year, lockdown["drift_hours"])

    false_alarm_hours = sum(r["drift_hours"] for r in results)
    report = {
        "rule": f"at least {min_cities} voting cities with PSI above their threshold",
        "min_cities": min_cities,
        "thresholds": thresholds,
        "normal_years": results,
        "lockdown": lockdown,
        "acceptance": {
            "lockdown_triggers": lockdown["drift_hours"] > 0,
            "normal_weeks_quiet": false_alarm_hours == 0,
            "false_alarm_hours": false_alarm_hours,
        },
    }
    report["acceptance"]["passed"] = (
        report["acceptance"]["lockdown_triggers"]
        and report["acceptance"]["normal_weeks_quiet"]
    )
    if with_mae:
        report["mae_ratio_pooled_72h"] = mae_ratios(
            frame, n_hours, params["promotion"]["model_name"]
        )
    (reports / "drift_replay.json").write_text(json.dumps(report, indent=2))
    return report


def main(argv: list[str] | None = None) -> int:
    """Print a summary; exit code 0 only if the acceptance test passed."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--with-mae", action="store_true", help="also score MAE ratio")
    args = parser.parse_args(argv)
    configure_logging()
    load_env()
    report = run(load_params(), args.with_mae)
    for r in [*report["normal_years"], report["lockdown"]]:
        print(
            f"{r['year']}: drift {r['drift_hours']:4d} of {r['hours_scored']} h, "
            f"{len(r['episodes'])} episodes, max cities {r['max_cities_exceeding']}, "
            f"first {r['first_drift']}"
        )
    acc = report["acceptance"]
    print(f"acceptance: {'PASSED' if acc['passed'] else 'FAILED'} {acc}")
    return 0 if acc["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
