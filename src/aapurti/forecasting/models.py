"""Forecasting models. Per-series statistical models take a 1-D training array and return h forecasts."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from ..config import SEASONAL_PERIOD

BASELINES = ["naive", "seasonal_naive", "moving_average"]
MODELS = BASELINES + ["holt_winters", "gradient_boosting"]


def naive(train: np.ndarray, h: int) -> np.ndarray:
    return np.repeat(train[-1], h).astype(float)


def seasonal_naive(train: np.ndarray, h: int, m: int = SEASONAL_PERIOD) -> np.ndarray:
    last = train[-m:]
    return np.array([last[i % m] for i in range(h)], dtype=float)


def moving_average(train: np.ndarray, h: int, window: int = 28) -> np.ndarray:
    return np.repeat(train[-window:].mean(), h).astype(float)


def holt_winters(train: np.ndarray, h: int, m: int = SEASONAL_PERIOD, history: int = 364) -> np.ndarray:
    """Damped additive trend + additive weekly seasonality (statsmodels). Falls back to seasonal naive."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    y = np.asarray(train[-history:], dtype=float)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ExponentialSmoothing(y, trend="add", damped_trend=True, seasonal="add", seasonal_periods=m,
                                       initialization_method="estimated").fit()
            fc = np.asarray(fit.forecast(h), dtype=float)
        if not np.all(np.isfinite(fc)):
            raise ValueError("non-finite forecast")
        return np.clip(fc, 0, None)
    except Exception:
        return seasonal_naive(train, h, m)


STAT_MODELS = {"naive": naive, "seasonal_naive": seasonal_naive, "moving_average": moving_average,
               "holt_winters": holt_winters}

LAGS = (28, 35, 42, 364)
FEATURES = ["lag_28", "lag_35", "lag_42", "lag_364", "roll7", "roll28", "dow", "dom", "month",
            "doy_sin", "doy_cos", "promo", "log_scale", "series_code"]


def build_gbm_frame(panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """panel: date, series, units (NaN for future), promo_flag. All demand-derived features are
    shifted by >= `horizon` days so a forecast made at origin o only uses data <= o (no leakage)."""
    df = panel.sort_values(["series", "date"]).copy()
    g = df.groupby("series")["units"]
    for L in LAGS:
        df[f"lag_{L}"] = g.shift(L)
    shifted = g.shift(horizon)
    df["roll7"] = shifted.groupby(df["series"]).transform(lambda s: s.rolling(7, min_periods=7).mean())
    df["roll28"] = shifted.groupby(df["series"]).transform(lambda s: s.rolling(28, min_periods=28).mean())
    d = df["date"]
    df["dow"] = d.dt.dayofweek
    df["dom"] = d.dt.day
    df["month"] = d.dt.month
    df["doy_sin"] = np.sin(2 * np.pi * d.dt.dayofyear / 365.25)
    df["doy_cos"] = np.cos(2 * np.pi * d.dt.dayofyear / 365.25)
    df["promo"] = df["promo_flag"]
    df["series_code"] = df["series"].astype("category").cat.codes
    return df


def gbm_forecast(frame: pd.DataFrame, origin: pd.Timestamp, horizon: int) -> pd.DataFrame:
    """Global gradient-boosting model trained on rows <= origin; predicts (origin, origin+horizon]."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    train = frame[(frame["date"] <= origin) & frame["units"].notna()].copy()
    scale = train[train["date"] > origin - pd.Timedelta(days=365)].groupby("series")["units"].mean().clip(lower=1.0)
    frame = frame.assign(scale=frame["series"].map(scale))
    frame["log_scale"] = np.log(frame["scale"])
    lag_cols = [f"lag_{L}" for L in LAGS] + ["roll7", "roll28"]
    for c in lag_cols:
        frame[c] = frame[c] / frame["scale"]
    tr = frame[(frame["date"] <= origin) & frame["units"].notna()].dropna(subset=lag_cols)
    model = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.06, max_depth=6, random_state=0)
    model.fit(tr[FEATURES], tr["units"] / tr["scale"])
    te = frame[(frame["date"] > origin) & (frame["date"] <= origin + pd.Timedelta(days=horizon))].copy()
    te = te.dropna(subset=lag_cols)
    te["forecast"] = np.clip(model.predict(te[FEATURES]) * te["scale"], 0, None)
    return te[["series", "date", "forecast"]]
