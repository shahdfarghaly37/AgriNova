"""Add real NASA POWER climate history for one more governorate.

Needs internet (NASA POWER). Run once per governorate, e.g.:
    python add_governorate.py cairo
    python add_governorate.py --all        # every governorate in egypt.py that has no data yet

It appends daily data (1991 -> today) to data/processed/weather_daily.csv and
registers the place in extra_locations.json, which config.py already reads.
Restart the API afterwards. Without this step a governorate simply uses the
nearest of the 10 reference stations (the API reports the distance).
"""
import argparse, importlib, json
import pandas as pd
from config import ROOT, PROC, LOCATIONS
from egypt import GOVERNORATES

fetch = importlib.import_module("01_fetch_weather")
EXTRA = ROOT / "extra_locations.json"
OUT = PROC / "weather_daily.csv"
COLS = ["date", "temp_mean", "temp_max", "temp_min", "precip_mm", "humidity_pct",
        "wind_ms", "solar_kwh_m2", "source", "location_id"]


def add(gid):
    ar, lat, lon = GOVERNORATES[gid]
    if gid in LOCATIONS:
        print(f"{gid}: already has data, skipping")
        return
    print(f"{gid} ({ar}): downloading from NASA POWER ...")
    df = fetch.fetch_power(lat, lon)
    if df is None or df.empty:
        print(f"{gid}: download failed, nothing changed")
        return
    df = df.rename_axis("date").reset_index()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["source"], df["location_id"] = "nasa_power", gid
    df = df.reindex(columns=COLS)
    df.to_csv(OUT, mode="a", header=False, index=False)
    extra = json.loads(EXTRA.read_text(encoding="utf-8")) if EXTRA.exists() else {}
    extra[gid] = [lat, lon]
    EXTRA.write_text(json.dumps(extra), encoding="utf-8")
    print(f"{gid}: added {len(df)} days")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("gov", nargs="?")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    ids = list(GOVERNORATES) if a.all else [a.gov]
    for g in ids:
        if g not in GOVERNORATES:
            raise SystemExit(f"unknown governorate id: {g}")
        add(g)
