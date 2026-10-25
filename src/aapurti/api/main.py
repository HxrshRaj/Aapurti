"""FastAPI service over the gold tables in SQLite. No Spark at serve time (Spark runs in the batch step)."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .. import config
from ..excel import build_workbook

DB_ENV = "AAPURTI_DB"
FRONTEND_DIST = config.ROOT / "frontend" / "dist"


def db_path() -> Path:
    return Path(os.environ.get(DB_ENV, config.DB_PATH))


def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    p = db_path()
    if not p.exists():
        raise HTTPException(503, f"Serving database not found at {p}. Run scripts/run_all.py first.")
    con = sqlite3.connect(p)
    try:
        return pd.read_sql_query(sql, con, params=params)
    finally:
        con.close()


def records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records"))   # NaN -> null


def meta() -> dict:
    return {r["key"]: json.loads(r["value"]) for r in q("SELECT key, value FROM meta").to_dict("records")}


app = FastAPI(title="Aapurti API", description=config.SYNTHETIC_NOTICE, version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"status": "ok", "synthetic_data": True, "db_present": db_path().exists()}


@app.get("/api/filters")
def filters():
    plants = records(q("SELECT plant_id, plant_name FROM dim_plant ORDER BY plant_id"))
    skus = records(q("""SELECT DISTINCT d.sku_id, k.sku_name, k.volume_class, d.plant_id
                        FROM fact_forecast d JOIN dim_sku k USING (sku_id) ORDER BY d.sku_id"""))
    return {"plants": plants, "skus": skus, "as_of": meta().get("as_of"), "notice": config.SYNTHETIC_NOTICE}


@app.get("/api/kpis")
def kpis():
    inv = q("SELECT * FROM fact_inventory_position")
    hold = q("SELECT SUM(actual) a, SUM(forecast) f, SUM(ABS(actual-forecast)) e FROM fact_forecast WHERE actual IS NOT NULL")
    cap = q("SELECT SUM(run_hours) r, SUM(available_hours) a FROM fact_capacity_monthly "
            "WHERE month = (SELECT MAX(month) FROM fact_capacity_monthly)")
    last_month = q("SELECT MAX(month) m FROM fact_capacity_monthly")["m"].iloc[0]
    units30 = q("SELECT SUM(units) u FROM fact_daily_demand WHERE demand_date > date((SELECT MAX(demand_date) FROM fact_daily_demand), '-30 day')")["u"].iloc[0]
    rc = q("SELECT SUM(bronze_rows) b, SUM(quarantined_rows) q FROM dq_row_counts")
    a, e = float(hold["a"].iloc[0] or 0), float(hold["e"].iloc[0] or 0)
    docs = inv["days_of_cover"].dropna()
    return {
        "as_of": meta().get("as_of"),
        "forecast_wape": e / a if a else None,
        "forecast_accuracy": 1 - e / a if a else None,
        "units_last_30d": float(units30 or 0),
        "avg_days_of_cover": float(docs.mean()) if len(docs) else None,
        "high_risk_skus": int((inv["stockout_risk"] == "HIGH").sum()),
        "medium_risk_skus": int((inv["stockout_risk"] == "MEDIUM").sum()),
        "tracked_sku_plants": int(len(inv)),
        "inventory_value": float(inv["inventory_value"].sum()),
        "utilization_latest_month": float(cap["r"].iloc[0] / cap["a"].iloc[0]) if cap["a"].iloc[0] else None,
        "utilization_month": last_month,
        "dq_quarantine_rate": float(rc["q"].iloc[0] / rc["b"].iloc[0]) if rc["b"].iloc[0] else 0.0,
        "synthetic": True,
    }


@app.get("/api/forecast")
def forecast(sku_id: str | None = None, plant_id: str | None = None, history_days: int = Query(90, ge=7, le=400)):
    """Actual history plus forecast vs actual, aggregated over whichever of sku/plant is not filtered."""
    where, params = [], []
    if sku_id:
        where.append("sku_id = ?"); params.append(sku_id)
    if plant_id:
        where.append("plant_id = ?"); params.append(plant_id)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    hist = q(f"""SELECT demand_date AS date, SUM(units) AS actual FROM fact_daily_demand {w}
                 GROUP BY demand_date
                 HAVING demand_date > date((SELECT MAX(demand_date) FROM fact_daily_demand), '-{int(history_days)} day')
                 ORDER BY demand_date""", tuple(params))
    fc = q(f"""SELECT date, SUM(forecast) AS forecast, SUM(actual) AS actual_holdout, MAX(is_future) AS is_future,
                      GROUP_CONCAT(DISTINCT model) AS model
               FROM fact_forecast {w} GROUP BY date ORDER BY date""", tuple(params))
    if hist.empty and fc.empty:
        return {"series": [], "model": None, "wape_holdout": None}
    s = hist.merge(fc[["date", "forecast", "is_future"]], on="date", how="outer").sort_values("date")
    holdout = fc[fc["is_future"] == 0]
    a = float(holdout["actual_holdout"].sum())
    e = float((holdout["actual_holdout"] - holdout["forecast"]).abs().sum())
    # per-day abs error summed across series would hide offsetting errors; so report WAPE at series level too
    ser = q(f"SELECT sku_id, plant_id, actual, forecast FROM fact_forecast {w} AND is_future = 0" if w else
            "SELECT sku_id, plant_id, actual, forecast FROM fact_forecast WHERE is_future = 0", tuple(params))
    wape_series = float((ser["actual"] - ser["forecast"]).abs().sum() / ser["actual"].sum()) if ser["actual"].sum() else None
    return {"series": records(s), "models": sorted(set(",".join(fc["model"].dropna()).split(","))),
            "wape_holdout": wape_series, "wape_aggregate_day": (e / a if a else None)}


@app.get("/api/inventory/risk")
def inventory_risk(plant_id: str | None = None, risk: str | None = None, limit: int = Query(50, ge=1, le=500)):
    where, params = [], []
    if plant_id:
        where.append("plant_id = ?"); params.append(plant_id)
    if risk:
        if risk.upper() not in {"HIGH", "MEDIUM", "LOW"}:
            raise HTTPException(422, "risk must be HIGH, MEDIUM or LOW")
        where.append("stockout_risk = ?"); params.append(risk.upper())
    w = ("WHERE " + " AND ".join(where)) if where else ""
    df = q(f"""SELECT plant_id, sku_id, sku_name, category, volume_class, on_hand, avg_daily_demand, lead_time_days,
                      days_of_cover, safety_stock, reorder_point, stockout_risk, inventory_value
               FROM fact_inventory_position {w}
               ORDER BY CASE stockout_risk WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END,
                        days_of_cover IS NULL, days_of_cover LIMIT ?""", tuple(params) + (limit,))
    return {"rows": records(df)}


@app.get("/api/capacity")
def capacity(plant_id: str | None = None):
    w, params = ("WHERE plant_id = ?", (plant_id,)) if plant_id else ("", ())
    df = q(f"""SELECT month, plant_id, line_id, available_hours, run_hours, downtime_hours, utilization
               FROM fact_capacity_monthly {w} ORDER BY month, line_id""", params)
    latest = q(f"""SELECT line_id, plant_id, utilization FROM fact_capacity_monthly
                   WHERE month = (SELECT MAX(month) FROM fact_capacity_monthly) {'AND plant_id = ?' if plant_id else ''}
                   ORDER BY utilization DESC""", params)
    return {"monthly": records(df), "latest_by_line": records(latest)}


@app.get("/api/data-quality")
def data_quality():
    m = meta()
    return {"row_counts": records(q("SELECT * FROM dq_row_counts")),
            "quarantine": records(q("SELECT * FROM dq_quarantine_summary ORDER BY rows DESC")),
            "reconciliation": m.get("reconciliation", {}).get("checks", []),
            "reconciled": m.get("reconciliation", {}).get("all_ok")}


@app.get("/api/backtest")
def backtest():
    return {"results": records(q("SELECT * FROM backtest_results ORDER BY volume_class, wape")),
            "winners": records(q("SELECT * FROM model_selection"))}


@app.get("/export.xlsx")
def export_xlsx():
    inv = q("SELECT * FROM fact_inventory_position")
    fva = q("SELECT * FROM fact_forecast")
    plants = q("SELECT plant_id, plant_name FROM dim_plant ORDER BY plant_id")
    data = build_workbook(inv, fva, plants, str(meta().get("as_of")))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="aapurti_supply_chain.xlsx"'})


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
