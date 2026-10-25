# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze: raw files as-is plus ingestion metadata (`_source_file`, `_batch_id`, `_ingested_at`)

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

from datetime import datetime, timezone

from aapurti.pipeline import bronze
from aapurti.pipeline.session import write_table

batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
for name, df in bronze.ingest_all(spark, RAW, batch_id).items():  # noqa: F821
    write_table(df, f"{LAKE}/bronze/{name}", FMT)
    print(name, df.count())
