"""Join-strategy comparison from Spark's physical plan.

The same join is planned twice: once with broadcast joins allowed and once with them disabled (a sort-merge join with a
shuffle on both sides). For each plan the report counts shuffle (Exchange) and broadcast nodes and the result checksum, so
the two strategies can be shown to return the same answer while doing different work.
"""
from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F


def plan_text(df: DataFrame) -> str:
    return df._jdf.queryExecution().executedPlan().toString()


def strategy_of(plan: str) -> str:
    if "BroadcastHashJoin" in plan:
        return "broadcast_hash"
    if "SortMergeJoin" in plan:
        return "sort_merge"
    if "ShuffledHashJoin" in plan:
        return "shuffled_hash"
    return "other"


def _checksum(joined: DataFrame, value_col: str) -> dict:
    row = joined.agg(F.count("*").alias("rows"), F.sum(value_col).alias("total")).collect()[0]
    return {"rows": int(row["rows"]), "total": float(row["total"])}


def compare_join_strategies(spark: SparkSession, big: DataFrame, small: DataFrame, key: str, value_col: str) -> list[dict]:
    """Plan and run `big JOIN small USING (key)` with broadcast allowed, then with it disabled."""
    conf = {"spark.sql.adaptive.enabled": "false", "spark.sql.autoBroadcastJoinThreshold": None}
    saved = {k: spark.conf.get(k, None) for k in conf}
    out = []
    try:
        spark.conf.set("spark.sql.adaptive.enabled", "false")  # adaptive execution would re-plan at run time
        for label, threshold in (("broadcast_allowed", str(10 * 1024 * 1024)), ("broadcast_disabled", "-1")):
            spark.conf.set("spark.sql.autoBroadcastJoinThreshold", threshold)
            joined = big.join(small, key)
            plan = plan_text(joined)
            out.append({"setting": label, "strategy": strategy_of(plan),
                        "shuffles": plan.count("Exchange hashpartitioning"),
                        "broadcasts": plan.count("BroadcastExchange"), **_checksum(joined, value_col)})
    finally:
        for k, v in saved.items():
            if v is None:
                spark.conf.unset(k)
            else:
                spark.conf.set(k, v)
    return out


def main() -> None:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lake", required=True)
    a = ap.parse_args()
    from aapurti.pipeline.session import get_spark
    spark = get_spark("aapurti-plans", shuffle_partitions=4)
    spark.sparkContext.setLogLevel("ERROR")
    demand = spark.read.parquet(f"{a.lake}/gold/daily_demand")
    skus = spark.read.parquet(f"{a.lake}/silver/skus").select("sku_id", "category")
    print(json.dumps(compare_join_strategies(spark, demand, skus, "sku_id", "units"), indent=2))


if __name__ == "__main__":
    main()
