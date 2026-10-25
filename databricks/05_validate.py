# Databricks notebook source
# MAGIC %md
# MAGIC # Validation against approved calculations (reference/) and source reconciliation
# MAGIC The reference tests need the repo's `reference/` folder (Repos checkout) and Parquet access via the driver's local path,
# MAGIC so this notebook validates the pure-Python approved cases and runs the SQL-level checks below.

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

from aapurti.validation.reference import check_calcs

results = check_calcs()
assert all(r["ok"] for r in results), [r for r in results if not r["ok"]]
print(f"{len(results)} approved calculation cases match")

# COMMAND ----------

# Every bronze row must be in silver or in quarantine.
for t in ["demand_daily", "inventory_movements", "machine_capacity"]:
    b = spark.read.format(FMT).load(f"{LAKE}/bronze/{t}").count()  # noqa: F821
    s = spark.read.format(FMT).load(f"{LAKE}/silver/{t}").count()  # noqa: F821
    q = spark.read.format(FMT).load(f"{LAKE}/silver/quarantine").filter(f"source_table = '{t}'").count()  # noqa: F821
    assert b == s + q, (t, b, s, q)
    print(t, "OK", b, "=", s, "+", q)
