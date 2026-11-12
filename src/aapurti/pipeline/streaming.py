"""Spark Structured Streaming over inventory-movement events dropped into a directory.

Tumbling event-time windows per (plant, movement type) with a watermark. Events that arrive later than the watermark are
dropped, and the watermark and window state survive restarts through the checkpoint directory, so a late event after a
restart is still dropped. Updated windows are upserted by key in `foreachBatch`, which makes a replayed micro-batch
idempotent. Runs with `trigger(availableNow=True)`: it drains what is in the directory, then stops (no always-on service).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType, TimestampType

EVENT_SCHEMA = StructType([
    StructField("movement_id", StringType()),
    StructField("event_time", TimestampType()),
    StructField("plant_id", StringType()),
    StructField("sku_id", StringType()),
    StructField("movement_type", StringType()),
    StructField("quantity", DoubleType()),
])


def read_events(spark: SparkSession, input_dir) -> DataFrame:
    return spark.readStream.schema(EVENT_SCHEMA).option("header", True).csv(str(input_dir))


def windowed_totals(events: DataFrame, window: str = "1 hour", watermark: str = "10 minutes") -> DataFrame:
    """Event count and total quantity per tumbling window, plant and movement type."""
    return (events.withWatermark("event_time", watermark)
            .groupBy(F.window("event_time", window), "plant_id", "movement_type")
            .agg(F.count("*").alias("events"), F.sum("quantity").alias("total_quantity")))


class WindowStore:
    """Upserts window results by (window start, plant, movement type); the last write for a key wins."""

    def __init__(self) -> None:
        self.rows: dict[tuple, dict] = {}
        self.batches: list[int] = []

    def upsert(self, batch: DataFrame, batch_id: int) -> None:
        self.batches.append(batch_id)
        for r in batch.collect():
            key = (r["window"]["start"].isoformat(), r["plant_id"], r["movement_type"])
            self.rows[key] = {"window_start": key[0], "window_end": r["window"]["end"].isoformat(),
                              "plant_id": r["plant_id"], "movement_type": r["movement_type"],
                              "events": int(r["events"]), "total_quantity": float(r["total_quantity"])}

    def as_list(self) -> list[dict]:
        return [self.rows[k] for k in sorted(self.rows)]


def drain(spark: SparkSession, input_dir, checkpoint_dir, store: WindowStore,
          window: str = "1 hour", watermark: str = "10 minutes") -> None:
    """Process every new file in input_dir once, then return. Call again after more files arrive."""
    query = (windowed_totals(read_events(spark, input_dir), window, watermark)
             .writeStream.outputMode("update").foreachBatch(store.upsert)
             .option("checkpointLocation", str(checkpoint_dir))
             .trigger(availableNow=True).start())
    query.awaitTermination()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", required=True, help="directory of CSV files with the EVENT_SCHEMA columns")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--window", default="1 hour")
    ap.add_argument("--watermark", default="10 minutes")
    ap.add_argument("--out", help="write the window results as JSON")
    a = ap.parse_args()
    from aapurti.pipeline.session import get_spark
    spark = get_spark("aapurti-streaming", shuffle_partitions=2)
    spark.sparkContext.setLogLevel("ERROR")
    store = WindowStore()
    drain(spark, a.input, a.checkpoint, store, a.window, a.watermark)
    rows = store.as_list()
    if a.out:
        Path(a.out).write_text(json.dumps(rows, indent=2))
    print(f"{len(rows)} windows from {len(store.batches)} micro-batch(es)")
    for r in rows[:10]:
        print("  ", r)


if __name__ == "__main__":
    main()
