"""Backend settings, read from the environment (docs/LLD.md section 8)."""

import os
from dataclasses import dataclass
from pathlib import Path

from src.common.config import PROJECT_ROOT, load_params, require_env


@dataclass(frozen=True)
class Settings:
    """Everything the backend needs to start. Tests build this directly."""

    ops_api_key: str
    cities: tuple[str, ...]
    model_name: str
    model_server_url: str = "http://model-server:5001"
    serving_path: Path = PROJECT_ROOT / "data/features/serving.parquet"
    reports_dir: Path = PROJECT_ROOT / "reports"
    ops_dir: Path = PROJECT_ROOT / "ops"
    replay_start: str = "2020-03-25 00:00:00"
    replay_end: str = "2020-06-30 23:00:00"
    replay_speed_hps: float = 1.0
    retrain_cooldown_min: int = 30
    drift_min_cities: int = 3
    drift_mae_ratio: float = 1.5

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from params.yaml and environment variables.

        Raises ConfigError if OPS_API_KEY is missing, so the service never
        starts with the ops endpoints unprotected.
        """
        params = load_params()
        paths = params["paths"]

        def path(key: str, *more: str) -> Path:
            return PROJECT_ROOT.joinpath(paths[key], *more)

        return cls(
            ops_api_key=require_env("OPS_API_KEY"),
            cities=tuple(params["cities"]),
            model_name=params["promotion"]["model_name"],
            model_server_url=os.environ.get(
                "MODEL_SERVER_URL", "http://model-server:5001"
            ),
            serving_path=path("features_dir", "serving.parquet"),
            reports_dir=path("reports_dir"),
            ops_dir=Path(os.environ.get("OPS_DIR", PROJECT_ROOT / "ops")),
            replay_start=params["replay"]["start"],
            replay_end=params["replay"]["end"],
            replay_speed_hps=float(os.environ.get("REPLAY_SPEED_HPS", "1.0")),
            retrain_cooldown_min=int(os.environ.get("RETRAIN_COOLDOWN_MIN", "30")),
            drift_min_cities=int(os.environ.get("DRIFT_MIN_CITIES", "3")),
            drift_mae_ratio=float(os.environ.get("DRIFT_MAE_RATIO", "1.5")),
        )
