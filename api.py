"""Farmer Imposters API: three simple features on top of 09_engine.

  GET /api/governorates                   list for the picker
  GET /api/crops                          crops the farmer can ask about
  GET /api/top?gov=gharbia&n=3            Feature 1: best crops now
  GET /api/check?gov=gharbia&crop=قمح     Feature 2: is this crop OK?
  GET /api/climate?gov=gharbia            Feature 3: climate + what fits now

Run:  uvicorn api:app --reload --port 8000
Everything uses engine defaults (loam soil, medium water, sprinkler) so the
farmer only picks a governorate. Dates default to today.
"""
import importlib
from datetime import date
from functools import lru_cache

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from config import PROC, LOCATIONS
from egypt import GOVERNORATES, CROPS_AR, CORE, FULL, EXTENDED_OK, CROP_ALIASES, TXT, reasons, summary

eng = importlib.import_module("09_engine")

# Potato and sorghum have the full analysis but no yield estimate (no yield model for them).
# Keep this False until web/index.html can show a crop without a yield number; then set True.
NEW_FULL = [c for c in FULL if c not in CORE]
SHOW_NEW_CROPS = False
if SHOW_NEW_CROPS:
    eng.ACTIVE_CROPS = list(eng.FULL_CROPS)
app = FastAPI(title="Farmer Imposters API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CLIMATE_NOW = pd.read_csv(PROC / "current_climate.csv").set_index("location_id")

def T(lang):
    return TXT.get(lang, TXT['en'])


# ---- helpers ------------------------------------------------------------------
def _gov(gov, lang="en"):
    if gov not in GOVERNORATES:
        raise HTTPException(404, T(lang)["no_gov"])
    return GOVERNORATES[gov]


def _day(day, lang="en"):
    try:
        return date.fromisoformat(day) if day else date.today()
    except ValueError:
        raise HTTPException(400, T(lang)["bad_date"])


def _farm(gov, day):
    _, lat, lon = _gov(gov)
    return eng.Farm(lat=lat, lon=lon, planting_date=day)


def _crop(name, lang="en"):
    key = str(name).strip().lower()
    key = CROP_ALIASES.get(key, key)
    key = eng.norm_crop(key)
    if key not in CROPS_AR or (key in NEW_FULL and not SHOW_NEW_CROPS):
        raise HTTPException(404, T(lang)["no_crop"])
    return key


def _lvl(score):  # 3 good / 2 medium / 1 bad  (for the three dots in the UI)
    return 3 if score >= 70 else 2 if score >= 45 else 1


def _verdict(score):
    return "yes" if score >= 70 else "maybe" if score >= 50 else "no"


def _yield_level(s):
    return "high" if s >= 65 else "medium" if s >= 40 else "low"


def _soil_level(s):
    return "gentle" if s >= 65 else "normal" if s >= 45 else "tiring"


def _water_level(r):
    return r["water_demand_class"]


def _station(farm):
    loc, km = eng.nearest_location(farm.lat, farm.lon)
    return loc, round(km)


def _month_year(iso, t):
    if not iso or str(iso) == "nan":
        return None
    d = date.fromisoformat(str(iso))
    return f"{t['months'][d.month - 1]} {d.year}"


def _card(r, t):
    """One core crop as the UI needs it."""
    s = float(r["overall_score"])
    return dict(
        crop=r["crop"], name=t["crop"][r["crop"]], score=round(s), verdict=_verdict(s),
        verdict_text=t["verdict"][_verdict(s)],
        heat=_lvl(float(r["heat_score"])), water=_lvl(float(r["water_score"])),
        soil=_lvl(float(r["soil_impact_score"])),
        harvest=_month_year(r.get("gdd_harvest_date"), t), reasons=reasons(r, t), limited=False)


def _ext_card(r, t):
    s = float(r["overall_score"])
    return dict(crop=r["crop"], name=t["crop"][r["crop"]], score=round(s), verdict=_verdict(s),
                verdict_text=t["verdict"][_verdict(s)], limited=True,
                reasons=reasons(dict(r, scope="limited"), t))


@lru_cache(maxsize=512)
def _all(gov, day_iso):
    farm = _farm(gov, date.fromisoformat(day_iso))
    df, _ = eng.evaluate(farm)
    return df.sort_values("overall_score", ascending=False).to_dict("records")


@lru_cache(maxsize=512)
def _ext(gov, day_iso):
    farm = _farm(gov, date.fromisoformat(day_iso))
    e = eng.evaluate_extended(farm, top=len(eng.Data.get().extended))
    return e[e["crop"].isin(EXTENDED_OK)].to_dict("records")


# ---- endpoints (all take ?lang=en|ar, default en) ----------------------------------
@app.get("/api/governorates")
def governorates(lang: str = "en"):
    t, out = T(lang), []
    for gid, (ar, lat, lon) in GOVERNORATES.items():
        st, km = eng.nearest_location(lat, lon)
        out.append(dict(id=gid, name=t["gov"][gid], lat=lat, lon=lon, own_data=gid in LOCATIONS,
                        station=t["gov"].get(st, st), station_km=round(km)))
    return out


@app.get("/api/crops")
def crops(lang: str = "en"):
    return [dict(id=c, name=T(lang)["crop"][c], full=c in FULL) for c in CROPS_AR
            if SHOW_NEW_CROPS or c not in NEW_FULL]


@app.get("/api/top")
def top(gov: str, n: int = Query(3, ge=1, le=5), day: str | None = None, lang: str = "en"):
    t, d = T(lang), _day(day, lang)
    _gov(gov, lang)
    rows = _all(gov, d.isoformat())[:n]
    others = [_ext_card(r, t) for r in _ext(gov, d.isoformat())[:3] if r["overall_score"] >= 60]
    _, km = _station(_farm(gov, d))
    return dict(governorate=t["gov"][gov], date=d.isoformat(), top=[_card(r, t) for r in rows],
                others=others, station_km=km if km > 150 else None, note=t["note"])


@app.get("/api/check")
def check(gov: str, crop: str, day: str | None = None, lang: str = "en"):
    t, d = T(lang), _day(day, lang)
    _gov(gov, lang)
    c = _crop(crop, lang)
    res = eng.advise_crop(_farm(gov, d), c)
    base = res["check"]
    if "error" in base:
        raise HTTPException(404, t["no_crop"])
    s = float(base["overall_score"])
    v = _verdict(s)
    out = dict(crop=c, name=t["crop"][c], governorate=t["gov"][gov], date=d.isoformat(),
               score=round(s), verdict=v, verdict_text=t["verdict"][v])
    if c in FULL:
        ya = bool(base.get("yield_available", True))
        so = _soil_level(float(base["soil_impact_score"]))
        yl = _yield_level(float(base["yield_score"])) if ya else None
        out.update(reasons=reasons(base, t), yield_level=yl, yield_text=t["yield_"][yl] if ya else t["no_yield"],
                   soil_level=so, soil_text=t["soil"][so], water_level=_water_level(base),
                   water_text=t["water"][_water_level(base)], harvest=_month_year(base.get("gdd_harvest_date"), t),
                   limited=False, note=t["note"] if ya else t["no_yield"],
                   summary=summary(yl, so, t) if ya else t["no_yield"])
    else:
        out.update(reasons=reasons(dict(base, scope="limited"), t), limited=True, summary=t["rough"])
    alts = []
    if v != "yes":
        alts = [dict(crop=a["crop"], name=t["crop"][a["crop"]], score=round(a["overall_score"]))
                for a in res["alternatives"]]
        if not alts:
            alts = [dict(crop=r["crop"], name=t["crop"][r["crop"]], score=round(r["overall_score"]))
                    for r in _all(gov, d.isoformat()) if r["crop"] != c and r["overall_score"] >= 50][:3]
    out["alternatives"] = alts
    w = res["wait_option"]
    out["wait"] = None if not w else dict(
        date=w["start_date"], month=t["months"][date.fromisoformat(w["start_date"]).month - 1],
        days=w["days_from_now"], score=round(w["score_then"]), verdict=_verdict(w["score_then"]),
        verdict_text=t["verdict"][_verdict(w["score_then"])])
    return out


@app.get("/api/climate")
def climate(gov: str, day: str | None = None, lang: str = "en"):
    t, d = T(lang), _day(day, lang)
    _gov(gov, lang)
    st, km = _station(_farm(gov, d))
    cc = CLIMATE_NOW.loc[st]
    clim = eng.Data.get().clim[st]
    doy_month = [date.fromordinal(date(2001, 1, 1).toordinal() + i).month for i in range(365)]
    s = pd.Series(clim["temp_mean"]).groupby(doy_month).mean()
    rows = _all(gov, d.isoformat())
    fit_now = [dict(crop=r["crop"], name=t["crop"][r["crop"]], score=round(r["overall_score"]))
               for r in rows if r["overall_score"] >= 50]
    fit_now += [dict(crop=r["crop"], name=t["crop"][r["crop"]], score=round(r["overall_score"]), limited=True)
                for r in _ext(gov, d.isoformat()) if r["overall_score"] >= 70][:3]
    best_month = [dict(crop=r["crop"], name=t["crop"][r["crop"]],
                       month=t["months"][date.fromisoformat(r["best_climate_start"]).month - 1]) for r in rows]
    return dict(governorate=t["gov"][gov], season=t["seasons"][eng.season_of(d.month)],
                temp_now=round(float(cc["temp_mean_14d"]), 1), temp_max_now=round(float(cc["temp_max_14d"]), 1),
                rain_90d_mm=round(float(cc["rain_90d_mm"]), 1), as_of=str(cc["as_of"]),
                monthly_temp=[round(float(s[m]), 1) for m in range(1, 13)], months=t["months"],
                fit_now=fit_now, best_month=best_month, station_km=km if km > 150 else None)




# Show the real error in the page (and in the black window) instead of a bare 500
import traceback
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def any_error(request, exc):
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})

