# Farmer Imposters: Status after the full backend pass (no website yet)

## Run order (PowerShell, from D:\NASA)
    python 03_train_model.py          # yield model v2 with 5-fold CV (slow: Random Forest, about 10 min)
    python 07_build_crop_knowledge.py # wheat/soybean profiles, heat class, soil demand, GDD params
    python 04_build_master.py         # master tables (now 100% crop-name match)
    python 05_validate_master.py
    python 10_crop_classifier.py
    python 09_engine.py --build-final # writes data/final/*.csv
    python 09_engine.py --mode suggest --lat 30.79 --lon 31.0 --soil clay --ph 7.8 --water medium --irrigation flood --goal balanced
(01, 02 and 06 are unchanged. 07 must run before 04.)

## What was wrong and is now fixed
1. 03_train_model.py silently dropped ALL categorical columns (crop_type, soil_type, season, ...)
   because pandas 3 reads text as dtype "str", not "object". Fixed. Test R2 0.215 -> 0.840.
2. corn/maize was already mapped correctly. The real gap was wheat and soybean having no
   profile. They now get temperature, humidity and pH profiles from the top-yield quartile of the
   247K dataset (synthetic, labeled). N, P, K, rainfall stay empty on purpose (different units).
   Name match is 100%, missing ideal_* features for temperature, humidity, pH: 0%.
3. Datetime/round warning in 04: rounding now applies to numeric columns only.
4. heat_tolerance_class and soil_demand_index filled in crop_traits.csv (rules in 07, literature-indicative).

## Yield model v2 (synthetic dataset, experimental)
| Model | CV R2 (5-fold, 50K subsample) | Test R2 | Test MAE |
|---|---|---|---|
| Ridge | 0.4375 | 0.4378 | 2.66 |
| Random Forest | 0.7565 | 0.7822 | 1.63 |
| HistGradientBoosting (selected) | 0.8262 +- 0.0010 | 0.8403 | 1.39 |
Top drivers: crop_type, avg_temp_c, rainfall_mm. Metrics describe this synthetic dataset only.

## Crop classifier (Crop Recommendation, 22 crops)
Random Forest: CV accuracy 0.9938, test 0.9932. Dataset is near-separable, so this proves the
profiles are distinct, not field accuracy. Not used inside the ranking (needs N, P, K, rainfall).

## Engine (09_engine.py)
Scores 0-100 per crop: temp_fit, heat_score, water_score, soil_fit (pH), soil_impact_score (proxy),
yield_score (experimental), season_fit. Goal weights: balanced, max_yield, save_water, protect_soil.
Also: GDD harvest date, climate-best planting start (within +-1 month of the calendar window),
explanations and warnings. Modes: Check My Crop, Suggest Crops (top 5 core crops + 3 limited-data
extras), Compare Crops. GPS snaps to the nearest of 10 governorates and warns beyond 150 km.

## Assumptions to defend or verify before the final presentation
- crop_knowledge.csv (temperature ranges, heat thresholds, GDD base and totals, pH ranges, nutrient
  demand) are indicative literature values, flagged knowledge_status = verify_before_final.
- Climate = mean of the last 5 years (2022 onward) by day of year per governorate (NASA POWER grid).
  NASA grid Tmax can run warmer than station data; summer heat risk is therefore high everywhere.
- Heat share is counted on the flowering/filling stage (40% to 80% of the season).
- Water capacity per season: low 500, medium 1000, high 1500 mm (assumption). Efficiencies: flood 0.60,
  sprinkler 0.75, drip 0.90. Effective rain = 80%.
- Yield: only avg_temp_c comes from NASA. Other inputs sit at dataset medians. Treat as an index.
- Soil impact is a rotation and nutrient-demand proxy, not soil degradation measurement.
- Only 5 crops have full analysis. The other 19-20 crops get climate + pH only.
- Rice area is regulated by water policy in Egypt and is not modeled.
