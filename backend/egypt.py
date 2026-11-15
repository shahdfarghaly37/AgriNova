"""Egypt reference data + Arabic wording for the farmer-facing API.

All user-visible Arabic text lives here, so the team can edit wording
without touching the logic in api.py.
"""

# id: (Arabic name, lat, lon)  - capital city coordinates.
# The first 10 ids match config.LOCATIONS (they have real NASA POWER history).
GOVERNORATES = {
    "alexandria": ("الإسكندرية", 31.20, 29.92),
    "beheira": ("البحيرة", 31.03, 30.47),
    "gharbia": ("الغربية", 30.79, 31.00),
    "sharqia": ("الشرقية", 30.59, 31.50),
    "fayoum": ("الفيوم", 29.31, 30.84),
    "minya": ("المنيا", 28.11, 30.75),
    "assiut": ("أسيوط", 27.18, 31.18),
    "aswan": ("أسوان", 24.09, 32.90),
    "matrouh": ("مطروح", 31.35, 27.24),
    "new_valley": ("الوادي الجديد", 25.45, 30.55),
    "cairo": ("القاهرة", 30.04, 31.24),
    "giza": ("الجيزة", 30.01, 31.21),
    "dakahlia": ("الدقهلية", 31.04, 31.38),
    "kafr_elsheikh": ("كفر الشيخ", 31.11, 30.94),
    "menoufia": ("المنوفية", 30.55, 31.01),
    "qalyubia": ("القليوبية", 30.47, 31.18),
    "damietta": ("دمياط", 31.42, 31.82),
    "port_said": ("بورسعيد", 31.27, 32.30),
    "ismailia": ("الإسماعيلية", 30.60, 32.27),
    "suez": ("السويس", 29.97, 32.55),
    "north_sinai": ("شمال سيناء", 31.13, 33.80),
    "south_sinai": ("جنوب سيناء", 28.24, 33.62),
    "beni_suef": ("بني سويف", 29.07, 31.10),
    "sohag": ("سوهاج", 26.56, 31.69),
    "qena": ("قنا", 26.16, 32.72),
    "luxor": ("الأقصر", 25.70, 32.64),
    "red_sea": ("البحر الأحمر", 27.26, 33.81),
}

# Core crops have full analysis. Extended crops only have climate + pH data,
# so we keep just the ones that make sense for Egyptian farms.
CROPS_AR = {
    "wheat": "قمح", "maize": "ذرة", "rice": "أرز", "cotton": "قطن", "soybean": "فول صويا",
    "banana": "موز", "chickpea": "حمص", "grapes": "عنب", "lentil": "عدس", "mango": "مانجو",
    "muskmelon": "شمام", "orange": "برتقال", "papaya": "بابايا", "pomegranate": "رمان",
    "watermelon": "بطيخ",
}
CORE = ["wheat", "maize", "rice", "cotton", "soybean"]
EXTENDED_OK = [c for c in CROPS_AR if c not in CORE]

# Accept Arabic or English input for the "ask about a crop" box.
CROP_ALIASES = {ar: en for en, ar in CROPS_AR.items()}
CROP_ALIASES.update({"درة": "maize", "ذره": "maize", "رز": "rice", "صويا": "soybean",
                     "فول الصويا": "soybean", "بطيخ": "watermelon", "كنتالوب": "muskmelon"})

MONTHS_AR = ["يناير", "فبراير", "مارس", "إبريل", "مايو", "يونيو",
             "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
SEASONS_AR = {"winter": "الشتاء", "spring": "الربيع", "summer": "الصيف", "autumn": "الخريف"}

VERDICT_AR = {"yes": "ينفع", "maybe": "ينفع بحذر", "no": "مش مناسب دلوقتي"}
YIELD_AR = {"high": "إنتاجه عالي", "medium": "إنتاجه متوسط", "low": "إنتاجه ضعيف"}
SOIL_AR = {"gentle": "كويس للأرض", "normal": "عادي على الأرض", "tiring": "بيجهد الأرض"}
WATER_AR = {"low": "مية قليلة", "medium": "مية متوسطة", "high": "مية كتير"}


def reasons_ar(r):
    """Short Arabic reasons from one engine row (dict). At most 3."""
    out = []
    if r.get("scope") == "full":
        if r.get("temp_fit", 100) < 50:
            out.append("الجو دلوقتي مش مناسب له")
        if r.get("heat_stress_risk") == "high":
            out.append("الحر هيضره وقت الإزهار")
        if not r.get("water_feasible", True):
            out.append("محتاج مية أكتر من اللي متاحة")
        elif r.get("water_demand_class") == "high":
            out.append("بيشرب مية كتير")
        if not r.get("in_calendar_window", True):
            out.append("ده مش ميعاد زراعته")
        if r.get("soil_impact_score", 100) < 45:
            out.append("بيجهد الأرض")
        if not out:
            out.append("الجو والميعاد والمية مناسبين")
    else:
        if r.get("temp_fit", 100) < 50:
            out.append("الجو دلوقتي مش مناسب له")
        else:
            out.append("الجو مناسب له")
        out.append("تقدير مبدئي (الجو بس)")
    return out[:3]
