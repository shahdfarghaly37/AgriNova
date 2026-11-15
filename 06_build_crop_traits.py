"""Build a documented crop-traits reference for the five yield-model crops.

Run from the project root:
    python 06_build_crop_traits.py

This script does not modify raw data or train a model.
"""
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
PROCESSED.mkdir(parents=True, exist_ok=True)

YIELD_FILE = RAW / "crop_yield_data.csv"
RECOMMENDATION_FILE = RAW / "crop_recommendation.csv"

# Canonical names used across the project. Keep original labels in the mapping file.
ALIASES = {
    "corn": "maize",
    "maize": "maize",
    "cotton": "cotton",
    "rice": "rice",
    "soybean": "soybean",
    "wheat": "wheat",
}

# FAO indicative ranges. These are broad agronomic references, not Egypt-specific
# cultivar guarantees. Seasonal water need is crop evapotranspiration over the
# full growing period, not rainfall_mm and not irrigation_mm.
FAO_TRAITS = {
    "maize": {
        "family": "Poaceae",
        "water_need_min_mm_season": 500,
        "water_need_max_mm_season": 800,
        "maturity_min_days": 125,
        "maturity_max_days": 180,
        "fao_crop_group": "Maize, grain",
    },
    "cotton": {
        "family": "Malvaceae",
        "water_need_min_mm_season": 700,
        "water_need_max_mm_season": 1300,
        "maturity_min_days": 180,
        "maturity_max_days": 195,
        "fao_crop_group": "Cotton",
    },
    "rice": {
        "family": "Poaceae",
        "water_need_min_mm_season": 450,
        "water_need_max_mm_season": 700,
        "maturity_min_days": 90,
        "maturity_max_days": 150,
        "fao_crop_group": "Rice",
    },
    "soybean": {
        "family": "Fabaceae",
        "water_need_min_mm_season": 450,
        "water_need_max_mm_season": 700,
        "maturity_min_days": 135,
        "maturity_max_days": 150,
        "fao_crop_group": "Soybean",
    },
    "wheat": {
        "family": "Poaceae",
        "water_need_min_mm_season": 450,
        "water_need_max_mm_season": 650,
        "maturity_min_days": 120,
        "maturity_max_days": 150,
        "fao_crop_group": "Barley/Oats/Wheat",
    },
}

FAO_WATER_URL = "https://www.fao.org/4/s2022e/s2022e02.htm"
FAO_GROWTH_URL = "https://www.fao.org/4/s2022e/s2022e07.htm"
CROP_REC_SOURCE = "Kaggle Crop Recommendation dataset, local raw file crop_recommendation.csv"


def normalize(value: object) -> str:
    return str(value).strip().lower().replace(" ", "_")


