"""Farmer Imposters engine: algorithms + My Farm (Check / Suggest / Compare).

Pipeline position: runs after 02, 04, 06, 07 and 03 (trained model).

What is REAL and what is NOT
- Climate: real NASA POWER daily data, recent-years climatology per governorate.
- Crop parameters: indicative FAO/literature values (crop_knowledge.csv).
- Yield: EXPERIMENTAL index from a model trained on a synthetic/unverified
  dataset. Only avg_temp_c is taken from NASA; the other climate-like inputs stay
  at dataset medians because their definitions differ. Never present it as a
  validated yield forecast for Egyptian farms.
- Soil impact: a rotation/nutrient PROXY, not a measurement of soil degradation.
- GPS: snaps to the nearest of 10 reference governorates, not farm-level climate.

CLI examples (PowerShell):
  python 09_engine.py --mode suggest --lat 30.8 --lon 31.0 --soil clay --ph 7.8 --water medium --irrigation flood --goal balanced
  python 09_engine.py --mode check --crop wheat --lat 27.2 --lon 31.2
  python 09_engine.py --mode compare --crops wheat,maize,rice --lat 31.2 --lon 29.9
  python 09_engine.py --build-final
"""
import argparse
import json
import math
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

import joblib
import numpy as np
import pandas as pd

from config import LOCATIONS, PROC, RECENT_YEARS, END_DATE

FINAL = PROC.parent / "final"
FINAL.mkdir(parents=True, exist_ok=True)

RECENT_START_YEAR = END_DATE.year - RECENT_YEARS + 1
# CORE_CROPS = the crops the yield model was trained on (synthetic data, experimental yield index).
# FULL_CROPS = every crop with a full row in crop_knowledge.csv and crop_traits.csv. The crops in
# FULL_CROPS but not in CORE_CROPS get the full climate/heat/water/pH/soil/season analysis, but NO
# yield estimate (there is no yield model for them).
CORE_CROPS = ["wheat", "maize", "rice", "cotton", "soybean"]
YIELD_CROPS = CORE_CROPS
FULL_CROPS = CORE_CROPS + ["potato", "sorghum"]
# Crops evaluated by default (when no list is given). Switch to FULL_CROPS once egypt.py and api.py
# know the new crops (names in Arabic, and rows without a yield score).
ACTIVE_CROPS = CORE_CROPS
# FAO yield item name (fao_yield_clean.csv, area Egypt) -> our crop name. Real data, 1961-2016.
FAO_ITEM_TO_CROP = {"Maize": "maize", "Rice, paddy": "rice", "Wheat": "wheat", "Soybeans": "soybean",
                    "Potatoes": "potato", "Sorghum": "sorghum"}
ALIASES = {"corn": "maize", "soy": "soybean", "soybeans": "soybean"}
# Trees and other perennials: a 120-day window from the planting date makes no sense for them,
# so they are judged on the whole year's climate instead.
PERENNIAL_CROPS = {"apple", "banana", "coconut", "coffee", "grapes", "mango", "orange",
                   "papaya", "pomegranate"}

# ---- Assumptions (edit here, they are documented in the final README) -------
# Seasonal water the farmer can supply per crop season (mm, gross at the field).
# Assumption: Egyptian Nile allotments are roughly 4000-5000 m3/feddan/year (about 950-1190 mm).
WATER_CAPACITY_MM = {"low": 500, "medium": 1000, "high": 1500}
# Typical application efficiencies (FAO guidance): surface/flood, sprinkler, drip.
IRRIGATION_EFFICIENCY = {"flood": 0.60, "sprinkler": 0.75, "drip": 0.90}
EFFECTIVE_RAIN_FRACTION = 0.8
GOAL_WEIGHTS = {
    #               climate heat  water soil_fit soil_impact yield season
    "balanced":     (0.30, 0.15, 0.15, 0.10, 0.10, 0.10, 0.10),
    "max_yield":    (0.25, 0.15, 0.05, 0.10, 0.00, 0.35, 0.10),
    "save_water":   (0.20, 0.10, 0.40, 0.05, 0.05, 0.05, 0.15),
    "protect_soil": (0.20, 0.10, 0.10, 0.10, 0.35, 0.05, 0.10),
}
COMPONENTS = ["temp_fit", "heat_score", "water_score", "soil_fit", "soil_impact_score",
              "yield_score", "season_fit"]
FAMILY = {"wheat": "Poaceae", "maize": "Poaceae", "rice": "Poaceae",
          "cotton": "Malvaceae", "soybean": "Fabaceae",
          "potato": "Solanaceae", "sorghum": "Poaceae"}
MAX_SNAP_KM = 150


# ---- Helpers -----------------------------------------------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_location(lat, lon):
    best = min(LOCATIONS, key=lambda k: haversine_km(lat, lon, *LOCATIONS[k]))
    return best, haversine_km(lat, lon, *LOCATIONS[best])


def norm_crop(name):
    key = str(name).strip().lower().replace(" ", "")
    return ALIASES.get(key, key)