# ---- NEW: endpoints for the new design (all English, every farm field is accepted) ----
from dataclasses import replace
from fastapi.responses import PlainTextResponse
DRIFT = pd.read_csv(PROC / "climate_drift.csv")
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
NAME = {c: TXT["en"]["crop"][c] for c in CROPS_AR}
_n = lambda v: None if v is None or v != v else round(float(v), 1)

def _fm(gov, soil="loam", ph=None, m3=3800.0, irr="drip", goal="balanced", day=None, prev="", lat=None, lon=None):
    _, la, lo = _gov(gov)
    lat = la if lat is None else lat  # the map pin wins over the governorate centre
    lon = lo if lon is None else lon
    mm = float(m3) / 4.2  # 1 mm of water = 4.2 m3 per feddan
    water = "low" if mm < 750 else "medium" if mm < 1250 else "high"
    return eng.Farm(lat=lat, lon=lon, soil_type=soil, soil_ph=ph, water_availability=water,
                    irrigation_method=irr, goal=goal, planting_date=_day(day),
                    previous_crops=[c for c in prev.split(",") if c])

def _run(f, crops=None):
    try:
        return eng.evaluate(f, crops)
    except AssertionError as e:
        raise HTTPException(400, str(e))

def _row(r):
    return dict(crop=r["crop"], name=NAME[r["crop"]], score=round(float(r["overall_score"])),
                verdict=_verdict(r["overall_score"]), label=r["recommendation"],
                heat=_lvl(float(r["heat_score"])), water=_lvl(float(r["water_score"])),
                soil=_lvl(float(r["soil_impact_score"])), harvest=_month_year(r.get("gdd_harvest_date"), TXT["en"]),
                yield_score=round(float(r["yield_score"])) if r.get("yield_available", True) else None,
                yield_available=bool(r.get("yield_available", True)), fao_yield_t_ha=_n(r.get("fao_egypt_yield_t_ha")),
                yield_note=None if r.get("yield_available", True) else TXT["en"]["no_yield"],
                temp_fit=round(float(r["temp_fit"])),
                season_fit=round(float(r["season_fit"])), heat_score=round(float(r["heat_score"])),
                water_score=round(float(r["water_score"])), soil_score=round(float(r["soil_impact_score"])),
                warnings=r["warnings"])