def main() -> None:
    for path in (YIELD_FILE, RECOMMENDATION_FILE):
        if not path.exists():
            raise FileNotFoundError(f"Required input not found: {path}")

    yield_df = pd.read_csv(YIELD_FILE, low_memory=False)
    rec_df = pd.read_csv(RECOMMENDATION_FILE, low_memory=False)

    required_yield = {"crop_type"}
    required_rec = {"label", "N", "P", "K", "temperature", "humidity", "ph", "rainfall"}
    if not required_yield.issubset(yield_df.columns):
        raise ValueError(f"Yield data must contain: {sorted(required_yield)}")
    if not required_rec.issubset(rec_df.columns):
        raise ValueError(f"Crop recommendation data missing: {sorted(required_rec - set(rec_df.columns))}")

    yield_labels = sorted(yield_df["crop_type"].dropna().map(normalize).unique())
    canonical_yield = sorted({ALIASES.get(label, label) for label in yield_labels})
    expected = sorted(FAO_TRAITS)
    if canonical_yield != expected:
        raise ValueError(
            "Unexpected yield crop set. "
            f"Expected {expected}, found {canonical_yield}. Review ALIASES before proceeding."
        )

    # Create an explicit audit trail for every original yield label.
    mapping_rows = []
    for original in yield_labels:
        canonical = ALIASES.get(original, original)
        mapping_rows.append({
            "source_dataset": "crop_yield_data.csv",
            "original_crop_label": original,
            "canonical_crop_type": canonical,
            "mapping_rule": "alias" if original != canonical else "identity",
        })
    mapping = pd.DataFrame(mapping_rows)
    mapping.to_csv(PROCESSED / "crop_name_mapping.csv", index=False)

    rec = rec_df.copy()
    rec["canonical_crop_type"] = rec["label"].map(normalize).replace(ALIASES)
    rows = []
    for crop, traits in FAO_TRAITS.items():
        group = rec.loc[rec["canonical_crop_type"] == crop]
        row = {
            "crop_type": crop,
            "crop_family": traits["family"],
            "water_need_min_mm_season": traits["water_need_min_mm_season"],
            "water_need_max_mm_season": traits["water_need_max_mm_season"],
            "maturity_min_days": traits["maturity_min_days"],
            "maturity_max_days": traits["maturity_max_days"],
            "fao_crop_group": traits["fao_crop_group"],
            "crop_recommendation_rows": int(len(group)),
            "crop_recommendation_profile_available": bool(len(group)),
            "heat_tolerance_class": pd.NA,
            "soil_demand_index": pd.NA,
            "traits_notes": (
                "FAO values are indicative ranges; cultivar and local conditions change them. "
                "Heat tolerance and soil-demand index are intentionally not assigned without a defensible source."
            ),
            "water_maturity_source": "FAO Irrigation and Drainage Paper 24, indicative crop tables",
            "water_source_url": FAO_WATER_URL,
            "maturity_source_url": FAO_GROWTH_URL,
        }
        # These are observed quantiles from the recommendation dataset, not physiological limits.
        for col in ["N", "P", "K", "temperature", "humidity", "ph", "rainfall"]:
            if len(group):
                row[f"rec_{col.lower()}_q10"] = float(group[col].quantile(0.10))
                row[f"rec_{col.lower()}_median"] = float(group[col].median())
                row[f"rec_{col.lower()}_q90"] = float(group[col].quantile(0.90))
            else:
                row[f"rec_{col.lower()}_q10"] = pd.NA
                row[f"rec_{col.lower()}_median"] = pd.NA
                row[f"rec_{col.lower()}_q90"] = pd.NA
        row["crop_recommendation_source"] = CROP_REC_SOURCE if len(group) else pd.NA
        row["crop_recommendation_interpretation"] = (
            "Observed dataset distribution only, not a verified ideal agronomic range."
            if len(group) else
            "No matching crop in crop_recommendation.csv; do not impute from another crop."
        )
        rows.append(row)

    traits_df = pd.DataFrame(rows)
    traits_df.to_csv(PROCESSED / "crop_traits.csv", index=False)

    report = {
        "status": "success",
        "yield_rows_checked": int(len(yield_df)),
        "original_yield_crop_labels": yield_labels,
        "canonical_crop_types": canonical_yield,
        "crop_traits_rows": int(len(traits_df)),
        "crop_recommendation_matches": {
            row["crop_type"]: int(row["crop_recommendation_rows"])
            for row in rows
        },
        "important_limitations": [
            "FAO water need is seasonal crop evapotranspiration, not rainfall or irrigation volume.",
            "FAO maturity ranges are indicative and not cultivar-specific or Egypt-specific guarantees.",
            "Crop recommendation quantiles are observed dataset distributions, not certified ideal limits.",
            "Heat tolerance class and soil demand index are left blank rather than invented.",
            "No yield dataset rows are changed by this script.",
        ],
        "sources": [FAO_WATER_URL, FAO_GROWTH_URL],
    }
    (PROCESSED / "crop_traits_build_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("Crop traits created:", PROCESSED / "crop_traits.csv")
    print("Crop mapping created:", PROCESSED / "crop_name_mapping.csv")
    print("Build report created:", PROCESSED / "crop_traits_build_report.json")
    print("\nCrop recommendation profile coverage:")
    print(traits_df[["crop_type", "crop_recommendation_rows", "crop_family",
                     "water_need_min_mm_season", "water_need_max_mm_season",
                     "maturity_min_days", "maturity_max_days"]].to_string(index=False))
    print("\nNote: heat_tolerance_class and soil_demand_index remain blank intentionally.")


if __name__ == "__main__":
    main()
