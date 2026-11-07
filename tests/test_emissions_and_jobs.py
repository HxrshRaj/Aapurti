import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from aapurti import emissions, ml_forecast


@pytest.fixture()
def client(mini_env, monkeypatch):
    monkeypatch.setenv("AAPURTI_DB", str(mini_env["db"]))
    from aapurti.api.main import app
    return TestClient(app)


def test_estimate_arithmetic():
    df = pd.DataFrame({"category": ["Motors", "Gaskets"], "units": [100, 1000]})
    out = emissions.estimate(df, transport_km=200).set_index("category")
    assert out.loc["Motors", "production_kg"] == pytest.approx(100 * 21.0)
    assert out.loc["Motors", "transport_kg"] == pytest.approx(100 * 200 * 0.0005)
    assert out.loc["Gaskets", "total_kg"] == pytest.approx(1000 * 0.9 + 1000 * 200 * 0.0005)
    assert list(out.index) == ["Motors", "Gaskets"]   # sorted by total desc


def test_unknown_category_uses_default_and_zero_units_have_no_per_unit():
    out = emissions.estimate(pd.DataFrame({"category": ["Mystery", "Pumps"], "units": [10, 0]}))
    assert out.loc[out.category == "Mystery", "production_kg"].iloc[0] == pytest.approx(10 * emissions.DEFAULT_PRODUCTION_FACTOR)
    assert np.isnan(out.loc[out.category == "Pumps", "kg_per_unit"].iloc[0])


def test_negative_distance_rejected():
    with pytest.raises(ValueError):
        emissions.estimate(pd.DataFrame({"category": ["Pumps"], "units": [1]}), transport_km=-1)


def test_emissions_endpoint(client):
    j = client.get("/api/emissions", params={"days": 60, "transport_km": 100}).json()
    assert j["by_category"] and j["total_kg_co2e"] == pytest.approx(sum(r["total_kg"] for r in j["by_category"]))
    assert "Illustrative" in j["notice"]
    far = client.get("/api/emissions", params={"days": 60, "transport_km": 5000}).json()
    assert far["total_kg_co2e"] > j["total_kg_co2e"]
    assert client.get("/api/emissions", params={"transport_km": -5}).status_code == 422


def _series(n=200):
    dates = pd.date_range("2024-01-01", periods=n).strftime("%Y-%m-%d").tolist()
    rng = np.random.default_rng(0)
    units = (100 + 20 * np.sin(np.arange(n) * 2 * np.pi / 7) + rng.normal(0, 2, n)).tolist()
    return dates, units


def test_ml_forecast_shape_and_quality():
    dates, units = _series()
    out = ml_forecast.forecast_series(dates[:-14], units[:-14], 14)
    assert len(out["forecast"]) == 14 and out["dates"][0] == dates[-14]
    actual = np.array(units[-14:])
    ml_err = np.abs(actual - np.array(out["forecast"])).mean()
    assert ml_err < 15          # tracks the weekly pattern (amplitude is 20)


def test_ml_forecast_validation():
    dates, units = _series(30)
    with pytest.raises(ValueError):
        ml_forecast.forecast_series(dates, units, 7)
    d2, u2 = _series()
    with pytest.raises(ValueError):
        ml_forecast.forecast_series(d2, u2, 0)


def test_job_lifecycle(client):
    f = client.get("/api/filters").json()["skus"][0]
    r = client.post("/api/forecast/jobs", params={"sku_id": f["sku_id"], "plant_id": f["plant_id"], "horizon": 7})
    assert r.status_code == 202
    job = client.get(f"/api/forecast/jobs/{r.json()['id']}").json()
    assert job["status"] == "done", job      # TestClient runs background tasks before returning
    assert len(job["result"]["forecast"]) == 7 and all(v >= 0 for v in job["result"]["forecast"])


def test_job_errors(client):
    assert client.post("/api/forecast/jobs", params={"sku_id": "NOPE", "plant_id": "P01"}).status_code == 404
    assert client.get("/api/forecast/jobs/doesnotexist").status_code == 404
    f = client.get("/api/filters").json()["skus"][0]
    assert client.post("/api/forecast/jobs", params={"sku_id": f["sku_id"], "plant_id": f["plant_id"], "horizon": 500}).status_code == 422