def trapezoid(t, amin, omin, omax, amax):
    t = np.asarray(t, dtype=float)
    up = np.clip((t - amin) / max(omin - amin, 1e-6), 0, 1)
    down = np.clip((amax - t) / max(amax - omax, 1e-6), 0, 1)
    return 100.0 * np.minimum(up, down)


def season_of(month):
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer"}.get(month, "autumn")


def label_for(score):
    if score >= 70:
        return "Recommended"
    if score >= 50:
        return "Possible with caution"
    return "Not recommended"


# ---- Farm profile ------------------------------------------------------------
@dataclass
class Farm:
    lat: float
    lon: float
    soil_type: str = "loam"            # loam, sandy, clay, silt, peat
    soil_ph: float | None = None
    water_availability: str = "medium"  # low, medium, high
    irrigation_method: str = "sprinkler"  # flood, sprinkler, drip
    previous_crops: list = field(default_factory=list)  # most recent first
    goal: str = "balanced"             # balanced, max_yield, save_water, protect_soil
    planting_date: date = field(default_factory=date.today)
    fertilized: str = "yes"

    def validate(self):
        assert self.goal in GOAL_WEIGHTS, f"goal must be one of {list(GOAL_WEIGHTS)}"
        assert self.water_availability in WATER_CAPACITY_MM
        assert self.irrigation_method in IRRIGATION_EFFICIENCY
        assert 21 <= self.lat <= 32 and 24 <= self.lon <= 37, "Coordinates look outside Egypt."
        return self


# ---- Data loading (cached) ---------------------------------------------------
class Data:
    _inst = None

    @classmethod
    def get(cls):
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    def __init__(self):
        w = pd.read_csv(PROC / "weather_daily.csv", parse_dates=["date"])
        w = w[w["date"].dt.year >= RECENT_START_YEAR].copy()
        w["doy"] = w["date"].dt.dayofyear.clip(upper=365)
        w["year"] = w["date"].dt.year
        self.clim = {}
        for loc, g in w.groupby("location_id"):
            by = g.groupby("doy")
            tm = by["temp_mean"].mean().reindex(range(1, 366)).interpolate().to_numpy()
            tx = by["temp_max"].mean().reindex(range(1, 366)).interpolate().to_numpy()
            pr = by["precip_mm"].mean().reindex(range(1, 366)).fillna(0).to_numpy()
            hu = by["humidity_pct"].mean().reindex(range(1, 366)).interpolate().to_numpy()
            tmax_mat = g.pivot_table(index="doy", columns="year", values="temp_max").reindex(range(1, 366))
            self.clim[loc] = dict(temp_mean=_smooth(tm), temp_max=_smooth(tx), precip=pr,
                                  humidity=_smooth(hu), tmax_mat=tmax_mat.interpolate(limit_direction="both"),
                                  last_date=g["date"].max())
        know = pd.read_csv(PROC / "crop_knowledge.csv").set_index("crop_type")
        traits = pd.read_csv(PROC / "crop_traits.csv").set_index("crop_type")
        self.know, self.traits = know, traits
        self.profile = pd.read_csv(PROC / "crops_profile_extended.csv").set_index("crop")
        med_path = PROC / "crop_median_yield.json"
        if med_path.exists():
            self.crop_median_yield = json.loads(med_path.read_text(encoding="utf-8"))
        else:
            agri = pd.read_csv(PROC / "agri_247k_clean.csv", usecols=["crop_type", "crop_yield_tons"])
            self.crop_median_yield = agri.groupby("crop_type")["crop_yield_tons"].median().to_dict()
            med_path.write_text(json.dumps(self.crop_median_yield), encoding="utf-8")
        self.model = joblib.load(PROC / "yield_model.joblib")
        self.meta = json.loads((PROC / "metrics.json").read_text(encoding="utf-8"))
        self.extended = [c for c in self.profile.index if c not in FULL_CROPS]
        # Real FAO yields for Egypt (hg/ha -> t/ha), mean of the last 5 years available.
        self.fao_egypt = {}
        fao_path = PROC / "fao_yield_clean.csv"
        if fao_path.exists():
            fao = pd.read_csv(fao_path, usecols=["area", "item", "year", "value"])
            fao = fao[fao["area"] == "Egypt"]
            for item, crop in FAO_ITEM_TO_CROP.items():
                g = fao[fao["item"] == item].sort_values("year").tail(5)
                if len(g):
                    self.fao_egypt[crop] = dict(t_ha=float(g["value"].mean()) / 10000.0,
                                                years=f"{int(g['year'].min())}-{int(g['year'].max())}")


def _smooth(a, k=7):
    ext = np.concatenate([a[-k:], a, a[:k]])
    return np.convolve(ext, np.ones(k) / k, mode="same")[k:-k]


def _window_idx(start, days):
    doy0 = min(start.timetuple().tm_yday, 365)
    return (np.arange(days) + doy0 - 1) % 365  # zero-based doy indices


