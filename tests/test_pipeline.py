import pandas as pd
import pytest
from pyspark.sql import functions as F

from aapurti.pipeline import silver


def test_bronze_is_raw_strings_with_metadata(spark, mini_env):
    b = spark.read.parquet(str(mini_env["lake"] / "bronze" / "demand_daily"))
    types = {f.name: f.dataType.simpleString() for f in b.schema}
    assert all(types[c] == "string" for c in ["demand_date", "plant_id", "sku_id", "units", "promo_flag"])
    for meta in ("_source_file", "_batch_id", "_ingested_at"):
        assert meta in types
    assert b.filter("_source_file != 'demand_daily.csv'").count() == 0


def test_bronze_keeps_every_source_row(mini_env):
    src = pd.read_csv(mini_env["raw"] / "demand_daily.csv")
    assert len(pd.read_parquet(mini_env["lake"] / "bronze" / "demand_daily")) == len(src)


@pytest.mark.parametrize("tbl", ["demand_daily", "inventory_movements", "machine_capacity"])
def test_silver_plus_quarantine_equals_bronze(mini_env, tbl):
    lake = mini_env["lake"]
    b = len(pd.read_parquet(lake / "bronze" / tbl))
    s = len(pd.read_parquet(lake / "silver" / tbl))
    q = pd.read_parquet(lake / "silver" / "quarantine")
    assert b == s + (q["source_table"] == tbl).sum()


def test_quarantine_has_reasons_and_records(mini_env):
    q = pd.read_parquet(mini_env["lake"] / "silver" / "quarantine")
    assert len(q) > 0 and q["reason"].notna().all() and q["record"].str.startswith("{").all()
    assert {"duplicate", "unknown_sku", "negative_units"} <= set(q["reason"])


def test_silver_demand_is_typed_and_valid(mini_env):
    d = pd.read_parquet(mini_env["lake"] / "silver" / "demand_daily")
    assert d["units"].dtype.kind == "i" and (d["units"] >= 0).all()
    assert not d.duplicated(["demand_date", "plant_id", "sku_id"]).any()
    assert "S999" not in set(d["sku_id"])


def test_quarantine_rules_on_synthetic_rows(spark):
    cols = ["demand_date", "plant_id", "sku_id", "units", "promo_flag", "_source_file", "_batch_id"]
    rows = [("2025-01-01", "P1", "A", "10", "0", "f", "b"),      # good
            ("2025-01-01", "P1", "A", "10", "0", "f", "b"),      # duplicate
            ("2025-01-02", "P1", "A", None, "0", "f", "b"),      # null units
            ("2025-01-03", "P1", "A", "-3", "0", "f", "b"),      # negative
            ("2025-01-04", "P1", "A", "200000", "0", "f", "b"),  # out of range
            ("2025-01-05", "P1", "ZZ", "4", "0", "f", "b"),      # orphan sku
            ("2025-01-06", "P9", "A", "4", "0", "f", "b"),       # orphan plant
            ("2025-13-40", "P1", "A", "4", "0", "f", "b"),       # bad date
            (None, "P1", "A", "4", "0", "f", "b")]               # null key
    df = spark.createDataFrame(rows, cols).withColumn("_ingested_at", F.current_timestamp())
    skus = spark.createDataFrame([("A",)], ["sku_id"])
    plants = spark.createDataFrame([("P1",)], ["plant_id"])
    good, bad = silver.clean_demand(df, skus, plants)
    assert good.count() == 1
    reasons = {r["reason"]: r["n"] for r in bad.groupBy("reason").agg(F.count("*").alias("n")).collect()}
    assert reasons == {"duplicate": 1, "null_units": 1, "negative_units": 1, "units_out_of_range": 1,
                       "unknown_sku": 1, "unknown_plant": 1, "invalid_date": 1, "null_key": 1}


def test_negative_adjustment_allowed_negative_receipt_not(spark):
    cols = ["movement_id", "movement_date", "plant_id", "sku_id", "movement_type", "quantity", "_source_file", "_batch_id"]
    rows = [("1", "2025-01-01", "P1", "A", "ADJUSTMENT", "-4", "f", "b"),
            ("2", "2025-01-01", "P1", "A", "RECEIPT", "-4", "f", "b"),
            ("3", "2025-01-01", "P1", "A", "ISSUE", "7", "f", "b")]
    df = spark.createDataFrame(rows, cols).withColumn("_ingested_at", F.current_timestamp())
    good, bad = silver.clean_movements(df, spark.createDataFrame([("A",)], ["sku_id"]),
                                       spark.createDataFrame([("P1",)], ["plant_id"]))
    assert {r["movement_id"] for r in good.collect()} == {"1", "3"}
    assert bad.collect()[0]["reason"] == "negative_quantity"


def test_capacity_rules(spark):
    cols = ["capacity_date", "plant_id", "line_id", "available_hours", "run_hours", "downtime_hours",
            "units_produced", "_source_file", "_batch_id"]
    rows = [("2025-01-01", "P1", "L1", "16", "10", "1", "100", "f", "b"),
            ("2025-01-02", "P1", "L1", "16", "20", "1", "100", "f", "b"),
            ("2025-01-03", "P1", "L1", "16", "10", "-1", "100", "f", "b"),
            ("2025-01-04", "P1", "LX", "16", "10", "1", "100", "f", "b")]
    df = spark.createDataFrame(rows, cols).withColumn("_ingested_at", F.current_timestamp())
    good, bad = silver.clean_capacity(df, spark.createDataFrame([("L1",)], ["line_id"]))
    assert good.count() == 1
    assert {r["reason"] for r in bad.collect()} == {"run_exceeds_available", "negative_hours", "unknown_line"}


def test_gold_tables(mini_env):
    lake = mini_env["lake"]
    inv = pd.read_parquet(lake / "gold" / "inventory_position")
    assert set(inv["stockout_risk"]) <= {"HIGH", "MEDIUM", "LOW"}
    assert (inv["on_hand"] >= 0).all()
    high = inv[inv["stockout_risk"] == "HIGH"]
    assert (high["days_of_cover"] < high["lead_time_days"]).all()
    low = inv[inv["stockout_risk"] == "LOW"].dropna(subset=["days_of_cover"])
    assert (low["on_hand"] >= low["reorder_point"]).all()
    cap = pd.read_parquet(lake / "gold" / "capacity_utilization")
    assert ((cap["utilization"] >= 0) & (cap["utilization"] <= 1)).all()
    dem = pd.read_parquet(lake / "gold" / "daily_demand")
    assert {"plant_name", "category", "volume_class"} <= set(dem.columns)


def test_pipeline_recovers_true_inventory_despite_dirty_movements(mini_env, tmp_path):
    """Clean and dirty generator runs share one RNG stream, so the clean run is the ground truth."""
    from aapurti.generator import generate
    generate(tmp_path, n_skus=6, start="2024-01-01", end="2025-03-31", corrupt=False)
    m = pd.read_json(tmp_path / "inventory_movements.jsonl", lines=True)
    o = pd.read_csv(tmp_path / "inventory_opening.csv").set_index(["plant_id", "sku_id"])["opening_qty"]
    m["s"] = m["quantity"].where(m["movement_type"] != "ISSUE", -m["quantity"])
    truth = o.add(m.groupby(["plant_id", "sku_id"])["s"].sum(), fill_value=0)
    gold = pd.read_parquet(mini_env["lake"] / "gold" / "inventory_position").set_index(["plant_id", "sku_id"])["on_hand"]
    pd.testing.assert_series_equal(gold.sort_index(), truth.sort_index().astype(float), check_names=False, check_dtype=False)
