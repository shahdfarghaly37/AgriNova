# Step 2.1: Crop traits and name mapping

## Files
- `06_build_crop_traits.py`: builds the crop traits table from the project's raw datasets.
- `crop_traits.csv`: one canonical row for each of the five yield-model crops.
- `crop_name_mapping.csv`: records source labels and canonical labels (`corn` -> `maize`).
- `crop_traits_build_report.json`: coverage and limitation report.

## Run
Copy `06_build_crop_traits.py` into the project root (next to `config.py`) and run:

```powershell
python 06_build_crop_traits.py
```

The script reads `data/raw/crop_yield_data.csv` and `data/raw/crop_recommendation.csv`, then writes the three generated files into `data/processed/`.

## Important interpretation
- FAO seasonal crop-water figures represent indicative crop evapotranspiration over the growing season. They are not rainfall or irrigation amounts.
- FAO crop duration values are indicative ranges, not local cultivar guarantees.
- Crop Recommendation quantiles are observed distributions in that dataset, not certified physiological optima.
- `heat_tolerance_class` and `soil_demand_index` are intentionally blank. No defensible crop-specific source has been added for those fields yet.
- The script does not edit raw files, the cleaned yield dataset, training data, or model files.

## Sources
- FAO, Crop Water Needs, Chapter 2: https://www.fao.org/4/s2022e/s2022e02.htm
- FAO, Crop Water Needs, Chapter 3: https://www.fao.org/4/s2022e/s2022e07.htm