# ---- Algorithms --------------------------------------------------------------
def gdd_harvest(clim, start, base, target, max_days=420):
    idx = _window_idx(start, max_days)
    daily = np.clip(clim["temp_mean"][idx] - base, 0, None)
    cum = np.cumsum(daily)
    hit = np.argmax(cum >= target) if (cum >= target).any() else None
    if hit is None:
        return None, None, float(cum[-1])
    return start + timedelta(days=int(hit) + 1), int(hit) + 1, float(cum[hit])


def _window_stats(loc, crop_row, start, days):
    clim = Data.get().clim[loc]
    idx = _window_idx(start, days)
    temp = clim["temp_mean"][idx]
    out = dict(window_days=days, window_temp_mean=float(temp.mean()),
               window_rain_mm=float(clim["precip"][idx].sum()),
               window_humidity=float(clim["humidity"][idx].mean()))
    return out, temp, idx


_REF = {}


def _heat_raw(clim, idx, k, days):
    heat_prob = (clim["tmax_mat"].to_numpy()[idx, :] > k["heat_tmax_c"]).mean(axis=1)
    a, b = int(0.4 * days), max(int(0.8 * days), int(0.4 * days) + 1)
    return float(heat_prob[a:b].mean())


def _ref_heat(loc, k, days):
    """Heat share this crop normally faces at this location (average over its usual planting months)."""
    key = (loc, k.name, days)
    if key not in _REF:
        clim = Data.get().clim[loc]
        ms = [int(m) for m in str(k["plant_months"]).split(",")]
        _REF[key] = float(np.mean([_heat_raw(clim, _window_idx(date(2001, m, 15), days), k, days) for m in ms]))
    return _REF[key]


def climate_and_heat(loc, k, start, days):
    """Temperature fit and heat-stress share for one crop and planting date."""
    clim = Data.get().clim[loc]
    stats, temp, idx = _window_stats(loc, k, start, days)
    fit = trapezoid(temp, k["temp_abs_min"], k["temp_opt_min"], k["temp_opt_max"], k["temp_abs_max"])
    # Heat damage matters mostly at flowering / grain or boll filling, so the heat
    # share is counted over the sensitive stage: 40% to 80% of the season.
    raw = _heat_raw(clim, idx, k, days)
    ref = _ref_heat(loc, k, days)
    # NASA grid Tmax runs warmer than farm stations, so the raw share is high everywhere (even in
    # a crop's normal season). The score uses the EXTRA hot days compared with this crop's usual
    # planting months at this location.
    stats.update(temp_fit=float(fit.mean()), heat_day_share=raw, heat_normal_share=ref,
                 heat_excess_share=max(0.0, raw - ref))
    return stats


def best_climate_start(loc, k, days, from_date):
    """Best start within +-1 month of the usual Egyptian planting months.

    This answers "should I shift the calendar date?" without suggesting
    agronomically meaningless seasons (e.g. maize planted in November).
    """
    months = [int(m) for m in str(k["plant_months"]).split(",")]
    best, first = None, None
    for off in range(0, 365, 5):
        d = from_date + timedelta(days=off)
        if min(min((d.month - pm) % 12, (pm - d.month) % 12) for pm in months) > 1:
            continue
        if first is None:
            first = d
        if (d - first).days > 75:  # stay inside the first upcoming season
            break
        s = climate_and_heat(loc, k, d, days)
        val = 0.6 * s["temp_fit"] + 0.4 * 100 * (1 - min(1, s["heat_excess_share"] / 0.25))
        if best is None or val > best[0]:
            best = (val, d)
    return best[1] if best else from_date


def water_metrics(k_tr, farm, rain_mm):
    need = (k_tr["water_need_min_mm_season"] + k_tr["water_need_max_mm_season"]) / 2
    net = max(0.0, need - EFFECTIVE_RAIN_FRACTION * rain_mm)
    gross = net / IRRIGATION_EFFICIENCY[farm.irrigation_method]
    cap = WATER_CAPACITY_MM[farm.water_availability]
    ratio = gross / cap
    score = float(np.clip(100 * (1.5 - ratio), 0, 100)) if ratio > 0.5 else 100.0
    cls = "low" if gross < 600 else ("medium" if gross < 1000 else "high")
    return dict(crop_water_need_mm=need, net_irrigation_mm=net, gross_irrigation_mm=gross,
                water_capacity_mm=cap, water_demand_class=cls, water_feasible=bool(ratio <= 1.0),
                water_score=score)


# Indicative suitability (0-100) of each soil type for each crop. General agronomic knowledge,
# not a measurement: rice likes heavy soil that holds water, the others prefer well-drained loam/silt.
SOIL_TYPE_FIT = {
    "wheat":   {"loam": 95, "silt": 90, "clay": 85, "sandy": 55, "peat": 50},
    "maize":   {"loam": 95, "silt": 90, "clay": 75, "sandy": 60, "peat": 70},
    "rice":    {"clay": 95, "silt": 85, "loam": 75, "peat": 65, "sandy": 40},
    "cotton":  {"loam": 90, "silt": 85, "clay": 80, "sandy": 65, "peat": 45},
    "soybean": {"loam": 95, "silt": 90, "clay": 75, "sandy": 60, "peat": 60},
}


