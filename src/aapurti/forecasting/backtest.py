"""Rolling-origin backtest, model selection per SKU volume class, and final forecasts."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import HORIZON, N_ORIGINS
from . import metrics
from .models import BASELINES, MODELS, STAT_MODELS, build_gbm_frame, gbm_forecast


def prepare_panel(daily: pd.DataFrame) -> pd.DataFrame:
    """daily: demand_date, plant_id, sku_id, volume_class, units, promo_flag (gold.daily_demand).
    Reindexes every series to a full calendar. Days removed by silver quarantine are filled with the
    value 7 days earlier (0 if unavailable) so the series stay regular."""
    daily = daily.assign(series=daily["plant_id"] + "|" + daily["sku_id"], date=pd.to_datetime(daily["demand_date"]))
    full = pd.date_range(daily["date"].min(), daily["date"].max(), freq="D")
    out = []
    for key, g in daily.groupby("series"):
        g = g.set_index("date").reindex(full)
        units = g["units"].astype(float)
        weekly = units.shift(7)
        units = units.fillna(weekly).fillna(0.0)
        out.append(pd.DataFrame({
            "date": full, "series": key, "plant_id": key.split("|")[0], "sku_id": key.split("|")[1],
            "volume_class": daily.loc[daily["series"] == key, "volume_class"].iloc[0],
            "units": units.values, "promo_flag": g["promo_flag"].fillna(0).astype(int).values}))
    return pd.concat(out, ignore_index=True)


def make_origins(last_date: pd.Timestamp, horizon: int = HORIZON, n: int = N_ORIGINS) -> list[pd.Timestamp]:
    """Backtest origins, oldest first: last_date - horizon*k, k = n..1."""
    return [last_date - pd.Timedelta(days=horizon * k) for k in range(n, 0, -1)]


def run_forecasts(panel: pd.DataFrame, origins: list[pd.Timestamp], horizon: int = HORIZON,
                  models: list[str] | None = None) -> pd.DataFrame:
    """Forecast `horizon` days after every origin with every model.
    Panel may contain future rows with NaN units (used for the production forecast)."""
    models = models or MODELS
    series_data = {k: g.sort_values("date") for k, g in panel.groupby("series")}
    gbm_frame = build_gbm_frame(panel, horizon) if "gradient_boosting" in models else None
    rows = []
    for origin in origins:
        for key, g in series_data.items():
            train = g.loc[g["date"] <= origin, "units"].to_numpy()
            future = pd.date_range(origin + pd.Timedelta(days=1), periods=horizon, freq="D")
            actual = g.set_index("date")["units"].reindex(future).to_numpy()
            for m in models:
                if m == "gradient_boosting":
                    continue
                fc = STAT_MODELS[m](train, horizon)
                rows.append(pd.DataFrame({"origin": origin, "series": key, "model": m, "date": future,
                                          "actual": actual, "forecast": fc}))
        if gbm_frame is not None:
            pred = gbm_forecast(gbm_frame, origin, horizon)
            act = panel.set_index(["series", "date"])["units"]
            pred["actual"] = act.reindex(pd.MultiIndex.from_frame(pred[["series", "date"]])).to_numpy()
            pred["origin"] = origin
            pred["model"] = "gradient_boosting"
            rows.append(pred[["origin", "series", "model", "date", "actual", "forecast"]])
    return pd.concat(rows, ignore_index=True)


def score(preds: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """Metrics per (volume_class, model), pooled over all origins and series, plus loss vs naive columns."""
    cls = panel.drop_duplicates("series").set_index("series")["volume_class"]
    p = preds.dropna(subset=["actual"]).assign(volume_class=lambda d: d["series"].map(cls))
    rows = []
    for (vc, m), g in list(p.groupby(["volume_class", "model"])) + list(p.assign(volume_class="ALL").groupby(["volume_class", "model"])):
        rows.append({"volume_class": vc, "model": m, "n_points": len(g),
                     "mape": metrics.mape(g["actual"], g["forecast"]), "wape": metrics.wape(g["actual"], g["forecast"]),
                     "rmse": metrics.rmse(g["actual"], g["forecast"]), "bias": metrics.bias(g["actual"], g["forecast"])})
    res = pd.DataFrame(rows)
    naive = res[res["model"] == "naive"].set_index("volume_class")["wape"]
    res["wape_vs_naive"] = res["wape"] - res["volume_class"].map(naive)

    # share of series on which each model is worse than naive (series-level WAPE)
    sw = (p.groupby(["series", "model"]).apply(lambda g: metrics.wape(g["actual"], g["forecast"]), include_groups=False)
          .unstack("model"))
    loses = {}
    for m in sw.columns:
        loses[m] = (sw[m] > sw["naive"]).groupby(cls.reindex(sw.index)).mean().to_dict()
        loses[m]["ALL"] = float((sw[m] > sw["naive"]).mean())
    res["pct_series_worse_than_naive"] = [loses[m][vc] for vc, m in zip(res["volume_class"], res["model"])]

    # same, against the best of the three baselines on each series (a much harder bar than naive alone)
    best_base = sw[[b for b in BASELINES if b in sw.columns]].min(axis=1)
    worse = {}
    for m in sw.columns:
        w = sw[m] > best_base
        worse[m] = w.groupby(cls.reindex(sw.index)).mean().to_dict()
        worse[m]["ALL"] = float(w.mean())
    res["pct_series_worse_than_best_baseline"] = [
        np.nan if m in BASELINES else worse[m][vc] for vc, m in zip(res["volume_class"], res["model"])]
    return res.sort_values(["volume_class", "wape"]).reset_index(drop=True)


def select_winners(results: pd.DataFrame) -> pd.DataFrame:
    r = results[results["volume_class"] != "ALL"]
    best = r.loc[r.groupby("volume_class")["wape"].idxmin()][["volume_class", "model", "wape", "mape", "rmse"]]
    base = (r[r["model"].isin(BASELINES)].groupby("volume_class")["wape"].min()).rename("best_baseline_wape")
    best = best.merge(base, on="volume_class").rename(columns={"model": "winner"})
    best["beats_best_baseline"] = best["wape"] < best["best_baseline_wape"]
    return best.reset_index(drop=True)


def final_forecasts(panel: pd.DataFrame, preds_bt: pd.DataFrame, winners: pd.DataFrame,
                    horizon: int = HORIZON) -> pd.DataFrame:
    """Forecast vs actual for the last backtest window, plus a future window beyond the data.
    Uses each volume class's winning model. Promo flag in the future window is assumed 0 (no promo plan)."""
    last = panel["date"].max()
    cls = panel.drop_duplicates("series").set_index("series")["volume_class"]
    win = winners.set_index("volume_class")["winner"]

    hold = preds_bt[preds_bt["origin"] == last - pd.Timedelta(days=horizon)].copy()
    hold = hold[hold["model"] == hold["series"].map(cls).map(win)]

    # production forecast: extend panel by `horizon` empty days, forecast from origin = last
    fut_dates = pd.date_range(last + pd.Timedelta(days=1), periods=horizon, freq="D")
    ext = pd.concat([panel] + [pd.DataFrame({"date": fut_dates, "series": k, "plant_id": k.split("|")[0],
                                             "sku_id": k.split("|")[1], "volume_class": cls[k], "units": np.nan,
                                             "promo_flag": 0}) for k in cls.index], ignore_index=True)
    fut = run_forecasts(ext, [last], horizon, models=sorted(set(win.values)))
    fut = fut[fut["model"] == fut["series"].map(cls).map(win)]

    hold["is_future"] = False
    fut["is_future"] = True
    out = pd.concat([hold, fut], ignore_index=True)
    out["plant_id"] = out["series"].str.split("|").str[0]
    out["sku_id"] = out["series"].str.split("|").str[1]
    out["volume_class"] = out["series"].map(cls)
    return out[["date", "plant_id", "sku_id", "volume_class", "model", "actual", "forecast", "is_future"]]
