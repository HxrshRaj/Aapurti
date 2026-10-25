"""Forecast accuracy metrics. All take aligned arrays; rows with NaN actuals are ignored."""
from __future__ import annotations

import numpy as np


def _clean(actual, forecast):
    a = np.asarray(actual, dtype=float)
    f = np.asarray(forecast, dtype=float)
    m = ~(np.isnan(a) | np.isnan(f))
    return a[m], f[m]


def wape(actual, forecast) -> float:
    """Weighted APE = sum|a-f| / sum a. Robust to zeros; the headline metric here."""
    a, f = _clean(actual, forecast)
    return float(np.abs(a - f).sum() / a.sum()) if a.sum() > 0 else float("nan")


def mape(actual, forecast) -> float:
    """Mean APE over rows with actual > 0 (zero-demand days are excluded, not scored as 0 or inf)."""
    a, f = _clean(actual, forecast)
    m = a > 0
    return float(np.mean(np.abs(a[m] - f[m]) / a[m])) if m.any() else float("nan")


def rmse(actual, forecast) -> float:
    a, f = _clean(actual, forecast)
    return float(np.sqrt(np.mean((a - f) ** 2))) if len(a) else float("nan")


def bias(actual, forecast) -> float:
    """(sum f - sum a) / sum a; positive = over-forecast."""
    a, f = _clean(actual, forecast)
    return float((f.sum() - a.sum()) / a.sum()) if a.sum() > 0 else float("nan")