def soil_fit_score(k, soil_ph, soil_type=None, crop=None):
    """0-100 soil match = 50% pH fit + 50% soil-type fit (indicative). pH fit peaks at the centre of
    the crop's pH range and falls toward its edges, so it is rarely a flat 100."""
    notes = []
    if soil_ph is None:
        ph_s = 70.0
        notes.append("pH unknown (neutral score used)")
    else:
        lo, hi = float(k["ph_opt_min"]), float(k["ph_opt_max"])
        if lo <= soil_ph <= hi:
            half = max((hi - lo) / 2, 1e-6)
            ph_s = 100.0 - 15.0 * abs(soil_ph - (lo + hi) / 2) / half
            notes.append("pH inside the indicative range")
        else:
            dist = lo - soil_ph if soil_ph < lo else soil_ph - hi
            ph_s = float(max(0.0, 85.0 - 35 * dist))
            notes.append(f"pH is {dist:.1f} units outside the indicative range")
    tf = SOIL_TYPE_FIT.get(crop, {}).get(str(soil_type).lower()) if soil_type else None
    if tf is None:
        return float(round(ph_s, 1)), "; ".join(notes)
    notes.append(f"{soil_type} soil suits this crop {tf}/100 (indicative)")
    return float(round(0.5 * ph_s + 0.5 * tf, 1)), "; ".join(notes)


def soil_impact(crop, k, farm):
    """Proxy 0-100 (higher = gentler on soil). Rotation and nutrient demand only."""
    score, notes = 60.0, []
    if bool(k["nitrogen_fixing"]):
        score += 25
        notes.append("legume fixes nitrogen")
    score -= {1: 0, 2: 5, 3: 15}[int(k["nutrient_demand"])]
    prev = [norm_crop(c) for c in farm.previous_crops]
    if prev:
        last = prev[0]
        if last == crop:
            score -= 30
            notes.append("same crop as last season (disease/nutrient build-up)")
        elif FAMILY.get(last) and FAMILY.get(last) == FAMILY.get(crop):
            score -= 20
            notes.append("same crop family as last season")
        elif FAMILY.get(last) == "Fabaceae" and FAMILY.get(crop) == "Poaceae":
            score += 10
            notes.append("follows a legume (nitrogen credit)")
    return float(np.clip(score, 0, 100)), notes


def predict_yields(farm, rows):
    """rows: list of dicts with crop_type, avg_temp_c, season. Experimental."""
    d = Data.get()
    meta = d.meta
    recs = []
    for r in rows:
        rec = {c: meta["numeric_ranges"][c][2] for c in meta["numeric_features"]}
        lo, hi = meta["numeric_ranges"]["avg_temp_c"][:2]
        rec["avg_temp_c"] = float(np.clip(r["avg_temp_c"], lo, hi))
        if farm.soil_ph is not None:
            rec["soil_ph"] = farm.soil_ph
        rec.update(weather_zone="dry", irrigation_method=farm.irrigation_method,
                   seed_quality="medium", soil_type=farm.soil_type, fertilized=farm.fertilized,
                   season=r["season"], crop_type=r["crop_type"])
        recs.append(rec)
    X = pd.DataFrame(recs)[meta["feature_order"]]
    return d.model.predict(X)


