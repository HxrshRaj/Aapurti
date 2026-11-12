"""Hive-style SQL warehouse over the gold layer, queried with Spark SQL.

Builds a small star schema in a local Hive metastore (embedded Derby, no server needed):

    dim_sku, dim_plant                 -> Parquet dimension tables
    fact_daily_demand                  -> Parquet fact table PARTITIONED BY (demand_month)

and runs analytics in Spark SQL (window functions, month-over-month growth, rolling averages). Partition
pruning is checked from the physical plan, so a single-month query provably reads one partition.

    python -m aapurti.pipeline.warehouse --lake data/lake --out data/warehouse
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

DB = "aapurti_dw"

QUERIES = {
    # Highest-volume category in each plant, with its share of the plant's units (RANK over a window).
    "top_category_by_plant": f"""
        SELECT plant_id, category, units, ROUND(100 * units / plant_units, 1) AS share_pct
        FROM (
          SELECT f.plant_id, s.category, SUM(f.units) AS units,
                 SUM(SUM(f.units)) OVER (PARTITION BY f.plant_id) AS plant_units,
                 RANK() OVER (PARTITION BY f.plant_id ORDER BY SUM(f.units) DESC) AS rnk
          FROM {DB}.fact_daily_demand f JOIN {DB}.dim_sku s USING (sku_id)
          GROUP BY f.plant_id, s.category
        ) WHERE rnk = 1 ORDER BY plant_id""",
    # Month-over-month change in total units (LAG over a window).
    "monthly_growth": f"""
        SELECT demand_month, units,
               LAG(units) OVER (ORDER BY demand_month) AS prev_units,
               ROUND(100 * (units - LAG(units) OVER (ORDER BY demand_month))
                     / LAG(units) OVER (ORDER BY demand_month), 1) AS growth_pct
        FROM (SELECT demand_month, SUM(units) AS units FROM {DB}.fact_daily_demand GROUP BY demand_month)
        ORDER BY demand_month""",
    # Trailing 7-day average of units for one plant (window frame).
    "rolling_7d_avg": f"""
        SELECT demand_date, units,
               ROUND(AVG(units) OVER (ORDER BY demand_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS avg_7d
        FROM (SELECT demand_date, SUM(units) AS units FROM {DB}.fact_daily_demand
              WHERE plant_id = (SELECT MIN(plant_id) FROM {DB}.dim_plant) GROUP BY demand_date)
        ORDER BY demand_date""",
}


def get_hive_spark(base_dir) -> SparkSession:
    """Spark session with Hive support and a metastore + warehouse under base_dir. Must be the first session
    created in the process (Hive support cannot be added to an already running session)."""
    base = Path(base_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    return (SparkSession.builder.appName("aapurti-warehouse").master("local[2]")
            .config("spark.sql.warehouse.dir", str(base / "warehouse"))
            .config("spark.hadoop.javax.jdo.option.ConnectionURL",
                    f"jdbc:derby:;databaseName={base / 'metastore'};create=true")
            .config("spark.sql.session.timeZone", "UTC")
            .config("spark.sql.shuffle.partitions", "4")
            .config("spark.ui.enabled", "false")
            .enableHiveSupport().getOrCreate())


def build_warehouse(spark: SparkSession, lake_dir) -> dict:
    """(Re)create the star schema from the lake's silver dimensions and gold daily_demand. Returns row counts."""
    lake = Path(lake_dir)
    spark.sql(f"CREATE DATABASE IF NOT EXISTS {DB}")
    for t in ("fact_daily_demand", "dim_sku", "dim_plant"):
        spark.sql(f"DROP TABLE IF EXISTS {DB}.{t}")

    skus = spark.read.parquet(str(lake / "silver" / "skus")).select("sku_id", "sku_name", "category", "volume_class")
    plants = spark.read.parquet(str(lake / "silver" / "plants")).select("plant_id", "plant_name")
    demand = (spark.read.parquet(str(lake / "gold" / "daily_demand"))
              .select("demand_date", "plant_id", "sku_id", "units", "promo_flag")
              .withColumn("demand_month", F.date_format("demand_date", "yyyy-MM")))

    skus.write.format("parquet").mode("overwrite").saveAsTable(f"{DB}.dim_sku")
    plants.write.format("parquet").mode("overwrite").saveAsTable(f"{DB}.dim_plant")
    (demand.write.format("parquet").mode("overwrite").partitionBy("demand_month")
     .saveAsTable(f"{DB}.fact_daily_demand"))
    for t in ("dim_sku", "dim_plant", "fact_daily_demand"):
        spark.sql(f"ANALYZE TABLE {DB}.{t} COMPUTE STATISTICS")
    return {t: spark.table(f"{DB}.{t}").count() for t in ("dim_sku", "dim_plant", "fact_daily_demand")}


def partitions(spark: SparkSession) -> list[str]:
    return sorted(r[0].split("=", 1)[1] for r in spark.sql(f"SHOW PARTITIONS {DB}.fact_daily_demand").collect())


def pruning_report(spark: SparkSession, month: str) -> dict:
    """Physical-plan check: a filter on the partition column should read exactly that one partition."""
    q = f"SELECT SUM(units) FROM {DB}.fact_daily_demand WHERE demand_month = '{month}'"
    plan = spark._jsparkSession.sql(q).queryExecution().executedPlan().toString()
    scan = next((ln for ln in plan.splitlines() if "FileScan" in ln), "")
    return {"query": q, "uses_partition_filter": "PartitionFilters: [" in scan and month in scan,
            "partitions_total": len(partitions(spark)), "scan": scan.strip()[:300]}


def run_queries(spark: SparkSession) -> dict:
    return {name: [r.asDict() for r in spark.sql(sql).collect()] for name, sql in QUERIES.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lake", required=True)
    ap.add_argument("--out", required=True, help="directory for the Hive metastore and warehouse")
    ap.add_argument("--json", action="store_true", help="print one JSON document instead of a text report")
    a = ap.parse_args()
    spark = get_hive_spark(a.out)
    spark.sparkContext.setLogLevel("ERROR")
    counts = build_warehouse(spark, a.lake)
    months = partitions(spark)
    result = {"row_counts": counts, "partitions": months,
              "pruning": pruning_report(spark, months[len(months) // 2]), "queries": run_queries(spark)}
    spark.stop()
    if a.json:
        print("JSON_START" + json.dumps(result, default=str) + "JSON_END")
        return
    print("rows:", counts, "| partitions:", len(months))
    print("partition pruning OK:", result["pruning"]["uses_partition_filter"])
    for name, rows in result["queries"].items():
        print(f"\n-- {name} ({len(rows)} rows)")
        for r in rows[:5]:
            print("  ", r)


if __name__ == "__main__":
    main()
