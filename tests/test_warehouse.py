"""The Hive warehouse runs in a subprocess (Hive support must be set when the Spark session is first created, and the
shared test session has none). Every number from Spark SQL is checked against an independent pandas calculation."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def run(mini_env, tmp_path_factory):
    out = tmp_path_factory.mktemp("dw")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    p = subprocess.run([sys.executable, "-m", "aapurti.pipeline.warehouse", "--lake", str(mini_env["lake"]),
                        "--out", str(out), "--json"], capture_output=True, text=True, env=env, timeout=600)
    assert p.returncode == 0, p.stderr[-2000:]
    doc = json.loads(p.stdout.split("JSON_START")[1].split("JSON_END")[0])
    gold = pd.read_parquet(Path(mini_env["lake"]) / "gold" / "daily_demand")
    skus = pd.read_parquet(Path(mini_env["lake"]) / "silver" / "skus")
    return doc, gold, skus, out


def test_row_counts_match_gold(run):
    doc, gold, skus, _ = run
    assert doc["row_counts"]["fact_daily_demand"] == len(gold)
    assert doc["row_counts"]["dim_sku"] == len(skus)


def test_partitions_are_one_per_month(run):
    doc, gold, _, out = run
    months = sorted(pd.to_datetime(gold["demand_date"]).dt.strftime("%Y-%m").unique())
    assert doc["partitions"] == months
    assert (out / "warehouse" / "aapurti_dw.db" / "fact_daily_demand" / f"demand_month={months[0]}").is_dir()


def test_partition_pruning_in_physical_plan(run):
    doc, *_ = run
    pr = doc["pruning"]
    assert pr["uses_partition_filter"] is True
    assert pr["partitions_total"] > 1
    assert "PartitionFilters" in pr["scan"]


def test_monthly_growth_matches_pandas(run):
    doc, gold, *_ = run
    m = (gold.assign(demand_month=pd.to_datetime(gold["demand_date"]).dt.strftime("%Y-%m"))
         .groupby("demand_month")["units"].sum().sort_index())
    expected = (m.pct_change() * 100).round(1)
    got = pd.DataFrame(doc["queries"]["monthly_growth"]).set_index("demand_month")
    assert list(got.index) == list(m.index)
    assert got["units"].tolist() == m.tolist()
    assert pd.isna(got["growth_pct"].iloc[0])
    assert got["growth_pct"].iloc[1:].tolist() == pytest.approx(expected.iloc[1:].tolist(), abs=0.11)


def test_top_category_by_plant_matches_pandas(run):
    doc, gold, skus, _ = run
    j = gold.drop(columns=["category"]).merge(skus[["sku_id", "category"]], on="sku_id")
    per = j.groupby(["plant_id", "category"])["units"].sum().reset_index()
    best = per.loc[per.groupby("plant_id")["units"].idxmax()].set_index("plant_id")
    total = per.groupby("plant_id")["units"].sum()
    got = {r["plant_id"]: r for r in doc["queries"]["top_category_by_plant"]}
    assert set(got) == set(best.index)
    for plant, r in got.items():
        assert r["category"] == best.loc[plant, "category"]
        assert r["units"] == best.loc[plant, "units"]
        assert r["share_pct"] == pytest.approx(100 * best.loc[plant, "units"] / total[plant], abs=0.06)


def test_rolling_average_matches_pandas(run):
    doc, gold, *_ = run
    first_plant = sorted(gold["plant_id"].unique())[0]
    s = (gold[gold["plant_id"] == first_plant].groupby("demand_date")["units"].sum().sort_index())
    expected = s.rolling(7, min_periods=1).mean().round(2)
    got = pd.DataFrame(doc["queries"]["rolling_7d_avg"])
    assert len(got) == len(s)
    assert got["avg_7d"].tolist() == pytest.approx(expected.tolist(), abs=0.011)
