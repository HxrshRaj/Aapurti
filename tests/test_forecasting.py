import numpy as np
import pandas as pd
import pytest

from aapurti.forecasting import metrics
from aapurti.forecasting.backtest import make_origins, run_forecasts, score, select_winners
from aapurti.forecasting.models import (build_gbm_frame, gbm_forecast, holt_winters, moving_average, naive,
                                        seasonal_naive)


def test_metrics_known_values():
    a, f = [100, 200, 0, 100], [110, 180, 10, 100]
    assert metrics.wape(a, f) == pytest.approx(40 / 400)
    assert metrics.rmse(a, f) == pytest.approx(np.sqrt((100 + 400 + 100 + 0) / 4))
    assert metrics.mape(a, f) == pytest.approx(np.mean([0.1, 0.1, 0.0]))     # zero-actual day excluded
    assert metrics.bias(a, f) == pytest.approx(0.0)
    assert metrics.wape([1, np.nan], [2, 5]) == pytest.approx(1.0)           # NaN actuals ignored


def test_baselines():
    y = np.arange(1, 29, dtype=float)
    assert list(naive(y, 3)) == [28, 28, 28]
    assert list(seasonal_naive(y, 9)) == [22, 23, 24, 25, 26, 27, 28, 22, 23]
    assert list(moving_average(y, 2)) == [14.5, 14.5]


def test_holt_winters_learns_weekly_pattern():
    rng = np.random.default_rng(0)
    base = np.tile([10, 12, 11, 10, 9, 4, 3], 40).astype(float) + rng.normal(0, 0.2, 280)
    fc = holt_winters(base, 14)
    truth = np.tile([10, 12, 11, 10, 9, 4, 3], 2)
    assert np.abs(fc - truth).mean() < 1.0 and (fc >= 0).all()


def _panel(n_days=520, n_series=3, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days)
    out = []
    for s in range(n_series):
        dow = np.array([1.2, 1.2, 1.1, 1.0, 1.0, 0.6, 0.5])[dates.dayofweek]
        promo = (rng.random(n_days) < 0.05).astype(int)
        units = rng.poisson(50 * (s + 1) * dow * (1 + 0.5 * promo)).astype(float)
        out.append(pd.DataFrame({"date": dates, "series": f"P|S{s}", "plant_id": "P", "sku_id": f"S{s}",
                                 "volume_class": "A", "units": units, "promo_flag": promo}))
    return pd.concat(out, ignore_index=True)


def test_origins_end_at_last_date():
    o = make_origins(pd.Timestamp("2025-12-31"), 28, 3)
    assert o[-1] + pd.Timedelta(days=28) == pd.Timestamp("2025-12-31") and len(o) == 3 and o == sorted(o)


def test_no_leakage_future_actuals_do_not_change_forecast():
    panel = _panel()
    origin = pd.Timestamp("2025-05-01")
    base = run_forecasts(panel, [origin], 28)
    tampered = panel.copy()
    tampered.loc[tampered["date"] > origin, "units"] = 99999.0
    again = run_forecasts(tampered, [origin], 28)
    merged = base.merge(again, on=["origin", "series", "model", "date"], suffixes=("", "_t"))
    assert len(merged) == len(base) > 0
    np.testing.assert_allclose(merged["forecast"], merged["forecast_t"], rtol=1e-9,
                               err_msg="forecast used post-origin data")


def test_gbm_features_are_lagged_by_horizon():
    panel = _panel(n_series=1)
    fr = build_gbm_frame(panel, 28).reset_index(drop=True)
    i = 400
    assert fr.loc[i, "lag_28"] == panel.loc[i - 28, "units"]
    assert fr.loc[i, "roll7"] == pytest.approx(panel.loc[i - 28 - 6: i - 28, "units"].mean())
    pred = gbm_forecast(fr, pd.Timestamp("2025-05-01"), 28)
    assert len(pred) == 28 and (pred["forecast"] >= 0).all()


def test_scoring_and_selection_find_better_model():
    panel = _panel()
    preds = run_forecasts(panel, make_origins(pd.Timestamp("2025-05-15"), 28, 2), 28)
    res = score(preds, panel)
    assert {"naive", "seasonal_naive", "moving_average", "holt_winters", "gradient_boosting"} <= set(res["model"])
    assert {"wape", "mape", "rmse", "pct_series_worse_than_naive", "pct_series_worse_than_best_baseline"} <= set(res.columns)
    w = select_winners(res)
    assert w.loc[0, "winner"] != "naive"      # weekly seasonality: a flat last value is never best
    a = res[res["volume_class"] == "A"].set_index("model")["wape"]
    assert a["seasonal_naive"] < a["naive"]


def test_mini_env_forecast_outputs(mini_env):
    fva = pd.read_parquet(mini_env["lake"] / "gold" / "forecast_vs_actual")
    assert fva["is_future"].any() and (~fva["is_future"]).any()
    assert fva.loc[fva["is_future"], "actual"].isna().all() and fva.loc[~fva["is_future"], "actual"].notna().all()
    assert (fva["forecast"] >= 0).all()
