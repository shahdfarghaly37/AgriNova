"""Train and evaluate yield regressors on the 247K source dataset (v2).

Fixes vs v1:
- Categorical columns are detected with is_numeric_dtype, so they work with
  pandas 3 (dtype "str") as well as older pandas ("object"). In v1 this
  silently dropped crop_type, soil_type, season, etc.
- 5-fold cross validation on the train split plus a held-out test set.
- HistGradientBoosting added and compared against Ridge and Random Forest.

The source dataset is synthetic/unverified. Metrics describe fit to this
dataset only, not accuracy on real Egyptian farms.
"""
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_validate, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from config import PROC

TARGET = "crop_yield_tons"
SEED = 42


def split_columns(df):
    cats = [c for c in df.columns if c != TARGET and not pd.api.types.is_numeric_dtype(df[c])]
    nums = [c for c in df.columns if c != TARGET and c not in cats]
    return cats, nums


def linear_pre(cats, nums):
    return ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]), nums),
        ("cat", OneHotEncoder(handle_unknown="ignore"), cats),
    ])


def tree_pre(cats, nums):
    # Ordinal encoding keeps trees fast. Unknown categories become -1 -> NaN-like.
    return ColumnTransformer([
        ("num", "passthrough", nums),
        ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=np.nan), cats),
    ])


def score(y_true, y_pred):
    return {
        "r2": round(float(r2_score(y_true, y_pred)), 4),
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
    }


def main():
    path = PROC / "agri_247k_clean.csv"
    if not path.exists():
        raise FileNotFoundError("Run 02_clean_and_merge.py first.")
    df = pd.read_csv(path)
    df[TARGET] = pd.to_numeric(df[TARGET], errors="coerce")
    df = df.dropna(subset=[TARGET]).reset_index(drop=True)

    cats, nums = split_columns(df)
    print("Categorical:", cats)
    print("Numeric:", nums)
    X, y = df[cats + nums], df[TARGET]
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=SEED)

    cat_idx = list(range(len(nums), len(nums) + len(cats)))
    models = {
        "ridge_baseline": Pipeline([("pre", linear_pre(cats, nums)), ("m", Ridge(alpha=1.0))]),
        "random_forest": Pipeline([("pre", tree_pre(cats, nums)), ("imp", SimpleImputer(strategy="median")),
            ("m", RandomForestRegressor(n_estimators=100, max_depth=18, min_samples_leaf=5,
                                        max_features=0.8, max_samples=0.8, n_jobs=-1, random_state=SEED))]),
        "hist_gradient_boosting": Pipeline([("pre", tree_pre(cats, nums)),
            ("m", HistGradientBoostingRegressor(max_iter=400, learning_rate=0.08, max_leaf_nodes=63,
                                                categorical_features=cat_idx, random_state=SEED))]),
    }

    cv = KFold(n_splits=5, shuffle=True, random_state=SEED)
    results, fitted = {}, {}
    for name, model in models.items():
        print(f"\n== {name}: 5-fold CV ==")
        # CV runs on a 50K subsample of the train split to keep runtime reasonable;
        # the final fit and the test metrics use the full train/test split.
        cv_idx = Xtr.sample(50000, random_state=SEED).index
        cvr = cross_validate(model, Xtr.loc[cv_idx], ytr.loc[cv_idx], cv=cv, n_jobs=1,
                             scoring=["r2", "neg_mean_absolute_error"])
        model.fit(Xtr, ytr)
        test = score(yte, model.predict(Xte))
        results[name] = {
            "cv_r2_mean": round(float(cvr["test_r2"].mean()), 4),
            "cv_r2_std": round(float(cvr["test_r2"].std()), 4),
            "cv_mae_mean": round(float(-cvr["test_neg_mean_absolute_error"].mean()), 4),
            "test": test,
        }
        fitted[name] = model
        print(results[name])

    selected = max(results, key=lambda k: results[k]["cv_r2_mean"])
    model = fitted[selected]
    joblib.dump(model, PROC / "yield_model.joblib")

    # Per-crop quality on the held-out test set.
    pred = model.predict(Xte)
    per_crop = {}
    for crop, idx in Xte.groupby("crop_type").groups.items():
        per_crop[str(crop)] = score(yte.loc[idx], pd.Series(pred, index=Xte.index).loc[idx])

    # Permutation importance on a test sample (original columns, not one-hot).
    sample = Xte.sample(5000, random_state=SEED)
    pi = permutation_importance(model, sample, yte.loc[sample.index], n_repeats=5,
                                random_state=SEED, scoring="r2", n_jobs=1)
    fi = pd.DataFrame({"feature": sample.columns, "importance": pi.importances_mean,
                       "std": pi.importances_std}).sort_values("importance", ascending=False)
    fi.to_csv(PROC / "feature_importance.csv", index=False)

    meta = {
        "selected_model": selected,
        "target": TARGET,
        "categorical_features": cats,
        "numeric_features": nums,
        "feature_order": cats + nums,
        "training_rows": int(len(Xtr)),
        "test_rows": int(len(Xte)),
        "crop_types_seen": sorted(df["crop_type"].astype(str).unique()),
        "categories": {c: sorted(df[c].dropna().astype(str).unique()) for c in cats},
        "numeric_ranges": {c: [float(df[c].quantile(0.01)), float(df[c].quantile(0.99)),
                               float(df[c].median())] for c in nums},
        "models": results,
        "per_crop_test": per_crop,
        "data_warning": ("Source dataset is synthetic/unverified. Metrics measure fit to this "
                         "dataset only, not accuracy on real Egyptian farms."),
        "scenario_predictions": ("Experimental. Only avg_temp_c may be filled from NASA data; "
                                 "rainfall, humidity and other mismatched-definition features "
                                 "stay at dataset medians. See 09_engine.py."),
    }
    (PROC / "metrics.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("\nSelected:", selected)
    print(fi.to_string(index=False))
    print("Per crop:", json.dumps(per_crop, indent=1))


if __name__ == "__main__":
    main()
