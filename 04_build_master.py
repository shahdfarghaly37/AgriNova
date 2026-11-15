"""Build final app-facing and analysis-facing master tables."""
import numpy as np
import pandas as pd
from config import PROC, MASTER, BASELINE_YEARS, HEAT_DAY_C, GDD_BASE_C


def normalize_crop_name(value):
    """Normalize known spelling/synonym differences across source datasets."""
    if pd.isna(value):
        return pd.NA
    key = str(value).strip().lower().replace("_", " ").replace("-", " ")
    key = " ".join(key.split())
    aliases = {
        "corn": "maize",
        "maize": "maize",
        "soy beans": "soybean",
        "soybean": "soybean",
        "rice paddy": "rice",
        "paddy rice": "rice",
    }
    return aliases.get(key, key)


def weather_monthly():
    path = PROC / "weather_daily.csv"
    if not path.exists():
        raise FileNotFoundError("Run 01_fetch_weather.py first.")
    weather = pd.read_csv(path, parse_dates=["date"])
    weather["year"] = weather["date"].dt.year
    weather["month"] = weather["date"].dt.month
    weather["heat_day"] = (weather["temp_max"] > HEAT_DAY_C).astype("int8")
    # Generic GDD base 10°C. This is a prototype proxy, not crop-specific phenology.
    weather["gdd"] = (weather["temp_mean"] - GDD_BASE_C).clip(lower=0)

    monthly = (
        weather.groupby(["location_id", "year", "month"])
        .agg(
            temp_mean=("temp_mean", "mean"),
            temp_max=("temp_max", "mean"),
            temp_min=("temp_min", "mean"),
            precip_mm=("precip_mm", "sum"),
            humidity_pct=("humidity_pct", "mean"),
            solar_kwh_m2=("solar_kwh_m2", "mean"),
            heat_days=("heat_day", "sum"),
            gdd=("gdd", "sum"),
            n_days=("date", "count"),
        )
        .reset_index()
    )
    baseline = (
        monthly[monthly["year"].between(*BASELINE_YEARS)]
        .groupby(["location_id", "month"])["temp_mean"]
        .mean().rename("baseline_temp").reset_index()
    )
    monthly = monthly.merge(baseline, on=["location_id", "month"], how="left")
    monthly["temp_anomaly_c"] = monthly["temp_mean"] - monthly["baseline_temp"]
    numeric_cols = monthly.select_dtypes(include=["number"]).columns
    monthly[numeric_cols] = monthly[numeric_cols].round(3)
    monthly.to_csv(MASTER / "master_weather_monthly.csv", index=False)
    return monthly


def training_master(profile):
    source = pd.read_csv(PROC / "agri_247k_clean.csv")
    crop_profile = profile.copy()
    crop_profile["crop_key"] = crop_profile["crop"].map(normalize_crop_name)

    keep = [
        "crop_key", "temperature_mean", "temperature_std",
        "temperature_q10", "temperature_q90", "humidity_mean",
        "humidity_q10", "humidity_q90", "ph_mean", "rainfall_mean",
        "n_mean", "p_mean", "k_mean",
    ]
    crop_profile = crop_profile[[c for c in keep if c in crop_profile.columns]].copy()
    rename = {
        "temperature_mean": "ideal_temp_mean",
        "temperature_std": "ideal_temp_std",
        "temperature_q10": "ideal_temp_q10",
        "temperature_q90": "ideal_temp_q90",
        "humidity_mean": "ideal_humidity_mean",
        "humidity_q10": "ideal_humidity_q10",
        "humidity_q90": "ideal_humidity_q90",
        "ph_mean": "ideal_ph_mean",
        "rainfall_mean": "ideal_rainfall_mean",
        "n_mean": "ideal_n_mean",
        "p_mean": "ideal_p_mean",
        "k_mean": "ideal_k_mean",
    }
    crop_profile = crop_profile.rename(columns=rename)

    if "crop_type" not in source:
        raise ValueError("crop_type missing from cleaned 247K dataset.")
    source["crop_key"] = source["crop_type"].map(normalize_crop_name)
    matched = source["crop_key"].isin(crop_profile["crop_key"])
    print(f"Rows with a crop-knowledge name match: {matched.mean():.1%}")
    unmatched = sorted(source.loc[~matched, "crop_key"].dropna().unique().tolist())
    print("Unmatched yield crop labels (no Crop Recommendation profile):", unmatched)
    print("Matched crop labels:", sorted(source.loc[matched, "crop_key"].dropna().unique().tolist()))
    master = source.merge(crop_profile, on="crop_key", how="left", validate="many_to_one")

    if {"avg_temp_c", "ideal_temp_mean"}.issubset(master.columns):
        master["temp_gap_c"] = master["avg_temp_c"] - master["ideal_temp_mean"]
        master["heat_excess_c"] = (
            master["avg_temp_c"] - master["ideal_temp_q90"]
        ).clip(lower=0)
        master["in_ideal_temp_range"] = master["avg_temp_c"].between(
            master["ideal_temp_q10"], master["ideal_temp_q90"]
        ).where(master["ideal_temp_mean"].notna())
    if {"humidity_pct", "ideal_humidity_mean"}.issubset(master.columns):
        master["humidity_gap"] = master["humidity_pct"] - master["ideal_humidity_mean"]
    if {"soil_ph", "ideal_ph_mean"}.issubset(master.columns):
        master["ph_gap"] = master["soil_ph"] - master["ideal_ph_mean"]

    out = master.drop(columns="crop_key")
    num_cols = out.select_dtypes(include=["number"]).columns
    out[num_cols] = out[num_cols].round(4)  # numeric only: avoids the datetime/bool round warning
    out.to_csv(MASTER / "master_training.csv", index=False)
    return master


