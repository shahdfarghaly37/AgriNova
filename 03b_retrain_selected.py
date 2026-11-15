"""Quick re-save of the selected yield model with the local scikit-learn version.

Use this when 09_engine.py prints InconsistentVersionWarning. It retrains only the
HistGradientBoosting model selected by 03_train_model.py (same settings and split),
so it takes seconds, and overwrites yield_model.joblib. metrics.json is not changed.
"""
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import r2_score, mean_absolute_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from config import PROC

meta = json.loads((PROC / "metrics.json").read_text(encoding="utf-8"))
cats, nums = meta["categorical_features"], meta["numeric_features"]
df = pd.read_csv(PROC / "agri_247k_clean.csv")
df = df.dropna(subset=["crop_yield_tons"]).reset_index(drop=True)
X, y = df[cats + nums], df["crop_yield_tons"]
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42)
pre = ColumnTransformer([
    ("num", "passthrough", nums),
    ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=np.nan), cats),
])
model = Pipeline([("pre", pre), ("m", HistGradientBoostingRegressor(
    max_iter=400, learning_rate=0.08, max_leaf_nodes=63,
    categorical_features=list(range(len(nums), len(nums) + len(cats))), random_state=42))])
model.fit(Xtr, ytr)
p = model.predict(Xte)
print(f"Test R2 {r2_score(yte, p):.4f}  MAE {mean_absolute_error(yte, p):.4f}  (expected about 0.8403 / 1.3915)")
joblib.dump(model, PROC / "yield_model.joblib")
print("Saved yield_model.joblib")