@app.get("/api/app/suggest")
def app_suggest(gov: str, soil: str = "loam", ph: float | None = None, m3: float = 3800, irr: str = "drip",
                goal: str = "balanced", day: str | None = None, prev: str = "", lat: float | None = None, lon: float | None = None):
    f = _fm(gov, soil, ph, m3, irr, goal, day, prev, lat, lon)
    df, _ = _run(f)
    rows = [_row(r) for r in df.sort_values("overall_score", ascending=False).to_dict("records")]
    e = eng.evaluate_extended(f, top=len(eng.Data.get().extended))
    more = [dict(crop=r["crop"], name=NAME[r["crop"]], score=round(float(r["overall_score"])))
            for r in e.to_dict("records") if r["crop"] in EXTENDED_OK][:10]
    _, km = _station(f)
    return dict(gov=gov, date=f.planting_date.isoformat(), crops=rows, more=more, station_km=km)

@app.get("/api/app/check")
def app_check(gov: str, crop: str, soil: str = "loam", ph: float | None = None, m3: float = 3800,
              irr: str = "drip", goal: str = "balanced", day: str | None = None, prev: str = "", lat: float | None = None, lon: float | None = None):
    f = _fm(gov, soil, ph, m3, irr, goal, day, prev, lat, lon)
    c = _crop(crop)
    res = eng.advise_crop(f, c)
    b = res["check"]
    if "error" in b:
        raise HTTPException(404, b["error"])
    s = float(b["overall_score"])
    out = dict(crop=c, name=NAME[c], score=round(s), verdict=_verdict(s), label=b["recommendation"] if "recommendation" in b else b.get("verdict"),
               limited=c not in FULL, note=res["note"], soil_note=b.get("soil_fit_note"))
    if c in FULL:
        ya = bool(b.get("yield_available", True))
        out.update(yield_available=ya, fao_yield_t_ha=_n(b.get("fao_egypt_yield_t_ha")),
                   fao_years=b.get("fao_egypt_years") or None, yield_note=None if ya else TXT["en"]["no_yield"])
        out.update(yield_t=_n(b["pred_yield_tons_experimental"]), yield_index=_n(b["yield_index"]),
                   water_mm=round(float(b["gross_irrigation_mm"])), water_cap=round(float(b["water_capacity_mm"])),
                   water_feasible=bool(b["water_feasible"]), heat_risk=b["heat_stress_risk"],
                   heat_share=round(100 * float(b["heat_excess_share"]), 1), heat_tmax=_n(b["heat_threshold_tmax_c"]),
                   temp=_n(b["window_temp_mean_c"]), soil_score=round(float(b["soil_fit"])),
                   harvest=_month_year(b.get("gdd_harvest_date"), TXT["en"]), warnings=b["warnings"])
    if c not in FULL:
        out.update(temp_fit=round(float(b["temp_fit"])), ph_fit=round(float(b["soil_fit"])), ph_known=f.soil_ph is not None)
    out["alternatives"] = [dict(crop=a["crop"], name=NAME[a["crop"]], score=a["overall_score"],
                                d_yield=a.get("delta_yield_index"), d_water=a.get("delta_water"))
                           for a in res["alternatives"]]
    w = res["wait_option"]
    out["wait"] = w and dict(date=w["start_date"], days=w["days_from_now"], score=round(w["score_then"]),
                             verdict=_verdict(w["score_then"]))
    return out