def location_crop(profile):
    current = pd.read_csv(PROC / "current_climate.csv")
    fit = pd.read_csv(PROC / "fit_scores.csv")
    drift = pd.read_csv(PROC / "climate_drift.csv")

    current["as_of"] = pd.to_datetime(current["as_of"])
    month = int(current["as_of"].dt.month.mode().iloc[0])
    month_drift = (
        drift[drift["month"] == month][["location_id", "delta_c"]]
        .rename(columns={"delta_c": "drift_c_this_month"})
    )

    # rain_90d_mm is present in both fit_scores and current_climate; keep the
    # current-climate value as the authoritative location-level field.
    fit_for_merge = fit.drop(columns=["rain_90d_mm"], errors="ignore")
    result = (
        fit_for_merge.merge(current, on="location_id", how="left", validate="many_to_one")
        .merge(month_drift, on="location_id", how="left", validate="many_to_one")
        .merge(profile, on="crop", how="left", validate="many_to_one")
    )
    result["rank_in_location"] = (
        result.groupby("location_id")["fit_score"]
        .rank(method="dense", ascending=False)
    )
    result["action"] = np.select(
        [result["fit_score"] >= 70, result["fit_score"] >= 40],
        ["favorable_climate_fit", "monitor_conditions"],
        default="low_climate_fit",
    )
    result["action_note"] = (
        "Prototype climate-fit indicator only. Not a planting instruction; "
        "soil, water availability, season, pests and local agronomist advice are not fully modeled."
    )
    # Yield is intentionally not merged here. The synthetic yield model has no
    # defensible location-level input mapping from the current climate table.
    result["pred_yield_tons"] = np.nan
    result["yield_prediction_status"] = "not_available_for_location_scenario"
    numeric_cols = result.select_dtypes(include=["number"]).columns
    result[numeric_cols] = result[numeric_cols].round(3)
    result.to_csv(MASTER / "master_location_crop.csv", index=False)
    return result


def data_dictionary():
    rows = []
    for path in sorted(MASTER.glob("master_*.csv")):
        frame = pd.read_csv(path)
        for column in frame.columns:
            series = frame[column]
            numeric = pd.api.types.is_numeric_dtype(series)
            rows.append({
                "file": path.name,
                "column": column,
                "dtype": str(series.dtype),
                "n_rows": len(frame),
                "missing_pct": round(float(series.isna().mean() * 100), 2),
                "min": series.min() if numeric and series.notna().any() else "",
                "max": series.max() if numeric and series.notna().any() else "",
                "example": series.dropna().iloc[0] if series.notna().any() else "",
            })
    pd.DataFrame(rows).to_csv(MASTER / "data_dictionary.csv", index=False)


def main():
    # Prefer the extended profile (adds wheat and soybean, built by 07_build_crop_knowledge.py).
    profile_path = PROC / "crops_profile_extended.csv"
    if not profile_path.exists():
        profile_path = PROC / "crops_profile.csv"
    if not profile_path.exists():
        raise FileNotFoundError("Run 02_clean_and_merge.py first.")
    print(f"Using crop profile: {profile_path.name}")
    profile = pd.read_csv(profile_path)
    weather_monthly()
    training_master(profile)
    location_crop(profile)
    data_dictionary()
    print(f"Master outputs saved in: {MASTER}")


if __name__ == "__main__":
    main()
