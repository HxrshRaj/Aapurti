# Databricks notebook source
# MAGIC %md
# MAGIC # Gold: daily demand, inventory position (days of cover, safety stock, stockout risk), capacity utilization

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

from pyspark.sql import functions as F

from aapurti.pipeline import gold
from aapurti.pipeline.session import read_table, write_table

s = {n: read_table(spark, f"{LAKE}/silver/{n}", FMT) for n in  # noqa: F821
     ["demand_daily", "inventory_movements", "machine_capacity", "skus", "plants", "suppliers", "lines", "inventory_opening"]}
as_of = s["demand_daily"].agg(F.max("demand_date")).first()[0]
write_table(gold.daily_demand(s["demand_daily"], s["skus"], s["plants"]), f"{LAKE}/gold/daily_demand", FMT)
write_table(gold.inventory_position(s["inventory_movements"], s["inventory_opening"], s["demand_daily"], s["skus"],
                                    s["suppliers"], as_of), f"{LAKE}/gold/inventory_position", FMT)
write_table(gold.capacity_utilization(s["machine_capacity"], s["lines"], s["plants"]), f"{LAKE}/gold/capacity_utilization", FMT)

# COMMAND ----------

display(read_table(spark, f"{LAKE}/gold/inventory_position", FMT).orderBy("days_of_cover"))  # noqa: F821
