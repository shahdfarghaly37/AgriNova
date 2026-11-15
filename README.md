# Farmer Imposters - corrected data pipeline

## Folder layout

Keep the six supplied source CSV files inside `data/raw/` with these exact names:

- `crop_recommendation.csv`
- `crop_yield_data.csv`
- `pesticides.csv`
- `rainfall.csv`
- `temp.csv`
- `yield.csv`

The scripts expect this project structure:

```text
project/
  config.py
  01_fetch_weather.py
  02_clean_and_merge.py
  03_train_model.py
  04_build_master.py
  data/
    raw/
    processed/
      master/
```

## Install

```bash
python -m pip install -r requirements.txt
```

## Run order

Run these commands from the project root:

```bash
python 01_fetch_weather.py
python 02_clean_and_merge.py
python 03_train_model.py
python 04_build_master.py
```

## What each script does

1. `01_fetch_weather.py`: downloads daily weather for the ten configured Egyptian locations. NASA POWER is primary, Open-Meteo Archive is fallback. Solar radiation is converted from MJ/m²/day to kWh/m²/day. Weather is cached per location in `data/raw/weather_<location>.csv`.
2. `02_clean_and_merge.py`: validates and cleans the supplied datasets, builds crop ideal-condition profiles, and creates climate drift, current climate and climate-fit tables. Optional reference datasets are cleaned independently, exact duplicate rows are removed, missing-value summaries are recorded, and datasets with incompatible grains are not row-merged.
3. `03_train_model.py`: trains Ridge and Random Forest yield regressors on the 247K dataset and compares held-out metrics. It does not replace training rainfall/temperature with NASA values.
4. `04_build_master.py`: creates app-facing and analysis-facing master CSVs, normalizes known crop aliases (for example, corn → maize), reports unmatched crop labels, and avoids duplicate rainfall columns and datetime-rounding warnings.

## Outputs

`data/processed/`:
- `crops_profile.csv`
- `agri_247k_clean.csv`
- `cleaning_report.json`
- `optional_cleaning_report.json`
- `weather_validation_report.json`
- `weather_daily.csv`
- `climate_drift.csv`
- `current_climate.csv`
- `fit_scores.csv`
- `pesticides_clean.csv`, `rainfall_clean.csv`, `temperature_clean.csv`, `fao_yield_clean.csv` (when source files exist)
- `optional_cleaning_report.json` (row counts, exact duplicates, repeated-key groups and missing-value percentages)
- `metrics.json`
- `yield_model.joblib`
- `feature_importance.csv`

`data/processed/master/`:
- `master_training.csv`
- `master_weather_monthly.csv`
- `master_location_crop.csv`
- `data_dictionary.csv`

## Important modeling limitations

- The 247K yield source is treated as synthetic/unverified based on the project brief. Its test metrics are not evidence of real-world Egyptian farm accuracy.
- The 247K source has five crop labels, while Crop Recommendation has 22. Only matching crop names receive crop-profile features. Do not assume a yield prediction is available for all 22 crops.
- The FAO yield, country-level rainfall, country-level temperature and pesticide tables are kept as separate reference datasets. Their grain and units do not support blind row-level merging with the other sources.
- NASA's recent 90-day rainfall total is not automatically equivalent to the 247K dataset's `rainfall_mm`. Therefore, the new pipeline does not substitute NASA climate values into the yield model.
- `fit_score`, generic GDD base 10°C and heat-day threshold 35°C are prototype indicators. They are not crop-specific agronomic advice.
- Open-Meteo fallback data does not provide humidity in this request, so humidity-based fit is omitted when unavailable.

## Re-running

The weather fetcher uses a cache. Delete `data/raw/weather_<location>.csv` for a location if you intentionally want to fetch it again. The cache is refreshed when it is missing, malformed, or too old.


## Step 1 validation notes

- The temperature reference begins before 1800; historical years are retained (valid year range used by cleaning is 1000–2100).
- Repeated country-year groups in the temperature reference are reported for review rather than silently aggregated. Exact duplicate rows are removed.
- Crop labels `corn`, `cotton`, and `rice` can match the Crop Recommendation crop profiles after alias normalization. `soybean` and `wheat` remain unmatched because those crop profiles are not present in the 22-class Crop Recommendation dataset.
- The location-crop master keeps one authoritative `rain_90d_mm` column from current climate data.
