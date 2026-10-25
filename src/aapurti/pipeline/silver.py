"""Silver: typed, deduplicated, validated. Bad rows go to a quarantine table with the reason."""
from __future__ import annotations

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql import functions as F

from ..config import DEMAND_MAX_PLAUSIBLE

META = ["_source_file", "_batch_id", "_ingested_at"]
VALID_MOVEMENTS = ["RECEIPT", "ISSUE", "ADJUSTMENT"]


def _first_reason(rules: list[tuple[str, Column]]) -> Column:
    """rules: (reason, failing_condition). First failing rule wins; NULL when the row is valid."""
    expr = F.lit(None).cast("string")
    for reason, cond in reversed(rules):
        expr = F.when(cond, F.lit(reason)).otherwise(expr)
    return expr


def _with_reason(df: DataFrame, rules: list[tuple[str, Column]], key: list[str]) -> DataFrame:
    """Adds `_reason`. A row fails on the first broken rule; among rows that pass every rule only the first per key
    survives and later ones are 'duplicate'. Duplicates are numbered among *valid* rows only, so a malformed row
    that shares a key can never displace the good one."""
    df = df.withColumn("_pre", _first_reason(rules)).withColumn("_ok", F.col("_pre").isNull())
    w = Window.partitionBy(*key, "_ok").orderBy("_ingested_at")
    df = df.withColumn("_rn", F.row_number().over(w))
    return df.withColumn("_reason", F.when(F.col("_ok") & (F.col("_rn") > 1), F.lit("duplicate")).otherwise(F.col("_pre")))


def _split(df: DataFrame, source_table: str, raw_cols: list[str]):
    bad = df.filter(F.col("_reason").isNotNull()).select(
        F.lit(source_table).alias("source_table"),
        F.col("_reason").alias("reason"),
        F.to_json(F.struct(*[F.col(c) for c in raw_cols])).alias("record"),
        F.col("_batch_id"))
    good = df.filter(F.col("_reason").isNull())
    return good, bad


def _ref_flags(df: DataFrame, valid_skus: DataFrame | None, valid_plants: DataFrame | None) -> DataFrame:
    if valid_skus is not None:
        df = df.join(valid_skus.select("sku_id").distinct().withColumn("_sku_ok", F.lit(1)), "sku_id", "left")
    if valid_plants is not None:
        df = df.join(valid_plants.select("plant_id").distinct().withColumn("_plant_ok", F.lit(1)), "plant_id", "left")
    return df


def clean_demand(bronze: DataFrame, valid_skus: DataFrame, valid_plants: DataFrame):
    raw_cols = ["demand_date", "plant_id", "sku_id", "units", "promo_flag"]
    df = (bronze
          .withColumn("demand_date_t", F.to_date("demand_date", "yyyy-MM-dd"))
          .withColumn("units_t", F.col("units").cast("double"))
          .withColumn("promo_t", F.col("promo_flag").cast("int")))
    df = _ref_flags(df, valid_skus, valid_plants)
    rules = [
        ("null_key", F.col("plant_id").isNull() | F.col("sku_id").isNull() | F.col("demand_date").isNull()),
        ("invalid_date", F.col("demand_date_t").isNull()),
        ("null_units", F.col("units_t").isNull()),
        ("negative_units", F.col("units_t") < 0),
        ("units_out_of_range", F.col("units_t") > DEMAND_MAX_PLAUSIBLE),
        ("unknown_sku", F.col("_sku_ok").isNull()),
        ("unknown_plant", F.col("_plant_ok").isNull()),
    ]
    df = _with_reason(df, rules, ["demand_date", "plant_id", "sku_id"])
    good, bad = _split(df, "demand_daily", raw_cols)
    good = good.select(F.col("demand_date_t").alias("demand_date"), "plant_id", "sku_id",
                       F.col("units_t").cast("long").alias("units"),
                       F.coalesce(F.col("promo_t"), F.lit(0)).alias("promo_flag"), *META)
    return good, bad


