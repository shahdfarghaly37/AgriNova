"""Step 07: crop knowledge for the five yield-model crops + extended profiles.

Outputs (data/processed):
- crop_knowledge.csv          literature-indicative agronomic parameters
- crop_traits.csv             UPDATED: heat_tolerance_class, soil_demand_index filled
- crops_profile_extended.csv  22 Crop Recommendation crops + wheat + soybean

IMPORTANT
- Values in KNOWLEDGE are indicative figures from FAO and crop-science
  literature. They are NOT measured for Egyptian cultivars. Every row carries
  knowledge_status so the team can verify before the final presentation.
- Wheat/soybean profiles from the yield dataset (synthetic/unverified) fill
  ONLY temperature, humidity and pH. N, P, K and rainfall stay empty because
  their definitions/units differ from Crop Recommendation.
"""
import numpy as np
import pandas as pd
from config import PROC

STATUS = "literature_indicative_verify_before_final"

# gdd_base_c: base temperature for Growing Degree Days.
# gdd_to_maturity: indicative accumulated GDD from planting to maturity.
# temp_*: mean daily air temperature thresholds (abs_min, opt_min, opt_max, abs_max).
# heat_tmax_c: daily maximum above which heat damage risk is counted.
# nutrient_demand: 1 low, 2 medium, 3 high (qualitative, literature based).
# plant_months: typical Egyptian planting months (calendar reference only).
KNOWLEDGE = [
    dict(crop_type="wheat", gdd_base_c=0, gdd_to_maturity=2000, temp_abs_min=3, temp_opt_min=12,
         temp_opt_max=22, temp_abs_max=32, heat_tmax_c=30, nutrient_demand=2, nitrogen_fixing=False,
         ph_opt_min=6.0, ph_opt_max=7.5, plant_months="11,12",
         note="Heat threshold refers to anthesis/grain filling (about 30 C)."),
    dict(crop_type="maize", gdd_base_c=10, gdd_to_maturity=1600, temp_abs_min=10, temp_opt_min=18,
         temp_opt_max=27, temp_abs_max=35, heat_tmax_c=35, nutrient_demand=3, nitrogen_fixing=False,
         ph_opt_min=5.8, ph_opt_max=7.0, plant_months="3,4,5,6,7",
         note="Spring and summer plantings both exist in Egypt."),
    dict(crop_type="rice", gdd_base_c=10, gdd_to_maturity=2000, temp_abs_min=15, temp_opt_min=22,
         temp_opt_max=30, temp_abs_max=37, heat_tmax_c=35, nutrient_demand=2, nitrogen_fixing=False,
         ph_opt_min=5.5, ph_opt_max=7.0, plant_months="5,6",
         note="Rice area in Egypt is regulated by water policy; not modeled here."),
    dict(crop_type="cotton", gdd_base_c=15.5, gdd_to_maturity=1400, temp_abs_min=15, temp_opt_min=21,
         temp_opt_max=30, temp_abs_max=38, heat_tmax_c=36, nutrient_demand=3, nitrogen_fixing=False,
         ph_opt_min=6.0, ph_opt_max=8.0, plant_months="3,4",
         note="Boll retention drops under sustained very high daytime heat."),
    dict(crop_type="soybean", gdd_base_c=10, gdd_to_maturity=2000, temp_abs_min=10, temp_opt_min=20,
         temp_opt_max=30, temp_abs_max=37, heat_tmax_c=35, nutrient_demand=1, nitrogen_fixing=True,
         ph_opt_min=6.0, ph_opt_max=7.0, plant_months="5,6",
         note="Legume: fixes nitrogen, so low fertilizer demand and a rotation benefit."),
]


def heat_class(tmax):
    if tmax <= 32:
        return "sensitive"
    if tmax <= 36:
        return "moderate"
    return "tolerant"


def main():
    know = pd.DataFrame(KNOWLEDGE)
    know["heat_tolerance_class"] = know["heat_tmax_c"].map(heat_class)
    know["knowledge_status"] = STATUS
    know["source"] = ("FAO Irrigation and Drainage Paper 56 and 24; FAO EcoCrop; "
                      "general crop-physiology literature (indicative values)")
    know.to_csv(PROC / "crop_knowledge.csv", index=False)

    traits = pd.read_csv(PROC / "crop_traits.csv")
    mapper = know.set_index("crop_type")
    traits["heat_tolerance_class"] = traits["crop_type"].map(mapper["heat_tolerance_class"])
    traits["soil_demand_index"] = traits["crop_type"].map(mapper["nutrient_demand"])
    traits["traits_notes"] = (
        "FAO water/maturity ranges are indicative. Heat class derived from the heat_tmax_c "
        "threshold (<=32 sensitive, <=36 moderate, else tolerant). soil_demand_index is a "
        "qualitative 1-3 nutrient-demand level from literature, not a measurement."
    )
    traits.to_csv(PROC / "crop_traits.csv", index=False)

    # Extended profile.
    profile = pd.read_csv(PROC / "crops_profile.csv")
    profile["profile_source"] = "crop_recommendation_dataset"
    agri = pd.read_csv(PROC / "agri_247k_clean.csv")
    rows = []
    for crop in ["wheat", "soybean"]:
        sub = agri[agri["crop_type"] == crop]
        top = sub[sub["crop_yield_tons"] >= sub["crop_yield_tons"].quantile(0.75)]
        row = {"crop": crop, "profile_source": "yield_dataset_top_yield_quartile_synthetic"}
        for src, name in [("avg_temp_c", "temperature"), ("humidity_pct", "humidity"), ("soil_ph", "ph")]:
            s = top[src].dropna()
            row[f"{name}_mean"] = s.mean()
            row[f"{name}_std"] = s.std()
            row[f"{name}_q10"] = s.quantile(0.10)
            row[f"{name}_q90"] = s.quantile(0.90)
        rows.append(row)
    ext = pd.concat([profile, pd.DataFrame(rows)], ignore_index=True)
    ext.to_csv(PROC / "crops_profile_extended.csv", index=False)

    print(know[["crop_type", "gdd_base_c", "gdd_to_maturity", "heat_tmax_c", "heat_tolerance_class",
                "nutrient_demand"]].to_string(index=False))
    print(ext[ext["profile_source"].str.contains("yield")][
        ["crop", "temperature_mean", "temperature_q10", "temperature_q90", "humidity_mean", "ph_mean"]
    ].round(2).to_string(index=False))
    print("Saved crop_knowledge.csv, crop_traits.csv (updated), crops_profile_extended.csv")


if __name__ == "__main__":
    main()
