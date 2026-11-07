"""On-demand ML forecast for one series, used by the async forecast-job API.

A small gradient-boosting regressor on lag and calendar features, fitted at request time on the series history
and rolled forward recursively. A seasonal-naive baseline is returned alongside so callers can see the lift.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

MIN_HISTORY = 60
LAGS = (1, 7, 14)


def _features(history: list[float], date: pd.Timestamp) -> list[float]:
    h = np.asarray(history, dtype=float)
    return [h[-1], h[-7], h[-14], h[-7:].mean(), h[-28:].mean(), date.dayofweek, date.month]


def forecast_series(dates: list[str], units: list[float], horizon: int = 14) -> dict:
    if not 1 <= horizon <= 90:
        raise ValueError("horizon must be between 1 and 90")
    if len(units) < MIN_HISTORY:
        raise ValueError(f"need at least {MIN_HISTORY} days of history, got {len(units)}")
    idx = pd.to_datetime(dates)
    y = np.asarray(units, dtype=float)
    X, t = [], []
    for i in range(28, len(y)):
        X.append(_features(list(y[:i]), idx[i]))
        t.append(y[i])
    model = GradientBoostingRegressor(n_estimators=120, max_depth=3, learning_rate=0.08, random_state=42)
    model.fit(np.asarray(X), np.asarray(t))
    hist, preds, out_dates = list(y), [], []
    d = idx[-1]
    for _ in range(horizon):
        d = d + pd.Timedelta(days=1)
        p = float(max(model.predict(np.asarray([_features(hist, d)]))[0], 0.0))
        preds.append(p); hist.append(p); out_dates.append(d.strftime("%Y-%m-%d"))
    seasonal = [float(y[-7 + (i % 7)]) for i in range(horizon)]
    return {"dates": out_dates, "forecast": [round(p, 2) for p in preds],
            "baseline_seasonal_naive": seasonal, "model": "gradient_boosting"}