# ---- Evaluation --------------------------------------------------------------
def evaluate(farm, crops=None):
    farm.validate()
    d = Data.get()
    loc, dist = nearest_location(farm.lat, farm.lon)
    crops = [norm_crop(c) for c in (crops or ACTIVE_CROPS)]
    rows, partial = [], []
    for crop in crops:
        if crop not in d.know.index:
            partial.append(crop)
            continue
        k, tr = d.know.loc[crop], d.traits.loc[crop]
        days = int(round((tr["maturity_min_days"] + tr["maturity_max_days"]) / 2))
        w = climate_and_heat(loc, k, farm.planting_date, days)
        wm = water_metrics(tr, farm, w["window_rain_mm"])
        sf, sf_note = soil_fit_score(k, farm.soil_ph, farm.soil_type, crop)
        si, si_notes = soil_impact(crop, k, farm)
        plant_months = [int(m) for m in str(k["plant_months"]).split(",")]
        m = farm.planting_date.month
        dist_m = min(min((m - pm) % 12, (pm - m) % 12) for pm in plant_months)
        harvest, hd, gdd_reached = gdd_harvest(d.clim[loc], farm.planting_date,
                                               k["gdd_base_c"], k["gdd_to_maturity"])
        best = best_climate_start(loc, k, days, farm.planting_date)
        hp = w["heat_excess_share"]  # extra hot days vs the crop's normal season
        fao = d.fao_egypt.get(crop)
        rows.append(dict(
            location_id=loc, snap_distance_km=round(dist, 1), crop=crop, scope="full",
            yield_available=bool(crop in YIELD_CROPS),
            fao_egypt_yield_t_ha=round(fao["t_ha"], 2) if fao else np.nan,
            fao_egypt_years=fao["years"] if fao else "",
            planting_date=farm.planting_date.isoformat(), window_days=days,
            window_temp_mean_c=w["window_temp_mean"], window_rain_mm=w["window_rain_mm"],
            temp_fit=w["temp_fit"], heat_day_share=w["heat_day_share"], heat_normal_share=w["heat_normal_share"], heat_excess_share=hp,
            
            heat_stress_risk="low" if hp < 0.05 else ("moderate" if hp < 0.15 else "high"),
            heat_score=100 * (1 - min(1, hp / 0.25)),
            heat_tolerance_class=k["heat_tolerance_class"], heat_threshold_tmax_c=k["heat_tmax_c"],
            **wm, soil_fit=sf, soil_fit_note=sf_note, soil_impact_score=si,
            soil_impact_notes="; ".join(si_notes), nutrient_demand=int(k["nutrient_demand"]),
            season_fit=max(0.0, 100 - 30 * dist_m), in_calendar_window=bool(dist_m == 0),
            gdd_base_c=k["gdd_base_c"], gdd_target=k["gdd_to_maturity"],
            gdd_harvest_date=harvest.isoformat() if harvest else None, gdd_days_to_harvest=hd,
            fao_maturity_days=f"{int(tr['maturity_min_days'])}-{int(tr['maturity_max_days'])}",
            best_climate_start=best.isoformat(),
            shift_vs_today_days=(best - farm.planting_date).days,
            _season=season_of(farm.planting_date.month)))
    full = pd.DataFrame(rows)
    if len(full):
        # Yield estimate only for crops the model was trained on. The others stay NaN (no invented number).
        has_y = full["yield_available"].astype(bool)
        full["pred_yield_tons_experimental"] = np.nan
        if has_y.any():
            sub = full[has_y]
            pred = predict_yields(farm, [dict(crop_type=r["crop"], avg_temp_c=r["window_temp_mean_c"],
                                              season=r["_season"]) for _, r in sub.iterrows()])
            full.loc[has_y, "pred_yield_tons_experimental"] = pred
        med = full["crop"].map(d.crop_median_yield)
        full["yield_index"] = full["pred_yield_tons_experimental"] / med
        full["yield_score"] = np.clip(50 + 250 * (full["yield_index"] - 1), 0, 100)
        # Goal scores: weights are renormalised over the components that exist for the crop, so a crop
        # with no yield estimate is scored on the other six components (core crops are unchanged).
        for g, wts in GOAL_WEIGHTS.items():
            num = sum(wt * full[c].fillna(0) for wt, c in zip(wts, COMPONENTS))
            den = sum(wt * full[c].notna() for wt, c in zip(wts, COMPONENTS))
            full[f"score_{g}"] = num / den
        full["overall_score"] = full[f"score_{farm.goal}"]
        full["recommendation"] = full["overall_score"].map(label_for)
        full["warnings"] = full.apply(_warnings, axis=1)
        full["explanation"] = full.apply(lambda r: _explain(r, farm), axis=1)
        full = full.drop(columns="_season")
    return full, partial


def evaluate_extended(farm, top=5):
    """Climate + pH only, for the Crop Recommendation crops (limited data)."""
    d = Data.get()
    loc, _ = nearest_location(farm.lat, farm.lon)
    clim = d.clim[loc]
    rows = []
    for crop in d.extended:
        p = d.profile.loc[crop]
        perennial = crop in PERENNIAL_CROPS
        days = 365 if perennial else 120
        temp = clim["temp_mean"][_window_idx(farm.planting_date, days)]
        lo, hi = p["temperature_q10"], p["temperature_q90"]
        fit = float(trapezoid(temp, lo - 6, lo, hi, hi + 6).mean())
        phs = 70.0
        if farm.soil_ph is not None and not np.isnan(p["ph_q10"]):
            dist = max(p["ph_q10"] - farm.soil_ph, farm.soil_ph - p["ph_q90"], 0)
            phs = max(0.0, 100 - 35 * dist)
        rows.append(dict(location_id=loc, crop=crop, scope="limited_climate_and_ph_only",
                         crop_cycle="perennial (full-year climate)" if perennial else "seasonal (120-day window)",
                         window_days=days, comparable_with_core=False,
                         temp_fit=fit, soil_fit=phs, overall_score=0.7 * fit + 0.3 * phs,
                         note="Limited score (climate and pH only). Not comparable with the core crops. "
                              "No water, heat, GDD or yield data for this crop."))
    return pd.DataFrame(rows).sort_values("overall_score", ascending=False).head(top)


