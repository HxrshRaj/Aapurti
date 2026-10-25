"""Gold: reporting tables. Formulas mirror aapurti.calcs (the approved definitions)."""
from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from ..config import DEMAND_WINDOW_DAYS, SERVICE_Z


def daily_demand(demand: DataFrame, skus: DataFrame, plants: DataFrame) -> DataFrame:
    return (demand.join(skus.select("sku_id", "sku_name", "category", "volume_class"), "sku_id")
            .join(plants.select("plant_id", "plant_name"), "plant_id")
            .select("demand_date", "plant_id", "plant_name", "sku_id", "sku_name", "category",
                    "volume_class", "units", "promo_flag"))


def inventory_position(movements: DataFrame, opening: DataFrame, demand: DataFrame, skus: DataFrame,
                       suppliers: DataFrame, as_of, window: int = DEMAND_WINDOW_DAYS,
                       z: float = SERVICE_Z) -> DataFrame:
    as_of_col = F.to_date(F.lit(str(as_of)))
    signed = (F.when(F.col("movement_type") == "ISSUE", -F.col("quantity"))
               .otherwise(F.col("quantity")))
    net = (movements.filter(F.col("movement_date") <= as_of_col)
           .groupBy("plant_id", "sku_id").agg(F.sum(signed).alias("net_movement")))
    start = F.date_sub(as_of_col, window - 1)
    d = (demand.filter((F.col("demand_date") >= start) & (F.col("demand_date") <= as_of_col))
         .groupBy("plant_id", "sku_id")
         .agg(F.sum("units").alias("_sum"), F.sum(F.col("units") * F.col("units")).alias("_sumsq")))
    base = (opening.join(net, ["plant_id", "sku_id"], "left")
            .join(d, ["plant_id", "sku_id"], "left")
            .join(skus.select("sku_id", "sku_name", "category", "volume_class", "supplier_id", "unit_cost"), "sku_id")
            .join(suppliers.select("supplier_id", "lead_time_days"), "supplier_id"))
    on_hand = F.col("opening_qty") + F.coalesce(F.col("net_movement"), F.lit(0))
    avg = F.coalesce(F.col("_sum"), F.lit(0.0)) / F.lit(float(window))
    var = F.greatest(F.coalesce(F.col("_sumsq"), F.lit(0.0)) / F.lit(float(window)) - avg * avg, F.lit(0.0))
    out = (base.withColumn("as_of_date", as_of_col)
           .withColumn("on_hand", on_hand.cast("double"))
           .withColumn("avg_daily_demand", avg)
           .withColumn("demand_sigma", F.sqrt(var))
           .withColumn("days_of_cover", F.when(avg > 0, on_hand / avg))
           .withColumn("safety_stock", F.lit(z) * F.col("demand_sigma") * F.sqrt(F.col("lead_time_days").cast("double")))
           .withColumn("reorder_point", avg * F.col("lead_time_days") + F.col("safety_stock"))
           .withColumn("stockout_risk",
                       F.when(F.col("days_of_cover").isNull(), "LOW")
                        .when(F.col("days_of_cover") < F.col("lead_time_days"), "HIGH")
                        .when(F.col("on_hand") < F.col("reorder_point"), "MEDIUM")
                        .otherwise("LOW"))
           .withColumn("inventory_value", F.col("on_hand") * F.col("unit_cost")))
    return out.select("as_of_date", "plant_id", "sku_id", "sku_name", "category", "volume_class", "supplier_id",
                      "lead_time_days", "unit_cost", "on_hand", "avg_daily_demand", "demand_sigma", "days_of_cover",
                      "safety_stock", "reorder_point", "stockout_risk", "inventory_value")


def capacity_utilization(capacity: DataFrame, lines: DataFrame, plants: DataFrame) -> DataFrame:
    """Monthly by line. utilization = sum(run_hours) / sum(available_hours)."""
    return (capacity.withColumn("month", F.date_format("capacity_date", "yyyy-MM"))
            .groupBy("month", "plant_id", "line_id")
            .agg(F.sum("available_hours").alias("available_hours"), F.sum("run_hours").alias("run_hours"),
                 F.sum("downtime_hours").alias("downtime_hours"), F.sum("units_produced").alias("units_produced"))
            .withColumn("utilization", F.when(F.col("available_hours") > 0, F.col("run_hours") / F.col("available_hours")))
            .join(lines.select("line_id", "rated_units_per_hour"), "line_id")
            .join(plants.select("plant_id", "plant_name"), "plant_id")
            .select("month", "plant_id", "plant_name", "line_id", "available_hours", "run_hours",
                    "downtime_hours", "units_produced", "utilization"))
