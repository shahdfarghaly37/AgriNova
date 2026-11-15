
from pathlib import Path
import pandas as pd
import json

MASTER = Path("data/processed/master")
REPORT = Path("data/processed/master_quality_report.json")

FILES = {
    "training": MASTER / "master_training.csv",
    "location_crop": MASTER / "master_location_crop.csv",
    "weather_monthly": MASTER / "master_weather_monthly.csv",
    "dictionary": MASTER / "data_dictionary.csv",
}

report = {}

def inspect_file(name, path):
    print(f"\n{'=' * 60}")
    print(f"FILE: {name}")
    print("=" * 60)

    if not path.exists():
        print("ERROR: File not found!")
        return

    df = pd.read_csv(path, low_memory=False)

    info = {
        "rows": len(df),
        "columns_count": len(df.columns),
        "columns": list(df.columns),
        "duplicate_rows": int(df.duplicated().sum()),
        "missing_values": df.isna().sum().to_dict(),
        "missing_percentage": (
            (df.isna().mean() * 100).round(2).to_dict()
        ),
    }

    print("Shape:", df.shape)
    print("\nColumns:")
    print(df.columns.tolist())

    print("\nDuplicate rows:", info["duplicate_rows"])

    print("\nMissing values:")
    for col, count in info["missing_values"].items():
        if count:
            print(f"  {col}: {count} ({info['missing_percentage'][col]}%)")

    # Check target
    if "crop_yield_tons" in df.columns:
        target = pd.to_numeric(
            df["crop_yield_tons"], errors="coerce"
        )
        info["target"] = {
            "missing": int(target.isna().sum()),
            "min": float(target.min()) if target.notna().any() else None,
            "max": float(target.max()) if target.notna().any() else None,
            "mean": float(target.mean()) if target.notna().any() else None,
            "non_positive": int((target <= 0).sum()),
        }

        print("\nTarget statistics:")
        print(info["target"])

    # Crop distribution
    if "crop_type" in df.columns:
        info["crop_distribution"] = (
            df["crop_type"].value_counts(dropna=False).to_dict()
        )
        print("\nCrop distribution:")
        print(df["crop_type"].value_counts(dropna=False).to_string())

    # Potential duplicate keys
    candidate_keys = [
        ["location_id", "crop_type"],
        ["location_id", "date"],
        ["country", "year"],
    ]

    info["key_checks"] = {}

    for keys in candidate_keys:
        if all(k in df.columns for k in keys):
            duplicates = int(df.duplicated(keys).sum())
            info["key_checks"]["+".join(keys)] = duplicates
            print(f"\nDuplicate key {keys}: {duplicates}")

    report[name] = info


for name, path in FILES.items():
    inspect_file(name, path)

REPORT.write_text(
    json.dumps(report, indent=2, default=str),
    encoding="utf-8"
)

print("\n" + "=" * 60)
print("AUDIT FINISHED")
print("Report saved to:", REPORT)
print("=" * 60)