def _warnings(r):
    w = []
    if r["heat_stress_risk"] == "high":
        w.append(f"High heat-stress risk (about {r['heat_excess_share']:.0%} more flowering/filling days above {r['heat_threshold_tmax_c']} C than in the crop's normal season)")
    if not r["water_feasible"]:
        w.append(f"Needs about {r['gross_irrigation_mm']:.0f} mm irrigation, above your {r['water_capacity_mm']} mm")
    if not r["in_calendar_window"]:
        w.append("Outside the usual planting months in Egypt")
    if r["soil_fit"] < 60:
        w.append(r["soil_fit_note"])
    if r["temp_fit"] < 50:
        w.append("Temperatures in the growing window are far from the crop's range")
    return "; ".join(w)


def _explain(r, farm):
    parts = [f"Temperature fit {r['temp_fit']:.0f}/100 (mean {r['window_temp_mean_c']:.1f} C over {r['window_days']} days)",
             f"heat-stress risk {r['heat_stress_risk']}",
             f"water demand {r['water_demand_class']} (about {r['gross_irrigation_mm']:.0f} mm gross irrigation)"]
    if r["soil_impact_notes"]:
        parts.append("soil: " + r["soil_impact_notes"])
    if r["gdd_harvest_date"]:
        parts.append(f"GDD-based harvest around {r['gdd_harvest_date']} (base {r['gdd_base_c']} C)")
    if abs(r["shift_vs_today_days"]) >= 20:
        parts.append(f"climate-best planting start is {r['best_climate_start']}")
    if not bool(r["yield_available"]):
        txt = "no yield estimate for this crop yet (no yield model)"
        if r["fao_egypt_yield_t_ha"] == r["fao_egypt_yield_t_ha"]:
            txt += f"; FAO average yield in Egypt {r['fao_egypt_yield_t_ha']:.1f} t/ha ({r['fao_egypt_years']})"
        parts.append(txt)
    return "; ".join(parts)



# ---- Trade-offs and soil outlook ---------------------------------------------
def rotation_plan(farm, crop, seasons=3):
    """Soil-only view (proxy). Compares repeating `crop` against a greedy rotation.

    Planting months and climate are NOT considered here, only the rotation and
    nutrient-demand proxy from soil_impact().
    """
    from copy import copy
    d = Data.get()
    crop = norm_crop(crop)

    def impact(c, prev):
        f = copy(farm)
        f.previous_crops = prev
        return soil_impact(c, d.know.loc[c], f)[0]

    prev_repeat = list(farm.previous_crops)
    repeat = []
    for _ in range(seasons):
        repeat.append(round(impact(crop, prev_repeat), 1))
        prev_repeat = [crop] + prev_repeat

    prev_rot, rotate, names = list(farm.previous_crops), [], []
    first = True
    for _ in range(seasons):
        if first:
            c = crop  # season 1 is the crop the farmer wants
            first = False
        else:
            c = max(ACTIVE_CROPS, key=lambda x: impact(x, prev_rot))
        rotate.append(round(impact(c, prev_rot), 1))
        names.append(c)
        prev_rot = [c] + prev_rot
    return dict(crop=crop, repeat_scores=repeat, repeat_mean=float(np.mean(repeat)),
                rotation_crops=names, rotation_scores=rotate, rotation_mean=float(np.mean(rotate)))


def tradeoff_analysis(df, w_yield=5, w_soil=5, w_water=5, min_feasibility=40, min_season_fit=40):
    """Adds regret-based columns to an evaluate() result.

    Criteria (higher is better): yield_score, soil_impact_score, water_score.
    A crop is 'feasible' when its climate/heat/season feasibility is high enough.
    regret_x = best feasible value of x minus this crop's x (what you give up).
    Least-loss pick = feasible crop with the smallest weighted maximum regret.
    Pareto = feasible crops that no other feasible crop beats on all three criteria.
    """
    out = df.copy()
    if "yield_available" not in out:
        out["yield_available"] = True
    # A crop with no yield estimate cannot be judged on yield. While yield matters (weight above the
    # minimum), it is shown but not eligible for the least-regret pick or the Pareto set.
    eligible = out["yield_available"].astype(bool) | (w_yield <= 0.1)
    out["comparable_on_yield"] = eligible
    out["feasibility"] = out[["temp_fit", "heat_score", "season_fit"]].mean(axis=1)
    # Step 6: a crop is feasible only if the average fit is high enough AND the planting date is
    # within about 2 months of its usual planting months (season_fit 40 = 2 months away).
    out["feasible"] = (out["feasibility"] >= min_feasibility) & (out["season_fit"] >= min_season_fit)
    crit = {"yield": "yield_score", "soil": "soil_impact_score", "water": "water_score"}
    weights = {"yield": w_yield, "soil": w_soil, "water": w_water}
    feas = out[out["feasible"] & eligible]
    for k, col in crit.items():
        best = feas[col].max() if len(feas) else out[col].max()
        out[f"regret_{k}"] = (best - out[col]).clip(lower=0)
    wsum = max(sum(weights.values()), 1e-9)
    wmax = max(weights.values()) or 1
    out["max_weighted_regret"] = out[[f"regret_{k}" for k in crit]].mul(
        [weights[k] / wmax for k in crit], axis=1).max(axis=1)
    num = sum(weights[k] * out[col].fillna(0) for k, col in crit.items())
    den = sum(weights[k] * out[col].notna() for k, col in crit.items()).clip(lower=1e-9)
    out["custom_score"] = num / den * 0.7 + 0.3 * out["feasibility"]
    cols = list(crit.values())
    pareto = []
    for i, r in out.iterrows():
        if not r["feasible"] or not bool(eligible.loc[i]):
            pareto.append(False)
            continue
        dominated = any(
            (o[cols] >= r[cols]).all() and (o[cols] > r[cols]).any()
            for j, o in feas.iterrows() if j != i)
        pareto.append(not dominated)
    out["pareto"] = pareto
    cand = out[out["feasible"] & eligible]
    out["least_loss_pick"] = False
    if len(cand):
        out.loc[cand["max_weighted_regret"].idxmin(), "least_loss_pick"] = True
    return out.sort_values(["feasible", "max_weighted_regret"], ascending=[False, True])