@app.get("/api/app/compare")
def app_compare(gov: str, w_yield: float = 5, w_soil: float = 5, w_water: float = 5, soil: str = "loam",
                ph: float | None = None, m3: float = 3800, irr: str = "drip", day: str | None = None, prev: str = "", lat: float | None = None, lon: float | None = None):
    f = _fm(gov, soil, ph, m3, irr, "balanced", day, prev, lat, lon)
    df, _ = _run(f)
    t = eng.tradeoff_analysis(df, max(w_yield, .1), max(w_soil, .1), max(w_water, .1))
    t = t.sort_values(["feasible", "custom_score"], ascending=[False, False])
    return dict(crops=[dict(_row(r), fit=round(float(r["custom_score"])), feasible=bool(r["feasible"]),
                            best=bool(r["least_loss_pick"]), regret=round(float(r["max_weighted_regret"])),
                            comparable_on_yield=bool(r["comparable_on_yield"]))
                       for r in t.to_dict("records")])

@app.get("/api/app/drift")
def app_drift(gov: str, lat: float | None = None, lon: float | None = None):
    _, la, lo = _gov(gov)
    lat = la if lat is None else lat
    lon = lo if lon is None else lon
    st, km = eng.nearest_location(lat, lon)
    d = DRIFT[DRIFT.location_id == st].sort_values("month")
    farm = eng.Farm(lat=lat, lon=lon)
    df, _ = _run(farm, ["wheat", "cotton"])
    return dict(station=TXT["en"]["gov"].get(st, st), km=round(km), months=MONTHS,
                baseline=[_n(v) for v in d.baseline_temp], recent=[_n(v) for v in d.recent_temp],
                delta=[_n(v) for v in d.delta_c], since=int(d.comparison_start_year.iloc[0]),
                mean_delta=round(float(d.delta_c.mean()), 2), base_avg=_n(d.baseline_temp.mean()),
                recent_avg=_n(d.recent_temp.mean()), shift_days=int(df.shift_vs_today_days.mean()))

