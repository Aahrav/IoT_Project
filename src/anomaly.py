from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler


DEFAULT_FEATURE_COLS = ["temperature_c", "vibration_rms", "current_a"]


@dataclass(frozen=True)
class AnomalyConfig:
    contamination: float = 0.03
    random_state: int = 7


def fit_score_isolation_forest(df: pd.DataFrame, cfg: AnomalyConfig, *, feature_cols: list[str] | None = None) -> pd.DataFrame:
    """
    Returns df with:
      - anomaly_score (higher = more anomalous)
      - anomaly_flag (1 = anomaly)
      - contrib_* simple per-feature contributions (proxy explanation)

    Notes:
    - IsolationForest doesn't give true feature attributions; we provide a fast proxy:
      robust z-scores multiplied by anomaly_score, normalized per-row.
    """
    work = df.copy()

    feature_cols = feature_cols or DEFAULT_FEATURE_COLS
    X = work[feature_cols].to_numpy(dtype=float)
    scaler = RobustScaler()
    Xs = scaler.fit_transform(X)

    model = IsolationForest(
        n_estimators=250,
        contamination=cfg.contamination,
        random_state=cfg.random_state,
        n_jobs=-1,
    )
    model.fit(Xs)

    # decision_function: higher = more normal. We invert to get higher = more anomalous.
    normality = model.decision_function(Xs)
    anomaly_score = (normality.max() - normality).astype(float)

    pred = model.predict(Xs)  # -1 anomaly, 1 normal
    anomaly_flag = (pred == -1).astype(int)

    # Proxy explanation: robust z per feature, scaled by anomaly_score.
    med = np.median(X, axis=0)
    mad = np.median(np.abs(X - med), axis=0)
    mad = np.where(mad == 0, 1e-6, mad)
    z = (X - med) / mad
    z_abs = np.abs(z)
    row_sum = z_abs.sum(axis=1, keepdims=True)
    row_sum = np.where(row_sum == 0, 1.0, row_sum)
    weights = z_abs / row_sum
    contrib = weights * anomaly_score.reshape(-1, 1)

    work["anomaly_score"] = anomaly_score
    work["anomaly_flag"] = anomaly_flag
    for i, c in enumerate(feature_cols):
        work[f"contrib_{c}"] = contrib[:, i]

    return work