# ---- My Farm modes -----------------------------------------------------------
def check_my_crop(farm, crop):
    df, partial = evaluate(farm, [crop])
    if df.empty:
        ext = Data.get()
        c = norm_crop(crop)
        if c in ext.extended:
            e = evaluate_extended(farm, top=len(ext.extended))
            row = e[e["crop"] == c].iloc[0].to_dict()
            row["verdict"] = "Limited analysis only (climate and pH)"
            return row
        return {"error": f"Unknown crop {crop}. Supported: {FULL_CROPS + ext.extended}"}
    r = df.iloc[0].to_dict()
    r["verdict"] = r["recommendation"]
    return r


def suggest_crops(farm, top=5):
    df, _ = evaluate(farm)
    df = df.sort_values("overall_score", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df.head(top), evaluate_extended(farm, top=3)


def compare_crops(farm, crops):
    df, partial = evaluate(farm, crops)
    return df.sort_values("overall_score", ascending=False), partial


# ---- Step 5: explicit alternatives (what to grow instead, or when to wait) ---
def _py(v):
    """numpy -> plain python, so the result is JSON friendly for the API later."""
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def advise_crop(farm, crop, min_gain=5, top_alt=3, wait_min_days=14):
    """Check My Crop plus an explicit answer to: what should I grow instead?

    Returns a dict with:
      check            the normal check_my_crop result
      needs_alternative  True when the requested crop is below 'Recommended' (score < 70)
      alternatives     up to top_alt CORE crops that beat the requested one by min_gain points,
                       are at least 'Possible with caution' (>= 50) and feasible, with the
                       gain or loss per criterion (overall, yield index, soil proxy, water)
      wait_option      same crop, but planted at its best climate start, if that is at least
                       wait_min_days away (with the score it would get then)
      least_loss_pick  the crop with the smallest weighted regret among feasible core crops
    Alternatives only come from the 5 core crops (the only ones with full data).
    """
    crop_n = norm_crop(crop)
    base = check_my_crop(farm, crop_n)
    out = {"requested_crop": crop_n, "check": base, "needs_alternative": False,
           "alternatives": [], "wait_option": None, "least_loss_pick": None, "note": ""}
    # Evaluate the default crops, plus the requested one when it has full data but is not a default yet.
    pool = list(ACTIVE_CROPS) + ([crop_n] if crop_n in FULL_CROPS and crop_n not in ACTIVE_CROPS else [])
    full, _ = evaluate(farm, pool)
    if full.empty:
        return out
    t = tradeoff_analysis(full)
    pick = t[t["least_loss_pick"]]
    out["least_loss_pick"] = pick.iloc[0]["crop"] if len(pick) else None
    is_core = crop_n in FULL_CROPS

    if "error" in base:
        out["needs_alternative"] = True
        out["note"] = "This crop is not supported yet, so here are the best supported crops for your farm."
        ref_score = 0.0
        req = None
    elif not is_core:
        out["note"] = ("Limited analysis only for this crop (climate and pH). "
                       "Its score is not comparable with the core crops, so no switch is advised.")
        return out
    else:
        req = full[full["crop"] == crop_n].iloc[0]
        ref_score = float(req["overall_score"])
        out["needs_alternative"] = ref_score < 70

    if out["needs_alternative"]:
        cand = t[(t["crop"] != crop_n) & t["feasible"] & (t["overall_score"] >= 50)
                 & (t["overall_score"] >= ref_score + min_gain)]
        cand = cand.sort_values("overall_score", ascending=False).head(top_alt)
        for _, a in cand.iterrows():
            item = dict(crop=a["crop"], overall_score=round(float(a["overall_score"]), 1),
                        recommendation=a["recommendation"],
                        gdd_harvest_date=a["gdd_harvest_date"],
                        warnings=a["warnings"])
            if req is not None:
                item.update(
                    delta_overall=round(float(a["overall_score"] - req["overall_score"]), 1),
                    delta_yield_index=(None if pd.isna(a["yield_score"] - req["yield_score"])
                                       else round(float(a["yield_score"] - req["yield_score"]), 1)),
                    delta_soil=round(float(a["soil_impact_score"] - req["soil_impact_score"]), 1),
                    delta_water=round(float(a["water_score"] - req["water_score"]), 1))
            out["alternatives"].append(item)
        if not out["alternatives"]:
            out["note"] = "No core crop is clearly better right now. Waiting for a better start date may help."

    if req is not None and int(req["shift_vs_today_days"]) >= wait_min_days:
        best_day = date.fromisoformat(str(req["best_climate_start"]))
        later, _ = evaluate(replace(farm, planting_date=best_day), [crop_n])
        if len(later):
            out["wait_option"] = dict(
                start_date=best_day.isoformat(), days_from_now=int(req["shift_vs_today_days"]),
                score_then=round(float(later.iloc[0]["overall_score"]), 1),
                verdict_then=later.iloc[0]["recommendation"])
    out["alternatives"] = [{k: _py(v) for k, v in a.items()} for a in out["alternatives"]]
    return out


# ---- Final tables for the website --------------------------------------------
def build_final_tables():
    """Default-farm scores for all 10 governorates x 5 core crops, plus knowledge."""
    out = []
    for loc, (lat, lon) in LOCATIONS.items():
        farm = Farm(lat=lat, lon=lon)  # defaults: loam, sprinkler, medium water, today
        df, _ = evaluate(farm)
        out.append(df)
    allr = pd.concat(out, ignore_index=True)
    allr["rank_in_location"] = allr.groupby("location_id")["score_balanced"].rank(ascending=False, method="first").astype(int)
    allr["as_of_planting_date"] = date.today().isoformat()
    allr["data_status"] = "climate_real_nasa_power; yield_experimental_synthetic; crop_params_indicative"
    num = allr.select_dtypes("number").columns
    allr[num] = allr[num].round(3)
    allr.to_csv(FINAL / "location_crop_scores.csv", index=False)
    pd.read_csv(PROC / "crop_knowledge.csv").to_csv(FINAL / "crop_knowledge.csv", index=False)
    pd.DataFrame([dict(location_id=k, lat=v[0], lon=v[1]) for k, v in LOCATIONS.items()]).to_csv(
        FINAL / "locations.csv", index=False)
    print(f"Saved {len(allr)} rows -> {FINAL / 'location_crop_scores.csv'}")
    return allr


# ---- CLI ---------------------------------------------------------------------
def _show(df, cols):
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 120)
    print(df[cols].round(1).to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["suggest", "check", "compare", "advise"], default="suggest")
    ap.add_argument("--lat", type=float, default=30.79)
    ap.add_argument("--lon", type=float, default=31.00)
    ap.add_argument("--soil", default="loam")
    ap.add_argument("--ph", type=float, default=None)
    ap.add_argument("--water", default="medium")
    ap.add_argument("--irrigation", default="sprinkler")
    ap.add_argument("--prev", default="", help="comma list, most recent first")
    ap.add_argument("--goal", default="balanced")
    ap.add_argument("--date", default=None, help="planting date YYYY-MM-DD")
    ap.add_argument("--crop", default="wheat")
    ap.add_argument("--crops", default="wheat,maize,rice")
    ap.add_argument("--build-final", action="store_true")
    a = ap.parse_args()
    if a.build_final:
        build_final_tables()
        return
    farm = Farm(a.lat, a.lon, a.soil, a.ph, a.water, a.irrigation,
                [c for c in a.prev.split(",") if c], a.goal,
                date.fromisoformat(a.date) if a.date else date.today())
    loc, dist = nearest_location(a.lat, a.lon)
    print(f"Nearest reference governorate: {loc} ({dist:.0f} km)"
          + ("  [FAR: climate is only indicative]" if dist > MAX_SNAP_KM else ""))
    cols = ["crop", "overall_score", "recommendation", "temp_fit", "heat_stress_risk",
            "water_demand_class", "gross_irrigation_mm", "soil_impact_score",
            "pred_yield_tons_experimental", "gdd_harvest_date"]
    if a.mode == "suggest":
        top, ext = suggest_crops(farm)
        _show(top, ["rank"] + cols)
        for _, r in top.iterrows():
            print(f"\n{r['crop']}: {r['explanation']}")
            if r["warnings"]:
                print("  WARNINGS:", r["warnings"])
        print("\nOther crops (climate and pH only, limited data):")
        _show(ext, ["crop", "overall_score", "temp_fit", "soil_fit"])
    elif a.mode == "advise":
        res = advise_crop(farm, a.crop)
        print(json.dumps(res, indent=2, default=str))
    elif a.mode == "check":
        r = check_my_crop(farm, a.crop)
        print(json.dumps({k: (v if not isinstance(v, float) else round(v, 2)) for k, v in r.items()},
                         indent=2, default=str))
    else:
        df, partial = compare_crops(farm, a.crops.split(","))
        _show(df, cols)
        if partial:
            print("No full knowledge for:", partial)


if __name__ == "__main__":
    main()
