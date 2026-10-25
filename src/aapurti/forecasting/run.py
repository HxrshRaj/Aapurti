"""Reads gold.daily_demand, backtests, selects winners, writes gold forecast tables. CLI entry point."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from .. import config
from .backtest import final_forecasts, make_origins, prepare_panel, run_forecasts, score, select_winners


def run_forecasting(lake_dir, horizon: int = config.HORIZON, n_origins: int = config.N_ORIGINS) -> dict:
    lake = Path(lake_dir)
    t0 = time.perf_counter()
    daily = pd.read_parquet(lake / "gold" / "daily_demand")
    panel = prepare_panel(daily)
    origins = make_origins(panel["date"].max(), horizon, n_origins)
    preds = run_forecasts(panel, origins, horizon)
    results = score(preds, panel)
    winners = select_winners(results)
    fva = final_forecasts(panel, preds, winners, horizon)

    out = lake / "gold"
    for name, df in {"backtest_results": results, "model_selection": winners, "forecast_vs_actual": fva}.items():
        d = out / name
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.parquet"):
            old.unlink()
        df.to_parquet(d / "part-0.parquet", index=False)
    # series-level backtest predictions (for audit), kept outside gold
    (lake / "audit").mkdir(exist_ok=True)
    preds.to_parquet(lake / "audit" / "backtest_predictions.parquet", index=False)
    return {"series": int(panel["series"].nunique()), "origins": [str(o.date()) for o in origins], "horizon": horizon,
            "seconds": round(time.perf_counter() - t0, 1), "winners": winners.to_dict("records")}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--lake", default=str(config.LAKE_DIR))
    a = p.parse_args()
    res = run_forecasting(a.lake)
    config.REPORTS_DIR.mkdir(exist_ok=True)
    (config.REPORTS_DIR / "forecast_run.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
