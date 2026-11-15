"""Download daily climate for the configured Egyptian locations.

NASA POWER is the primary source. Open-Meteo Archive is the fallback.
The API is called only during this script; downstream scripts read the saved CSV.
"""
import time
import numpy as np
import pandas as pd
import requests
from config import RAW, PROC, LOCATIONS, START_YEAR, END_DATE

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_PARAMS = (
    "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR,"
    "ALLSKY_SFC_SW_DWN,RH2M,WS2M"
)

# NASA ALLSKY_SFC_SW_DWN is MJ/m²/day. Convert to kWh/m²/day.
def normalize_power_frame(data):
    df = pd.DataFrame(data)
    df.index = pd.to_datetime(df.index.astype(str), format="%Y%m%d")
    df = df.replace(-999, np.nan).astype(float)
    df = df.rename(columns={
        "T2M": "temp_mean",
        "T2M_MAX": "temp_max",
        "T2M_MIN": "temp_min",
        "PRECTOTCORR": "precip_mm",
        "ALLSKY_SFC_SW_DWN": "solar_mj_m2",
        "RH2M": "humidity_pct",
        "WS2M": "wind_ms",
    })
    if "solar_mj_m2" in df:
        df["solar_kwh_m2"] = df["solar_mj_m2"] / 3.6
        df = df.drop(columns="solar_mj_m2")
    return df


def fetch_power_chunk(lat, lon, start, end, retries=3):
    params = {
        "parameters": POWER_PARAMS,
        "community": "AG",
        "latitude": lat,
        "longitude": lon,
        "start": start,
        "end": end,
        "format": "JSON",
    }
    for attempt in range(retries):
        try:
            response = requests.get(POWER_URL, params=params, timeout=120)
            response.raise_for_status()
            payload = response.json()["properties"]["parameter"]
            return normalize_power_frame(payload)
        except Exception as exc:
            print(f"  NASA POWER attempt {attempt + 1}/{retries} failed: {exc}")
            if attempt < retries - 1:
                time.sleep(4 * (attempt + 1))
    return None


def fetch_power(lat, lon):
    chunks = []
    for year in range(START_YEAR, END_DATE.year + 1, 10):
        end_year = min(year + 9, END_DATE.year)
        end = END_DATE.strftime("%Y%m%d") if end_year == END_DATE.year else f"{end_year}1231"
        chunk = fetch_power_chunk(lat, lon, f"{year}0101", end)
        if chunk is None:
            return None
        chunks.append(chunk)
    result = pd.concat(chunks).sort_index()
    return result[~result.index.duplicated(keep="last")]


def fetch_open_meteo(lat, lon):
    daily = (
        "temperature_2m_mean,temperature_2m_max,temperature_2m_min,"
        "precipitation_sum,shortwave_radiation_sum"
    )
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": f"{START_YEAR}-01-01",
        "end_date": END_DATE.isoformat(),
        "daily": daily,
        "timezone": "UTC",
    }
    response = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params=params,
        timeout=180,
    )
    response.raise_for_status()
    daily_data = response.json().get("daily")
    if not daily_data or "time" not in daily_data:
        raise ValueError("Open-Meteo returned no daily records.")
    d = pd.DataFrame(daily_data)
    d.index = pd.to_datetime(d.pop("time"))
    out = pd.DataFrame(index=d.index)
    out["temp_mean"] = d["temperature_2m_mean"]
    out["temp_max"] = d["temperature_2m_max"]
    out["temp_min"] = d["temperature_2m_min"]
    out["precip_mm"] = d["precipitation_sum"]
    # Open-Meteo shortwave_radiation_sum is MJ/m²/day.
    out["solar_kwh_m2"] = d["shortwave_radiation_sum"] / 3.6
    # Archive request does not include humidity or wind in this prototype.
    out["humidity_pct"] = np.nan
    out["wind_ms"] = np.nan
    return out


def cache_is_usable(path):
    if not path.exists():
        return False
    try:
        cached = pd.read_csv(path, index_col=0, parse_dates=True)
        required = {"temp_mean", "temp_max", "temp_min", "precip_mm", "solar_kwh_m2"}
        if not required.issubset(cached.columns) or cached.empty:
            return False
        latest = pd.to_datetime(cached.index).max().date()
        return latest >= (END_DATE - pd.Timedelta(days=14)).date()
    except Exception:
        return False


def main():
    frames = []
    for location_id, (lat, lon) in LOCATIONS.items():
        cache_path = RAW / f"weather_{location_id}.csv"
        source = None

        if cache_is_usable(cache_path):
            weather = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            source = weather["source"].dropna().iloc[0] if "source" in weather and weather["source"].notna().any() else "cached_unknown"
            print(f"[cache] {location_id}")
        else:
            print(f"[fetch] {location_id}")
            weather = fetch_power(lat, lon)
            source = "nasa_power"
            if weather is None:
                print(f"  NASA POWER unavailable for {location_id}; trying Open-Meteo.")
                weather = fetch_open_meteo(lat, lon)
                source = "open_meteo"
            weather["source"] = source
            weather.to_csv(cache_path, index_label="date")

        weather = weather.copy()
        weather.index = pd.to_datetime(weather.index)
        weather.index.name = "date"
        weather["location_id"] = location_id
        weather["source"] = source
        frames.append(weather.reset_index())

    result = pd.concat(frames, ignore_index=True)
    result = result.drop_duplicates(["location_id", "date"]).sort_values(["location_id", "date"])
    required = ["date", "location_id", "temp_mean", "temp_max", "temp_min", "precip_mm"]
    missing = [column for column in required if column not in result]
    if missing:
        raise ValueError(f"Weather output missing required columns: {missing}")
    result.to_csv(PROC / "weather_daily.csv", index=False)
    print(result.groupby(["location_id", "source"])[["temp_mean", "precip_mm"]].agg(["count", "mean"]).round(2))
    print(f"Saved {len(result):,} rows -> {PROC / 'weather_daily.csv'}")


if __name__ == "__main__":
    main()
