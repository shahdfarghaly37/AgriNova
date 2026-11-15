"""Shared configuration for Farmer Imposters."""
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
MASTER = PROC / "master"

for folder in (RAW, PROC, MASTER):
    folder.mkdir(parents=True, exist_ok=True)

# Match the exact filenames supplied in final.zip.
F_CROP_REC = RAW / "crop_recommendation.csv"
F_AGRI_247K = RAW / "crop_yield_data.csv"
F_PESTICIDES = RAW / "pesticides.csv"
F_RAINFALL = RAW / "rainfall.csv"
F_TEMP = RAW / "temp.csv"
F_YIELD_FAO = RAW / "yield.csv"

LOCATIONS = {
    "alexandria": (31.20, 29.92),
    "beheira": (31.03, 30.47),
    "gharbia": (30.79, 31.00),
    "sharqia": (30.59, 31.50),
    "fayoum": (29.31, 30.84),
    "minya": (28.11, 30.75),
    "assiut": (27.18, 31.18),
    "aswan": (24.09, 32.90),
    "matrouh": (31.35, 27.24),
    "new_valley": (25.45, 30.55),
}

START_YEAR = 1991
END_DATE = date.today() - timedelta(days=7)
BASELINE_YEARS = (1991, 2000)
RECENT_YEARS = 5

# Generic prototype thresholds, not crop-specific agronomic recommendations.
HEAT_DAY_C = 35
GDD_BASE_C = 10

# Extra governorates added with add_governorate.py (real NASA POWER history).
import json as _json
_extra = ROOT / "extra_locations.json"
if _extra.exists():
    LOCATIONS.update({k: tuple(v) for k, v in _json.loads(_extra.read_text(encoding="utf-8")).items()})
