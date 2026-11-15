"""Crop classification on the Crop Recommendation dataset (22 crops, 2200 rows).

Purpose: a supporting 'which crop does this soil/climate profile resemble' model.
Not used inside the ranking score because it needs N, P, K and rainfall inputs
that a GPS-only farmer does not have, and its rainfall unit differs from NASA.
"""
import json
import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from config import F_CROP_REC, PROC

df = pd.read_csv(F_CROP_REC)
X, y = df.drop(columns="label"), df["label"]
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)
cv = StratifiedKFold(5, shuffle=True, random_state=42)
models = {
    "logistic_regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)),
    "random_forest": RandomForestClassifier(n_estimators=300, random_state=42, n_jobs=-1),
}
res = {}
for n, m in models.items():
    cvs = cross_val_score(m, Xtr, ytr, cv=cv, scoring="accuracy")
    m.fit(Xtr, ytr)
    p = m.predict(Xte)
    res[n] = dict(cv_acc=round(float(cvs.mean()), 4), cv_std=round(float(cvs.std()), 4),
                  test_acc=round(float(accuracy_score(yte, p)), 4),
                  test_macro_f1=round(float(f1_score(yte, p, average="macro")), 4))
    print(n, res[n])
best = max(res, key=lambda k: res[k]["cv_acc"])
joblib.dump(models[best], PROC / "crop_classifier.joblib")
(PROC / "classifier_metrics.json").write_text(json.dumps(dict(
    selected=best, features=list(X.columns), classes=sorted(y.unique()), models=res,
    warning=("Crop Recommendation is a clean, near-separable Kaggle dataset. High accuracy "
             "shows the profiles are distinct, not that the model works on real Egyptian farms."),
), indent=2), encoding="utf-8")
print("Selected:", best)
