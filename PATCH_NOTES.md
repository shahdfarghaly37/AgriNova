# Step 1 patch notes — Real Data Validation & Cleaning

## `02_clean_and_merge.py`
- Added deterministic validation for `weather_daily.csv`: required columns, date parsing, duplicate `(location_id, date)` keys, location coverage, source counts, date range, and missing percentages. Results are saved to `weather_validation_report.json`.
- Improved optional reference cleaning for pesticides, rainfall, temperature, and FAO yield: normalize column names, parse known numeric fields (including placeholders such as `..`), normalize blank text values, remove exact duplicate rows, and save missing-value / repeated-natural-key diagnostics to `optional_cleaning_report.json`.
- Historical temperature years from 1743 onward are retained; the previous arbitrary lower bound of 1800 was too restrictive.
- Repeated country-year groups in temperature are reported, not aggregated or deleted, because records may have different values and the source does not explain the duplicate grain.
- Corrected the 247K duplicate counter so it reports exact duplicates removed from the original in-memory frame.
- The datasets remain separate; no unsupported row-level joins were introduced.

## `04_build_master.py`
- Added crop-name normalization and the known alias `corn` → `maize`.
- Reports unmatched labels explicitly. `soybean` and `wheat` remain unmatched because they are not among the Crop Recommendation profiles.
- Keeps one authoritative `rain_90d_mm` column from current climate data instead of creating `_x` / `_y` duplicates.
- Rounds numeric columns only, avoiding pandas datetime rounding warnings.

## Documentation
- Updated `README.md` with cleaning reports, crop mapping behavior, and Step 1 validation notes.

## Deliberately not changed
- `01_fetch_weather.py` was not run against the network again. Existing weather cache and processed NASA weather data were validated and reused.
- `03_train_model.py` and model training were not changed or rerun; they belong to the next modeling step.
