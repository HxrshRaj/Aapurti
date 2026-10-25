"""Batch step 3: load gold tables into SQLite for the API (no Spark needed at serve time) and
write the Power BI star-schema exports. CLI: python -m aapurti.serving"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd

from . import config


def _gold(lake: Path, name: str) -> pd.DataFrame:
    return pd.read_parquet(lake / "gold" / name)


def _silver(lake: Path, name: str) -> pd.DataFrame:
    return pd.read_parquet(lake / "silver" / name)


def build_tables(lake_dir, reports_dir=config.REPORTS_DIR) -> dict[str, pd.DataFrame]:
    lake, reports = Path(lake_dir), Path(reports_dir)
    dem = _gold(lake, "daily_demand")
    dem["demand_date"] = pd.to_datetime(dem["demand_date"]).dt.strftime("%Y-%m-%d")
    inv = _gold(lake, "inventory_position")
    inv["as_of_date"] = pd.to_datetime(inv["as_of_date"]).dt.strftime("%Y-%m-%d")
    fva = _gold(lake, "forecast_vs_actual")
    fva["date"] = pd.to_datetime(fva["date"]).dt.strftime("%Y-%m-%d")
    q = _silver(lake, "quarantine")

    counts = []
    for t in ("demand_daily", "inventory_movements", "machine_capacity"):
        b = len(pd.read_parquet(lake / "bronze" / t))
        s = len(_silver(lake, t))
        counts.append({"table": t, "bronze_rows": b, "silver_rows": s,
                       "quarantined_rows": int((q["source_table"] == t).sum())})

    skus = _silver(lake, "skus")
    plants = _silver(lake, "plants")
    suppliers = _silver(lake, "suppliers")
    lines = _silver(lake, "lines")
    tables = {
        "dim_plant": plants[["plant_id", "plant_name", "region"]],
        "dim_supplier": suppliers[["supplier_id", "supplier_name", "lead_time_days", "reliability"]],
        "dim_sku": skus[["sku_id", "sku_name", "category", "volume_class", "unit_cost", "supplier_id"]],
        "dim_line": lines[["line_id", "plant_id", "rated_units_per_hour"]],
        "fact_daily_demand": dem[["demand_date", "plant_id", "sku_id", "units", "promo_flag"]],
        "fact_inventory_position": inv,
        "fact_capacity_monthly": _gold(lake, "capacity_utilization").assign(
            month_start=lambda d: d["month"] + "-01"),   # date key for the Power BI date relationship
        "fact_forecast": fva,
        "backtest_results": _gold(lake, "backtest_results"),
        "model_selection": _gold(lake, "model_selection"),
        "dq_quarantine_summary": (q.groupby(["source_table", "reason"]).size().rename("rows").reset_index()),
        "dq_row_counts": pd.DataFrame(counts),
    }
    dates = pd.date_range(dem["demand_date"].min(), dem["demand_date"].max(), freq="D")
    tables["dim_date"] = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"), "year": dates.year, "quarter": dates.quarter, "month": dates.month,
        "month_name": dates.strftime("%b"), "year_month": dates.strftime("%Y-%m"),
        "week_of_year": dates.isocalendar().week.to_numpy(), "day_of_week": dates.day_of_week + 1,
        "is_weekend": (dates.day_of_week >= 5).astype(int)})

    meta = {"synthetic": True, "notice": config.SYNTHETIC_NOTICE, "as_of": str(inv["as_of_date"].iloc[0])}
    for fn, key in (("reconciliation.json", "reconciliation"), ("pipeline_run.json", "pipeline_run"),
                    ("forecast_run.json", "forecast_run")):
        p = reports / fn
        if p.exists():
            meta[key] = json.loads(p.read_text())
    tables["meta"] = pd.DataFrame([{"key": k, "value": json.dumps(v)} for k, v in meta.items()])
    return tables


def write_sqlite(tables: dict[str, pd.DataFrame], db_path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    for name, df in tables.items():
        df.to_sql(name, con, index=False)
    con.execute("CREATE INDEX ix_dem ON fact_daily_demand(sku_id, plant_id, demand_date)")
    con.execute("CREATE INDEX ix_fc ON fact_forecast(sku_id, plant_id, date)")
    con.commit()
    con.execute("VACUUM")
    con.close()


def write_powerbi(tables: dict[str, pd.DataFrame], out_dir) -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    star = ["dim_date", "dim_plant", "dim_sku", "dim_supplier", "dim_line", "fact_daily_demand",
            "fact_inventory_position", "fact_capacity_monthly", "fact_forecast", "backtest_results"]
    for n in star:
        tables[n].to_csv(out / f"{n}.csv", index=False)
    return star


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--lake", default=str(config.LAKE_DIR))
    p.add_argument("--db", default=str(config.DB_PATH))
    p.add_argument("--powerbi", default=str(config.ROOT / "powerbi" / "data"))
    a = p.parse_args()
    t = build_tables(a.lake)
    write_sqlite(t, a.db)
    print("sqlite:", a.db, Path(a.db).stat().st_size // 1024, "KB")
    print("powerbi:", write_powerbi(t, a.powerbi))


if __name__ == "__main__":
    main()
