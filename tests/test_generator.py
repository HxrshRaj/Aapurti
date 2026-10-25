import hashlib

import pandas as pd

from aapurti.generator import generate


def _digest(d):
    return {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in sorted(d.iterdir())}


def test_generator_is_deterministic(tmp_path):
    generate(tmp_path / "a", n_skus=5, start="2024-01-01", end="2024-03-31")
    generate(tmp_path / "b", n_skus=5, start="2024-01-01", end="2024-03-31")
    assert _digest(tmp_path / "a") == _digest(tmp_path / "b")


def test_different_seed_differs(tmp_path):
    generate(tmp_path / "a", seed=1, n_skus=5, start="2024-01-01", end="2024-02-29")
    generate(tmp_path / "b", seed=2, n_skus=5, start="2024-01-01", end="2024-02-29")
    assert _digest(tmp_path / "a")["demand_daily.csv"] != _digest(tmp_path / "b")["demand_daily.csv"]


def test_demand_has_weekly_seasonality_and_trend(tmp_path):
    generate(tmp_path, n_skus=8, start="2023-01-01", end="2024-12-31", corrupt=False)
    d = pd.read_csv(tmp_path / "demand_daily.csv", parse_dates=["demand_date"])
    d = d.groupby("demand_date")["units"].sum()
    by_dow = d.groupby(d.index.dayofweek).mean()
    assert by_dow.loc[:4].min() > by_dow.loc[6]
    assert d["2024"].sum() > d["2023"].sum()


def test_clean_mode_has_no_bad_rows(tmp_path):
    generate(tmp_path, n_skus=5, start="2024-01-01", end="2024-03-31", corrupt=False)
    d = pd.read_csv(tmp_path / "demand_daily.csv")
    assert d["units"].notna().all() and (d["units"] >= 0).all() and not d.duplicated().any()


def test_corrupt_mode_injects_bad_rows(tmp_path):
    generate(tmp_path, n_skus=8, start="2024-01-01", end="2024-12-31", corrupt=True)
    d = pd.read_csv(tmp_path / "demand_daily.csv")
    assert d["units"].isna().any() and (d["units"] < 0).any() and d.duplicated().any()
    assert (d["sku_id"] == "S999").any()


def test_inventory_never_negative(tmp_path):
    generate(tmp_path, n_skus=6, start="2024-01-01", end="2024-06-30", corrupt=False)
    m = pd.read_json(tmp_path / "inventory_movements.jsonl", lines=True)
    o = pd.read_csv(tmp_path / "inventory_opening.csv").set_index(["plant_id", "sku_id"])["opening_qty"]
    m["s"] = m["quantity"].where(m["movement_type"] != "ISSUE", -m["quantity"])
    net = m.groupby(["plant_id", "sku_id"])["s"].sum()
    assert (o.add(net, fill_value=0) >= 0).all()
