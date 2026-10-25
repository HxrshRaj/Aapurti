# Databricks notebook source
# MAGIC %md
# MAGIC # Silver: typed, deduplicated, validated; bad rows go to `quarantine` with the reason

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

from aapurti.pipeline import bronze, silver
from aapurti.pipeline.session import read_table, write_table

b = {n: read_table(spark, f"{LAKE}/bronze/{n}", FMT) for n in list(bronze.CSV_SOURCES) + ["inventory_movements"]}  # noqa: F821
dims = silver.clean_dims(b)
for n, df in dims.items():
    write_table(df, f"{LAKE}/silver/{n}", FMT)
dims = {n: read_table(spark, f"{LAKE}/silver/{n}", FMT) for n in dims}  # noqa: F821

dem, q1 = silver.clean_demand(b["demand_daily"], dims["skus"], dims["plants"])
mov, q2 = silver.clean_movements(b["inventory_movements"], dims["skus"], dims["plants"])
cap, q3 = silver.clean_capacity(b["machine_capacity"], dims["lines"])
for n, df in {"demand_daily": dem, "inventory_movements": mov, "machine_capacity": cap}.items():
    write_table(df, f"{LAKE}/silver/{n}", FMT)
write_table(q1.unionByName(q2).unionByName(q3), f"{LAKE}/silver/quarantine", FMT)

# COMMAND ----------

display(read_table(spark, f"{LAKE}/silver/quarantine", FMT).groupBy("source_table", "reason").count())  # noqa: F821
