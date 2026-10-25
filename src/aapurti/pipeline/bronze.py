"""Bronze: raw files loaded as-is (all columns string) plus ingestion metadata."""
from __future__ import annotations

from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

CSV_SOURCES = {
    "plants": "plants.csv", "suppliers": "suppliers.csv", "skus": "skus.csv", "lines": "lines.csv",
    "inventory_opening": "inventory_opening.csv", "demand_daily": "demand_daily.csv",
    "machine_capacity": "machine_capacity.csv",
}
MOVEMENT_COLUMNS = ["movement_id", "movement_date", "plant_id", "sku_id", "movement_type", "quantity"]


def add_metadata(df: DataFrame, source_file: str, batch_id: str) -> DataFrame:
    return (df.withColumn("_source_file", F.lit(source_file))
              .withColumn("_batch_id", F.lit(batch_id))
              .withColumn("_ingested_at", F.current_timestamp()))


def ingest_csv(spark: SparkSession, path, batch_id: str) -> DataFrame:
    df = spark.read.option("header", True).option("inferSchema", False).csv(str(path))
    return add_metadata(df, Path(path).name, batch_id)


def ingest_jsonl(spark: SparkSession, path, batch_id: str, columns: list[str]) -> DataFrame:
    # Read as text then extract so every field stays a string (no schema-inference drift).
    raw = spark.read.text(str(path))
    cols = [F.get_json_object("value", f"$.{c}").alias(c) for c in columns]
    return add_metadata(raw.select(*cols), Path(path).name, batch_id)


def ingest_all(spark: SparkSession, raw_dir, batch_id: str) -> dict[str, DataFrame]:
    raw_dir = Path(raw_dir)
    out = {name: ingest_csv(spark, raw_dir / f, batch_id) for name, f in CSV_SOURCES.items()}
    out["inventory_movements"] = ingest_jsonl(spark, raw_dir / "inventory_movements.jsonl", batch_id, MOVEMENT_COLUMNS)
    return out
