# Data Notes (Stage 0 quick profile)

Source: CPCB "Air Quality Data in India (2015-2020)", Kaggle, CC0. Files in `data/raw/`.
Method: single pass over each CSV with the Python standard-library `csv` module (no Spark, no pandas).
"Missing" means an empty PM2.5 field.

## Files

| File | Rows | Cols | Keys | Date range | PM2.5 missing |
|------|-----:|-----:|------|-----------|--------------:|
| city_day.csv | 29,531 | 16 | 26 cities | 2015-01-01 .. 2020-07-01 | 15.6% |
| city_hour.csv | 707,875 | 16 | 26 cities | 2015-01-01 01:00 .. 2020-07-01 00:00 | 20.5% |
| station_day.csv | 108,035 | 16 | 110 stations | 2015-01-01 .. 2020-07-01 | 20.0% |
| station_hour.csv | 2,589,083 | 16 | 110 stations | 2015-01-01 01:00 .. 2020-07-01 00:00 | 25.0% |
| stations.csv | 230 | 5 | 230 stations | – | – |

Columns (all four measurement files):
`City|StationId, Date|Datetime, PM2.5, PM10, NO, NO2, NOx, NH3, CO, SO2, O3, Benzene, Toluene, Xylene, AQI, AQI_Bucket`

`stations.csv`: `StationId, StationName, City, State, Status`. The file starts with a UTF-8 BOM, so read it with `utf-8-sig`.
It lists 230 stations, but only 110 have measurements.

## PM2.5 missing share by year (city_hour)

| 2015 | 2016 | 2017 | 2018 | 2019 | 2020 |
|-----:|-----:|-----:|-----:|-----:|-----:|
| 36% | 30% | 35% | 19% | 10% | 9% |

Coverage improves sharply from 2018 onwards. Many cities only start in 2017-2020.

## Per-city view (city_hour)

| City | Rows | PM2.5 missing | First PM2.5 | Mean PM2.5 1 Jan-24 Mar 2020 | Mean PM2.5 25 Mar-31 May 2020 |
|------|-----:|-----:|-----------|-----:|-----:|
| Delhi | 48,192 | 1% | 2015-01-01 | 118 | 48 |
| Chennai | 48,192 | 7% | 2015-03-23 | 38 | 18 |
| Lucknow | 48,192 | 7% | 2015-03-20 | 106 | 55 |
| Hyderabad | 48,107 | 7% | 2015-03-31 | 45 | 31 |
| Bengaluru | 48,192 | 10% | 2015-03-20 | 41 | 23 |
| Gurugram | 40,258 | 15% | 2016-01-22 | 90 | 46 |
| Patna | 44,554 | 26% | 2015-10-01 | 95 | 37 |
| Ahmedabad | 48,192 | 35% | 2015-01-28 | 60 | 29 |
| Kolkata | 19,503 | 7% | 2018-04-10 | 79 | 23 |
| Jaipur | 26,705 | 2% | 2017-06-19 | 48 | 33 |
| Mumbai | 48,192 | 62% | 2018-04-26 | 60 | 19 |
| (15 more cities, shorter or sparser history) | | | | | |

## Implications for the build

1. **Use `city_hour.csv` as the main table.** It matches the "selected city, 1h and 24h ahead" problem directly
   and is about 3.6x smaller than `station_hour.csv`. Station files are ingested for completeness but not modelled.
2. **The lockdown drift is strong and real.** After 25 Mar 2020, PM2.5 roughly halves in every city
   (Delhi 118 -> 48, Kolkata 79 -> 23). Replaying 25 Mar - 30 Jun 2020 in time order should trip a PSI/KS drift detector clearly.
3. **Missing values must be handled before lag features.** Plan: drop rows with missing targets, and forward-fill
   short gaps (≤ 3h) in lag inputs only. LightGBM tolerates the remaining NaNs natively.
4. **Start with a city shortlist.** Cities with long history and < 15% missing PM2.5: Delhi, Chennai, Lucknow,
   Hyderabad, Bengaluru, Jaipur, Kolkata. Mumbai is excluded because 62% of its PM2.5 values are missing.
5. **AQI and AQI_Bucket are blank for about 18% of hourly rows** (129,080 of 707,875). The app computes the PM2.5 AQI
   category itself from CPCB breakpoints instead of relying on these columns.
6. **Reading speed (stdlib, single core): about 1M rows/s** (station_hour 2.59M rows in 2.5 s). This is the
   baseline to compare Spark ingest against in `docs/metrics.md`.
