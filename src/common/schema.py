"""Single source of truth for model input and target column names.

The feature stage builds these columns, the training stage reads them, and the
backend sends them to the model server. docs/LLD.md section 4 lists the same
names; a test checks that this file and the document agree.
"""

# PM2.5 lag k is the value k-1 hours before the forecast time t, so lag 1 is the
# current hour. Lags use a short forward-fill (see params.yaml features).
PM25_LAGS = (1, 2, 3, 24, 168)

# Rolling windows over the last n hours up to and including t: (name, n).
ROLL_MEAN_WINDOWS = (6, 24)
ROLL_STD_WINDOWS = (24,)

# Other pollutants: only the current-hour value is used. column -> feature name.
CO_POLLUTANT_FEATURES = {
    "PM10": "pm10_lag_1",
    "NO2": "no2_lag_1",
    "CO": "co_lag_1",
    "SO2": "so2_lag_1",
    "O3": "o3_lag_1",
}

CALENDAR_FEATURES = ["hour", "dow", "month", "is_weekend"]

# Forecast horizons in hours and the target column for each.
HORIZONS = {1: "y_1h", 24: "y_24h"}
TARGETS = list(HORIZONS.values())

# Columns stored in data/features/*.parquet (one row per city and hour).
FEATURE_COLUMNS = (
    ["city_code"]
    + CALENDAR_FEATURES
    + [f"pm25_lag_{k}" for k in PM25_LAGS]
    + [f"pm25_roll_mean_{n}" for n in ROLL_MEAN_WINDOWS]
    + [f"pm25_roll_std_{n}" for n in ROLL_STD_WINDOWS]
    + list(CO_POLLUTANT_FEATURES.values())
)

# Columns sent to the model server: one row per (city, horizon).
FEATURES = ["horizon_h"] + FEATURE_COLUMNS

# Bookkeeping columns kept next to the features in the stored files.
ID_COLUMNS = ["City", "Datetime"]
ACTUAL_COLUMN = "pm25"  # the observed PM2.5 at hour t (not forward-filled)
