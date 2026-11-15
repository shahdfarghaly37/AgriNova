"""Validate and clean source datasets, then build climate and crop-fit tables.

Important: datasets are NOT row-merged. They have different grains and no shared
farm/date key. Crop names are used only for a limited knowledge lookup.
"""
import json
import numpy as np
import pandas as pd
from config import (
    F_CROP_REC, F_AGRI_247K, F_PESTICIDES, F_RAINFALL, F_TEMP, F_YIELD_FAO,
    PROC, LOCATIONS, BASELINE_YEARS, RECENT_YEARS,
)


def normalize_columns(df):
    df = df.copy()
    df.columns = (
        pd.Index(df.columns).astype(str).str.strip().str.lower()
        .str.replace(r"[^a-z0-9]+", "_", regex=True).str.strip("_")
    )
    return df


def require_file(path):
    if not path.exists():
        raise FileNotFoundError(f"Required input file not found: {path}")
    return path


def build_crop_profile():
    df = normalize_columns(pd.read_csv(require_file(F_CROP_REC)))
    df = df.rename(columns={"label": "crop"})
    required = ["n", "p", "k", "temperature", "humidity", "ph", "rainfall", "crop"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Crop recommendation dataset is missing columns: {missing}")

    for col in required[:-1]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["crop"] = df["crop"].astype(str).str.strip().str.lower()
    df = df.dropna(subset=required)
    if df.empty:
        raise ValueError("No valid rows remain in Crop Recommendation dataset.")

    grouped = df.groupby("crop")[required[:-1]]
    profile = pd.concat({
        "mean": grouped.mean(),
        "std": grouped.std(),
        "q10": grouped.quantile(0.10),
        "q90": grouped.quantile(0.90),
    }, axis=1)
    profile.columns = [f"{feature}_{stat}" for stat, feature in profile.columns]
    profile = profile.reset_index()
    profile.to_csv(PROC / "crops_profile.csv", index=False)
    print(f"Crop profile saved: {len(profile)} crops.")
    return profile


def clean_247k():
    df = normalize_columns(pd.read_csv(require_file(F_AGRI_247K)))
    required = {"crop_type", "crop_yield_tons"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"247K dataset missing required columns {sorted(missing)}. Found: {list(df.columns)}")

    original_rows = len(df)
    duplicate_rows = int(df.duplicated().sum())
    df = df.drop_duplicates().copy()

    # Normalize crop names across all project datasets.
    crop_name_mapping = {
        "corn": "maize",
        "maize": "maize",
        "cotton": "cotton",
        "rice": "rice",
        "soybean": "soybean",
        "wheat": "wheat",
    }

    df["crop_type"] = (
        df["crop_type"]
        .astype("string")
        .str.strip()
        .str.lower()
        .replace(crop_name_mapping)
    )
     
    numeric_candidates = [
        "soil_ph", "irrigation_mm", "days_from_last_harvest",
        "nitrogen_kg_ha", "rainfall_mm", "avg_temp_c", "phosphorus_kg_ha",
        "humidity_pct", "pest_index", "potassium_kg_ha", "crop_yield_tons",
    ]
    for col in numeric_candidates:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Mark physically invalid values missing instead of silently clipping them.
    invalid_rules = {
        "soil_ph": lambda s: (s < 0) | (s > 14),
        "humidity_pct": lambda s: (s < 0) | (s > 100),
        "rainfall_mm": lambda s: s < 0,
        "irrigation_mm": lambda s: s < 0,
        "days_from_last_harvest": lambda s: s < 0,
        "nitrogen_kg_ha": lambda s: s < 0,
        "phosphorus_kg_ha": lambda s: s < 0,
        "potassium_kg_ha": lambda s: s < 0,
        "pest_index": lambda s: (s < 0) | (s > 100),
        "crop_yield_tons": lambda s: s < 0,
    }
    invalid_counts = {}
    for col, rule in invalid_rules.items():
        if col in df:
            mask = rule(df[col])
            invalid_counts[col] = int(mask.sum())
            df.loc[mask, col] = np.nan

    # A missing/invalid target cannot be used for supervised training.
    df = df.dropna(subset=["crop_yield_tons"]).copy()

    categorical = [
        c for c in df.columns
        if c not in numeric_candidates and not pd.api.types.is_numeric_dtype(df[c])
    ]
    for col in categorical:
        df[col] = (
            df[col].astype("string").str.strip().str.lower()
            .replace({"": pd.NA, "nan": pd.NA, "none": pd.NA, "null": pd.NA})
        )

    report = {
        "source_rows": int(original_rows),
        "rows_after_duplicate_removal_and_target_validation": int(len(df)),
        "duplicates_removed": duplicate_rows,
        "invalid_values_marked_missing": invalid_counts,
        "missing_pct_after_cleaning": (df.isna().mean() * 100).round(2).to_dict(),
        "crop_types": sorted(df["crop_type"].dropna().astype(str).unique().tolist()),
        "note": "No percentile clipping was applied; extreme values require EDA review.",
    }
    df.to_csv(PROC / "agri_247k_clean.csv", index=False)
    (PROC / "cleaning_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"247K rows: {original_rows:,} -> {len(df):,}")
    print("Crop types:", report["crop_types"])
    return df


def _coerce_numeric_columns(df, candidates):
    """Convert known measurement columns to numeric; invalid tokens become NaN."""
    for col in candidates:
        if col in df.columns:
            # Handles source placeholders such as '..' without treating them as zero.
            df[col] = pd.to_numeric(
                df[col].astype("string").str.strip().replace({"..": pd.NA, "": pd.NA, "-": pd.NA}),
                errors="coerce",
            )
    return df


def clean_optional_reference_files():
    """Clean optional references independently; never merge incompatible data grains."""
    specs = {
        F_PESTICIDES: {
            "output": "pesticides_clean.csv",
            "numeric": ["year", "value"],
            "keys": ["domain", "area", "element", "item", "year", "unit"],
        },
        F_RAINFALL: {
            "output": "rainfall_clean.csv",
            "numeric": ["year", "average_rain_fall_mm_per_year"],
            "keys": ["area", "year"],
        },
        F_TEMP: {
            "output": "temperature_clean.csv",
            "numeric": ["year", "avg_temp"],
            "keys": ["country", "year"],
        },
        F_YIELD_FAO: {
            "output": "fao_yield_clean.csv",
            "numeric": ["area_code", "element_code", "item_code", "year_code", "year", "value"],
            "keys": ["area_code", "item_code", "element_code", "year", "unit"],
        },
    }
    report = {}
    for source, spec in specs.items():
        if not source.exists():
            print(f"[optional missing] {source.name}")
            continue

        df = normalize_columns(pd.read_csv(source, na_values=["..", "...", "", "NA", "N/A"]))
        source_rows = len(df)
        df = _coerce_numeric_columns(df, spec["numeric"])

        # Normalize text dimensions but preserve their readable labels.
        for col in df.select_dtypes(include=["object", "string"]).columns:
            df[col] = df[col].astype("string").str.strip().replace({"": pd.NA})

        # Remove exact duplicate records first. Key duplicates are reported, not
        # automatically collapsed: repeated observations can be legitimate.
        exact_duplicates = int(df.duplicated().sum())
        df = df.drop_duplicates().copy()
        key_columns = [c for c in spec["keys"] if c in df.columns]
        key_duplicate_rows = int(df.duplicated(subset=key_columns, keep=False).sum()) if key_columns else 0

        if "year" in df.columns:
            invalid_year = df["year"].notna() & ~df["year"].between(1000, 2100)
            df.loc[invalid_year, "year"] = np.nan

        output = PROC / spec["output"]
        df.to_csv(output, index=False)
        report[spec["output"]] = {
            "source_rows": int(source_rows),
            "rows_after_exact_deduplication": int(len(df)),
            "exact_duplicates_removed": exact_duplicates,
            "rows_in_duplicate_key_groups_review_required": key_duplicate_rows,
            "rows_missing_key_fields": int(df[key_columns].isna().any(axis=1).sum()) if key_columns else 0,
            "missing_pct": (df.isna().mean() * 100).round(2).to_dict(),
            "columns": list(df.columns),
        }
        print(
            f"Saved {spec['output']}: {len(df):,} rows; "
            f"removed {exact_duplicates:,} exact duplicates; "
            f"{key_duplicate_rows:,} rows belong to repeated natural-key groups."
        )

    (PROC / "optional_cleaning_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    return report



def validate_weather_file():
    """Run deterministic checks on the already-fetched daily weather file."""
    path = PROC / "weather_daily.csv"
    if not path.exists():
        raise FileNotFoundError("weather_daily.csv not found. Run 01_fetch_weather.py first.")
    weather = pd.read_csv(path)
    required = ["date", "location_id", "temp_mean", "temp_max", "temp_min", "precip_mm"]
    missing_columns = [c for c in required if c not in weather.columns]
    if missing_columns:
        raise ValueError(f"weather_daily.csv missing required columns: {missing_columns}")
    weather["date"] = pd.to_datetime(weather["date"], errors="coerce")
    duplicate_location_dates = int(weather.duplicated(["location_id", "date"]).sum())
    invalid_dates = int(weather["date"].isna().sum())
    location_counts = weather.groupby("location_id").size().to_dict()
    report = {
        "rows": int(len(weather)),
        "locations": int(weather["location_id"].nunique()),
        "date_min": weather["date"].min().date().isoformat() if weather["date"].notna().any() else None,
        "date_max": weather["date"].max().date().isoformat() if weather["date"].notna().any() else None,
        "duplicate_location_date_rows": duplicate_location_dates,
        "invalid_dates": invalid_dates,
        "missing_pct": (weather.isna().mean() * 100).round(2).to_dict(),
        "source_counts": weather["source"].value_counts(dropna=False).to_dict() if "source" in weather else {},
        "rows_per_location": location_counts,
    }
    (PROC / "weather_validation_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    if duplicate_location_dates or invalid_dates:
        raise ValueError(
            "Weather validation failed: duplicate location/date rows or invalid dates found. "
            "See weather_validation_report.json."
        )
    print(
        f"Weather validation passed: {report['rows']:,} rows across "
        f"{report['locations']} locations; no duplicate location/date keys."
    )
    return weather

def build_climate_tables():
    weather_path = PROC / "weather_daily.csv"
    if not weather_path.exists():
        raise FileNotFoundError("weather_daily.csv not found. Run 01_fetch_weather.py first.")

    weather = validate_weather_file()
    required = {"date", "location_id", "temp_mean", "temp_max", "temp_min", "precip_mm"}
    missing = required - set(weather.columns)
    if missing:
        raise ValueError(f"weather_daily.csv missing columns: {sorted(missing)}")

    weather["year"] = weather["date"].dt.year
    weather["month"] = weather["date"].dt.month

    baseline = (
        weather[weather["year"].between(*BASELINE_YEARS)]
        .groupby(["location_id", "month"])["temp_mean"]
        .mean().rename("baseline_temp").reset_index()
    )
    recent_start = int(weather["year"].max()) - RECENT_YEARS + 1
    recent = (
        weather[weather["year"].between(recent_start, weather["year"].max())]
        .groupby(["location_id", "month"])["temp_mean"]
        .mean().rename("recent_temp").reset_index()
    )
    drift = baseline.merge(recent, on=["location_id", "month"], how="outer")
    drift["delta_c"] = drift["recent_temp"] - drift["baseline_temp"]
    drift["comparison_start_year"] = recent_start
    drift.to_csv(PROC / "climate_drift.csv", index=False)

    current_rows = []
    for location_id, group in weather.groupby("location_id"):
        group = group.sort_values("date")
        latest = group["date"].max()
        last14 = group[group["date"] > latest - pd.Timedelta(days=14)]
        last90 = group[group["date"] > latest - pd.Timedelta(days=90)]
        current_rows.append({
            "location_id": location_id,
            "as_of": latest.date().isoformat(),
            "temp_mean_14d": last14["temp_mean"].mean(),
            "temp_max_14d": last14["temp_max"].mean(),
            "humidity_14d": last14["humidity_pct"].mean() if "humidity_pct" in last14 else np.nan,
            "rain_90d_mm": last90["precip_mm"].sum(min_count=1),
            "weather_source": ", ".join(sorted(group["source"].dropna().astype(str).unique()))
                if "source" in group else "unknown",
            "n_days_14d": int(last14["temp_mean"].notna().sum()),
            "n_days_90d": int(last90["precip_mm"].notna().sum()),
        })
    current = pd.DataFrame(current_rows)
    current.to_csv(PROC / "current_climate.csv", index=False)
    print("Current climate saved:")
    print(current.to_string(index=False))
    return current


def build_fit_scores(current, profile):
    rows = []
    for _, location in current.iterrows():
        for _, crop in profile.iterrows():
            z_scores = []
            temp_mean = crop.get("temperature_mean", np.nan)
            temp_std = crop.get("temperature_std", np.nan)
            if pd.notna(location["temp_mean_14d"]) and pd.notna(temp_mean):
                z_scores.append(
                    (location["temp_mean_14d"] - temp_mean) /
                    max(float(temp_std) if pd.notna(temp_std) else 0.0, 1.0)
                )

            humidity_mean = crop.get("humidity_mean", np.nan)
            humidity_std = crop.get("humidity_std", np.nan)
            if pd.notna(location["humidity_14d"]) and pd.notna(humidity_mean):
                z_scores.append(
                    (location["humidity_14d"] - humidity_mean) /
                    max(float(humidity_std) if pd.notna(humidity_std) else 0.0, 5.0)
                )

            score = float(100 * np.exp(-0.5 * np.mean(np.square(z_scores)))) if z_scores else np.nan
            temp_q90 = crop.get("temperature_q90", np.nan)
            rows.append({
                "location_id": location["location_id"],
                "crop": crop["crop"],
                "temp_gap_c": location["temp_mean_14d"] - temp_mean,
                "heat_excess_c": max(0.0, location["temp_max_14d"] - temp_q90)
                    if pd.notna(location["temp_max_14d"]) and pd.notna(temp_q90) else np.nan,
                "fit_score": score,
                "fit_inputs_available": len(z_scores),
                "fit_method": "temperature_and_humidity" if len(z_scores) == 2
                    else ("temperature_only" if len(z_scores) == 1 else "insufficient_data"),
                "rain_90d_mm": location["rain_90d_mm"],
            })

    fit = pd.DataFrame(rows)
    fit["fit_score"] = fit["fit_score"].round(1)
    fit = fit.sort_values(["location_id", "fit_score"], ascending=[True, False])
    fit.to_csv(PROC / "fit_scores.csv", index=False)
    print("Top 3 climate-fit crops per location:")
    print(fit.groupby("location_id").head(3).to_string(index=False))
    return fit


def main():
    profile = build_crop_profile()
    clean_247k()
    clean_optional_reference_files()
    current = build_climate_tables()
    build_fit_scores(current, profile)


if __name__ == "__main__":
    main()
