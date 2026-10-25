"""Orchestrates bronze -> silver -> gold on local Spark. CLI: python -m aapurti.pipeline.run"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import functions as F

from .. import config
from . import bronze, gold, silver
from .session import get_spark, read_table, write_table


def run_pipeline(raw_dir, lake_dir, fmt: str = "parquet", batch_id: str | None = None, spark=None) -> dict:
    """Runs the three layers; returns row counts and per-stage timings."""
    spark = spark or get_spark(delta=(fmt == "delta"))
    lake = Path(lake_dir)
    batch_id = batch_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    t: dict[str, float] = {}
    counts: dict[str, int] = {}

    def w(df, layer, name):
        write_table(df, lake / layer / name, fmt)

    t0 = time.perf_counter()
    for name, df in bronze.ingest_all(spark, raw_dir, batch_id).items():
        w(df, "bronze", name)
    t["bronze_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    b = {n: read_table(spark, lake / "bronze" / n, fmt) for n in
         list(bronze.CSV_SOURCES) + ["inventory_movements"]}
    dims = silver.clean_dims(b)
    for n, df in dims.items():
        w(df, "silver", n)
    dims = {n: read_table(spark, lake / "silver" / n, fmt) for n in dims}
    dem, q1 = silver.clean_demand(b["demand_daily"], dims["skus"], dims["plants"])
    mov, q2 = silver.clean_movements(b["inventory_movements"], dims["skus"], dims["plants"])
    cap, q3 = silver.clean_capacity(b["machine_capacity"], dims["lines"])
    w(dem, "silver", "demand_daily")
    w(mov, "silver", "inventory_movements")
    w(cap, "silver", "machine_capacity")
    w(q1.unionByName(q2).unionByName(q3), "silver", "quarantine")
    t["silver_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    s = {n: read_table(spark, lake / "silver" / n, fmt) for n in
         ["demand_daily", "inventory_movements", "machine_capacity", "quarantine"] + list(dims)}
    as_of = s["demand_daily"].agg(F.max("demand_date")).first()[0]
    w(gold.daily_demand(s["demand_daily"], s["skus"], s["plants"]), "gold", "daily_demand")
    w(gold.inventory_position(s["inventory_movements"], s["inventory_opening"], s["demand_daily"], s["skus"],
                              s["suppliers"], as_of), "gold", "inventory_position")
    w(gold.capacity_utilization(s["machine_capacity"], s["lines"], s["plants"]), "gold", "capacity_utilization")
    t["gold_s"] = time.perf_counter() - t0

    for layer, names in {"bronze": list(b), "silver": list(s), "gold": ["daily_demand", "inventory_position", "capacity_utilization"]}.items():
        for n in names:
            counts[f"{layer}.{n}"] = read_table(spark, lake / layer / n, fmt).count()
    t["total_s"] = t["bronze_s"] + t["silver_s"] + t["gold_s"]
    return {"batch_id": batch_id, "as_of": str(as_of), "format": fmt, "counts": counts,
            "timings_s": {k: round(v, 2) for k, v in t.items()}}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", default=str(config.RAW_DIR))
    p.add_argument("--lake", default=str(config.LAKE_DIR))
    p.add_argument("--format", default="parquet", choices=["parquet", "delta"])
    a = p.parse_args()
    res = run_pipeline(a.raw, a.lake, a.format)
    config.REPORTS_DIR.mkdir(exist_ok=True)
    (config.REPORTS_DIR / "pipeline_run.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