def clean_movements(bronze: DataFrame, valid_skus: DataFrame, valid_plants: DataFrame):
    raw_cols = ["movement_id", "movement_date", "plant_id", "sku_id", "movement_type", "quantity"]
    df = (bronze.withColumn("movement_date_t", F.to_date("movement_date", "yyyy-MM-dd"))
                .withColumn("quantity_t", F.col("quantity").cast("long")))
    df = _ref_flags(df, valid_skus, valid_plants)
    rules = [
        ("null_key", F.col("movement_id").isNull()),
        ("invalid_date", F.col("movement_date_t").isNull()),
        ("null_quantity", F.col("quantity_t").isNull()),
        ("invalid_movement_type", F.col("movement_type").isNull() | ~F.col("movement_type").isin(VALID_MOVEMENTS)),
        ("negative_quantity", (F.col("quantity_t") < 0) & (F.col("movement_type") != "ADJUSTMENT")),
        ("unknown_sku", F.col("_sku_ok").isNull()),
        ("unknown_plant", F.col("_plant_ok").isNull()),
    ]
    df = _with_reason(df, rules, ["movement_id"])
    good, bad = _split(df, "inventory_movements", raw_cols)
    good = good.select("movement_id", F.col("movement_date_t").alias("movement_date"), "plant_id", "sku_id",
                       "movement_type", F.col("quantity_t").alias("quantity"), *META)
    return good, bad


def clean_capacity(bronze: DataFrame, valid_lines: DataFrame):
    raw_cols = ["capacity_date", "plant_id", "line_id", "available_hours", "run_hours",
                "downtime_hours", "units_produced"]
    df = (bronze.withColumn("d", F.to_date("capacity_date", "yyyy-MM-dd"))
                .withColumn("avail", F.col("available_hours").cast("double"))
                .withColumn("run", F.col("run_hours").cast("double"))
                .withColumn("down", F.col("downtime_hours").cast("double"))
                .withColumn("units_p", F.col("units_produced").cast("long")))
    df = df.join(valid_lines.select("line_id").distinct().withColumn("_line_ok", F.lit(1)), "line_id", "left")
    rules = [
        ("invalid_date", F.col("d").isNull()),
        ("null_hours", F.col("avail").isNull() | F.col("run").isNull() | F.col("down").isNull()),
        ("negative_hours", (F.col("avail") < 0) | (F.col("run") < 0) | (F.col("down") < 0)),
        ("run_exceeds_available", F.col("run") > F.col("avail")),
        ("unknown_line", F.col("_line_ok").isNull()),
    ]
    df = _with_reason(df, rules, ["capacity_date", "line_id"])
    good, bad = _split(df, "machine_capacity", raw_cols)
    good = good.select(F.col("d").alias("capacity_date"), "plant_id", "line_id",
                       F.col("avail").alias("available_hours"), F.col("run").alias("run_hours"),
                       F.col("down").alias("downtime_hours"), F.col("units_p").alias("units_produced"), *META)
    return good, bad


def clean_dims(b: dict[str, DataFrame]) -> dict[str, DataFrame]:
    """Reference tables are small and trusted, but are still typed and deduplicated on their key."""
    return {
        "plants": b["plants"].dropDuplicates(["plant_id"]),
        "suppliers": (b["suppliers"].withColumn("lead_time_days", F.col("lead_time_days").cast("int"))
                      .withColumn("reliability", F.col("reliability").cast("double")).dropDuplicates(["supplier_id"])),
        "skus": b["skus"].withColumn("unit_cost", F.col("unit_cost").cast("double")).dropDuplicates(["sku_id"]),
        "lines": (b["lines"].withColumn("rated_units_per_hour", F.col("rated_units_per_hour").cast("int"))
                  .dropDuplicates(["line_id"])),
        "inventory_opening": (b["inventory_opening"].withColumn("opening_qty", F.col("opening_qty").cast("long"))
                              .dropDuplicates(["plant_id", "sku_id"])),
    }
