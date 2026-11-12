"""Structured Streaming windows/watermark/restart behaviour and join-strategy plans, run on the shared local Spark session."""

import pytest

from aapurti.pipeline.plans import compare_join_strategies
from aapurti.pipeline.streaming import WindowStore, drain


def _write(path, rows):
    header = "movement_id,event_time,plant_id,sku_id,movement_type,quantity\n"
    path.write_text(header + "".join(",".join(map(str, r)) + "\n" for r in rows))


def _by_key(store):
    return {(r["window_start"][11:16], r["plant_id"], r["movement_type"]): (r["events"], r["total_quantity"])
            for r in store.as_list()}


@pytest.fixture()
def dirs(tmp_path):
    inp = tmp_path / "in"
    inp.mkdir()
    return inp, tmp_path / "ckpt"


def test_tumbling_windows_count_and_sum_per_key(spark, dirs):
    inp, ckpt = dirs
    _write(inp / "a.csv", [
        ("m1", "2025-01-01 10:01:00", "P1", "S1", "receipt", 5),
        ("m2", "2025-01-01 10:30:00", "P1", "S2", "receipt", 7),
        ("m3", "2025-01-01 10:45:00", "P1", "S1", "issue", 2),
        ("m4", "2025-01-01 11:05:00", "P1", "S1", "receipt", 4),   # next window
        ("m5", "2025-01-01 10:10:00", "P2", "S1", "receipt", 9),   # other plant
    ])
    store = WindowStore()
    drain(spark, inp, ckpt, store)
    got = _by_key(store)
    assert got[("10:00", "P1", "receipt")] == (2, 12.0)
    assert got[("10:00", "P1", "issue")] == (1, 2.0)
    assert got[("11:00", "P1", "receipt")] == (1, 4.0)
    assert got[("10:00", "P2", "receipt")] == (1, 9.0)
    assert len(got) == 4


def test_new_file_updates_an_open_window_without_double_counting(spark, dirs):
    inp, ckpt = dirs
    store = WindowStore()
    _write(inp / "a.csv", [("m1", "2025-01-01 10:01:00", "P1", "S1", "receipt", 5)])
    drain(spark, inp, ckpt, store)
    _write(inp / "b.csv", [("m2", "2025-01-01 10:05:00", "P1", "S1", "receipt", 3)])
    drain(spark, inp, ckpt, store)
    assert _by_key(store)[("10:00", "P1", "receipt")] == (2, 8.0)


def test_late_event_after_watermark_is_dropped_and_survives_restart(spark, dirs):
    inp, ckpt = dirs
    store = WindowStore()
    _write(inp / "a.csv", [("m1", "2025-01-01 10:03:00", "P1", "S1", "receipt", 5)])
    drain(spark, inp, ckpt, store)
    # A much later event moves the watermark to about 11:50 (12:00 minus the 10 minute delay).
    _write(inp / "b.csv", [("m2", "2025-01-01 12:00:00", "P1", "S1", "receipt", 1)])
    drain(spark, inp, ckpt, store)
    # Same process, new run: the late 10:03 event must be ignored because the watermark came from the checkpoint.
    _write(inp / "c.csv", [("m3", "2025-01-01 10:04:00", "P1", "S1", "receipt", 100)])
    drain(spark, inp, ckpt, store)
    got = _by_key(store)
    assert got[("10:00", "P1", "receipt")] == (1, 5.0)       # unchanged: the late 100 was dropped
    assert got[("12:00", "P1", "receipt")] == (1, 1.0)


def test_event_inside_the_watermark_delay_is_still_accepted(spark, dirs):
    inp, ckpt = dirs
    store = WindowStore()
    _write(inp / "a.csv", [("m1", "2025-01-01 10:20:00", "P1", "S1", "receipt", 5)])
    drain(spark, inp, ckpt, store)
    # 10:15 is only 5 minutes behind the newest event (10:20), inside the 10 minute delay.
    _write(inp / "b.csv", [("m2", "2025-01-01 10:15:00", "P1", "S1", "receipt", 2)])
    drain(spark, inp, ckpt, store)
    assert _by_key(store)[("10:00", "P1", "receipt")] == (2, 7.0)


def test_join_strategies_differ_in_work_but_agree_on_results(spark):
    big = spark.range(0, 20000).selectExpr("id AS row_id", "CAST(id % 50 AS STRING) AS sku_id", "CAST(id % 7 AS DOUBLE) AS units")
    small = spark.range(0, 50).selectExpr("CAST(id AS STRING) AS sku_id", "concat('cat', id % 5) AS category")
    broadcast, merge = compare_join_strategies(spark, big, small, "sku_id", "units")
    assert broadcast["strategy"] == "broadcast_hash"
    assert broadcast["shuffles"] == 0 and broadcast["broadcasts"] == 1
    assert merge["strategy"] == "sort_merge"
    assert merge["shuffles"] == 2 and merge["broadcasts"] == 0   # both sides are shuffled for a sort-merge join
    assert (broadcast["rows"], broadcast["total"]) == (merge["rows"], merge["total"]) == (20000, float(sum(i % 7 for i in range(20000))))


def test_join_report_restores_the_session_settings(spark):
    before = (spark.conf.get("spark.sql.adaptive.enabled"), spark.conf.get("spark.sql.autoBroadcastJoinThreshold"))
    big = spark.range(0, 100).selectExpr("CAST(id AS STRING) AS sku_id", "CAST(id AS DOUBLE) AS units")
    small = spark.range(0, 10).selectExpr("CAST(id AS STRING) AS sku_id")
    compare_join_strategies(spark, big, small, "sku_id", "units")
    assert (spark.conf.get("spark.sql.adaptive.enabled"), spark.conf.get("spark.sql.autoBroadcastJoinThreshold")) == before
