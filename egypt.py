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

# CORE = crops with a yield estimate (yield model). FULL = every crop with the full analysis
# (climate, heat, water, pH, soil, season); potato and sorghum have it but no yield model.
# Extended crops only have climate + pH data, so we keep just the ones that make sense for Egypt.
CROPS_AR = {
    "wheat": "قمح", "maize": "ذرة", "rice": "أرز", "cotton": "قطن", "soybean": "فول صويا",
    "potato": "بطاطس", "sorghum": "ذرة رفيعة",
    "banana": "موز", "chickpea": "حمص", "grapes": "عنب", "lentil": "عدس", "mango": "مانجو",
    "muskmelon": "شمام", "orange": "برتقال", "papaya": "بابايا", "pomegranate": "رمان",
    "watermelon": "بطيخ",
}
CORE = ["wheat", "maize", "rice", "cotton", "soybean"]
FULL = CORE + ["potato", "sorghum"]
EXTENDED_OK = [c for c in CROPS_AR if c not in FULL]

# Accept Arabic or English input for the "ask about a crop" box.
CROP_ALIASES = {ar: en for en, ar in CROPS_AR.items()}
CROP_ALIASES.update({"درة": "maize", "ذره": "maize", "رز": "rice", "صويا": "soybean",
                     "فول الصويا": "soybean", "بطيخ": "watermelon", "كنتالوب": "muskmelon",
                     "ذره رفيعة": "sorghum", "ذرة رفيعه": "sorghum", "ذره رفيعه": "sorghum"})

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


# ================= English + language switch =================================
GOV_EN = {"alexandria": "Alexandria", "beheira": "Beheira", "gharbia": "Gharbia", "sharqia": "Sharqia",
          "fayoum": "Fayoum", "minya": "Minya", "assiut": "Assiut", "aswan": "Aswan", "matrouh": "Matrouh",
          "new_valley": "New Valley", "cairo": "Cairo", "giza": "Giza", "dakahlia": "Dakahlia",
          "kafr_elsheikh": "Kafr El Sheikh", "menoufia": "Menoufia", "qalyubia": "Qalyubia",
          "damietta": "Damietta", "port_said": "Port Said", "ismailia": "Ismailia", "suez": "Suez",
          "north_sinai": "North Sinai", "south_sinai": "South Sinai", "beni_suef": "Beni Suef",
          "sohag": "Sohag", "qena": "Qena", "luxor": "Luxor", "red_sea": "Red Sea"}
CROPS_EN = {"wheat": "Wheat", "maize": "Maize", "rice": "Rice", "cotton": "Cotton", "soybean": "Soybean",
            "potato": "Potato", "sorghum": "Sorghum",
            "banana": "Banana", "chickpea": "Chickpea", "grapes": "Grapes", "lentil": "Lentil",
            "mango": "Mango", "muskmelon": "Cantaloupe", "orange": "Orange", "papaya": "Papaya",
            "pomegranate": "Pomegranate", "watermelon": "Watermelon"}
TXT = {
    "ar": dict(
        gov={k: v[0] for k, v in GOVERNORATES.items()}, crop=CROPS_AR, months=MONTHS_AR, seasons=SEASONS_AR,
        verdict=VERDICT_AR, yield_=YIELD_AR, soil=SOIL_AR, water=WATER_AR,
        note="الإنتاجية تقدير تجريبي مش توقع مؤكد", no_gov="المحافظة مش موجودة",
        no_crop="المحصول ده لسه مش متاح", bad_date="التاريخ غلط (YYYY-MM-DD)",
        rough="تقدير مبدئي حسب الجو بس",
        no_yield="توقّع الإنتاجية لسه مش متاح للمحصول ده (بيتوسّع مع بيانات FAO)",
        summ=dict(hi_tire="إنتاجه عالي بس بيجهد الأرض", hi_gentle="إنتاجه عالي وكويس للأرض", hi="إنتاجه عالي",
                  lo_gentle="كويس للأرض بس إنتاجه أقل", lo_tire="إنتاجه ضعيف وبيجهد الأرض", lo="إنتاجه ضعيف",
                  mid_tire="إنتاجه متوسط وبيجهد الأرض", mid_gentle="إنتاجه متوسط وكويس للأرض", mid="إنتاجه متوسط"),
        r=dict(weather="الجو دلوقتي مش مناسب له", heat="الحر هيضره وقت الإزهار", water_short="محتاج مية أكتر من اللي متاحة",
               water_high="بيشرب مية كتير", season="ده مش ميعاد زراعته", tiring="بيجهد الأرض",
               ok="الجو والميعاد والمية مناسبين", w_ok="الجو مناسب له", rough="تقدير مبدئي (الجو بس)")),
    "en": dict(
        gov=GOV_EN, crop=CROPS_EN, season=None,
        months=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        seasons={"winter": "Winter", "spring": "Spring", "summer": "Summer", "autumn": "Autumn"},
        verdict={"yes": "Good to grow", "maybe": "Grow with care", "no": "Not now"},
        yield_={"high": "High yield", "medium": "Medium yield", "low": "Low yield"},
        soil={"gentle": "Good for soil", "normal": "Normal on soil", "tiring": "Tiring on soil"},
        water={"low": "Low water", "medium": "Medium water", "high": "High water"},
        note="Yield is an experimental estimate, not a guaranteed forecast", no_gov="Governorate not found",
        no_crop="This crop is not available yet", bad_date="Bad date (YYYY-MM-DD)",
        rough="Rough estimate from weather only",
        no_yield="Yield forecast not available for this crop yet (expanding with FAO data)",
        summ=dict(hi_tire="High yield, but tiring on the soil", hi_gentle="High yield and good for the soil",
                  hi="High yield", lo_gentle="Good for the soil, lower yield", lo_tire="Low yield and tiring on the soil",
                  lo="Low yield", mid_tire="Medium yield, tiring on the soil",
                  mid_gentle="Medium yield, good for the soil", mid="Medium yield"),
        r=dict(weather="The weather is not right for it now", heat="Heat will hurt it at flowering",
               water_short="Needs more water than is available", water_high="Uses a lot of water",
               season="Not its planting season", tiring="Tiring on the soil",
               ok="Weather, timing and water all fit", w_ok="Weather suits it", rough="Rough estimate (weather only)")),
}
del TXT["en"]["season"]


def reasons(r, T):
    m, out = T["r"], []
    if r.get("scope") == "full":
        if r.get("temp_fit", 100) < 50: out.append(m["weather"])
        if r.get("heat_stress_risk") == "high": out.append(m["heat"])
        if not r.get("water_feasible", True): out.append(m["water_short"])
        elif r.get("water_demand_class") == "high": out.append(m["water_high"])
        if not r.get("in_calendar_window", True): out.append(m["season"])
        if r.get("soil_impact_score", 100) < 45: out.append(m["tiring"])
        if not out: out.append(m["ok"])
    else:
        out.append(m["weather"] if r.get("temp_fit", 100) < 50 else m["w_ok"])
        out.append(m["rough"])
    return out[:3]


def summary(y, so, T):
    s = T["summ"]
    key = ("hi_tire" if y == "high" and so == "tiring" else "hi_gentle" if y == "high" and so == "gentle"
           else "hi" if y == "high" else "lo_gentle" if so == "gentle" and y == "low"
           else "lo_tire" if y == "low" and so == "tiring" else "lo" if y == "low"
           else "mid_tire" if so == "tiring" else "mid_gentle" if so == "gentle" else "mid")
    return s[key]
