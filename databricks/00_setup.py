# Databricks notebook source
# MAGIC %md
# MAGIC # Aapurti: setup (SYNTHETIC data)
# MAGIC Imports the same `aapurti` Python package that the local pipeline and the tests use.
# MAGIC **Status:** these notebooks are written to Databricks source format and call the tested modules, but they have
# MAGIC **not been imported or run on a Databricks workspace** from this repository.
# MAGIC
# MAGIC Setup: add this repo as a Databricks Repo (or upload `src/aapurti`), then attach a cluster with Spark 3.5+ / DBR 14+.

# COMMAND ----------

import sys

REPO_SRC = "/Workspace/Repos/<your-user>/Aapurti/src"  # edit: path of the repo's src/ folder in your workspace
if REPO_SRC not in sys.path:
    sys.path.insert(0, REPO_SRC)

dbutils.widgets.text("base_path", "/dbfs/tmp/aapurti", "Base path (raw/lake)")  # noqa: F821
dbutils.widgets.dropdown("format", "delta", ["delta", "parquet"], "Table format")  # noqa: F821
BASE = dbutils.widgets.get("base_path")  # noqa: F821
FMT = dbutils.widgets.get("format")  # noqa: F821
RAW, LAKE = f"{BASE}/raw", f"{BASE}/lake"
print(RAW, LAKE, FMT)

# COMMAND ----------

# Generate the synthetic raw files (seeded, deterministic). Runs on the driver with pandas.
from pathlib import Path

from aapurti.generator import generate

Path(RAW).mkdir(parents=True, exist_ok=True)
print(generate(Path(RAW)))
