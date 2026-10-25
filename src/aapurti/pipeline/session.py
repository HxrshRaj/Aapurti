"""SparkSession + table IO. Parquet by default; Delta behind fmt='delta' (needs delta-spark)."""
from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession


def get_spark(app: str = "aapurti", delta: bool = False, shuffle_partitions: int = 8) -> SparkSession:
    existing = SparkSession.getActiveSession()
    if existing is not None:
        return existing
    b = (SparkSession.builder.appName(app).master("local[*]")
         .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
         .config("spark.sql.session.timeZone", "UTC")
         .config("spark.ui.enabled", "false")
         .config("spark.ui.showConsoleProgress", "false")
         .config("spark.driver.memory", "2g"))
    if delta:
        from delta import configure_spark_with_delta_pip  # type: ignore
        b = (b.config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
             .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"))
        return configure_spark_with_delta_pip(b).getOrCreate()
    return b.getOrCreate()


def write_table(df: DataFrame, path, fmt: str = "parquet") -> None:
    df.write.mode("overwrite").format(fmt).save(str(path))


def read_table(spark: SparkSession, path, fmt: str = "parquet") -> DataFrame:
    return spark.read.format(fmt).load(str(path))