def _biz(gov, lat=None, lon=None):
    _, la, lo = _gov(gov)
    f = eng.Farm(la if lat is None else lat, lo if lon is None else lon, goal="max_yield")
    df, _ = _run(f)
    cc = CLIMATE_NOW.loc[_station(f)[0]]
    return df.sort_values("overall_score", ascending=False), cc

@app.get("/api/app/business")
def app_business(gov: str, lat: float | None = None, lon: float | None = None):
    df, cc = _biz(gov, lat, lon)
    return dict(gov=gov, crops=[_row(r) for r in df.to_dict("records")], temp_14d=_n(cc["temp_mean_14d"]),
                tmax_14d=_n(cc["temp_max_14d"]), rain_90d=_n(cc["rain_90d_mm"]), as_of=str(cc["as_of"]))

@app.get("/api/app/business.csv")
def app_business_csv(gov: str, lat: float | None = None, lon: float | None = None):
    df, _ = _biz(gov, lat, lon)
    keep = ["crop", "overall_score", "yield_score", "water_score", "heat_score", "soil_impact_score", "heat_stress_risk",
            "gdd_harvest_date", "gross_irrigation_mm", "yield_available", "fao_egypt_yield_t_ha"]
    return PlainTextResponse(df[keep].to_csv(index=False), headers={"Content-Disposition": f"attachment; filename={gov}_crops.csv"})

# ---- serve the website (web/index.html) from the same server -------------------
from pathlib import Path
from fastapi.staticfiles import StaticFiles
if (Path(__file__).parent / "web").exists():
    app.mount("/", StaticFiles(directory=str(Path(__file__).parent / "web"), html=True), name="web")
