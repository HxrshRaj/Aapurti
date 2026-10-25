import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(scope="session")
def spark():
    from aapurti.pipeline.session import get_spark
    s = get_spark("aapurti-tests", shuffle_partitions=2)
    s.sparkContext.setLogLevel("ERROR")
    yield s
    s.stop()


@pytest.fixture(scope="session")
def fixture_lake(spark, tmp_path_factory):
    """Pipeline run over the hand-designed reference fixture."""
    from aapurti.pipeline.run import run_pipeline
    lake = tmp_path_factory.mktemp("fixture_lake")
    run_pipeline(ROOT / "reference" / "fixture", lake, spark=spark)
    return lake


@pytest.fixture(scope="session")
def mini_env(spark, tmp_path_factory):
    """Small end-to-end environment: generate -> Spark pipeline -> forecasting -> reconcile -> SQLite."""
    from aapurti import serving
    from aapurti.forecasting.run import run_forecasting
    from aapurti.generator import generate
    from aapurti.pipeline.run import run_pipeline
    from aapurti.validation.reconcile import reconcile

    base = tmp_path_factory.mktemp("mini")
    raw, lake, reports = base / "raw", base / "lake", base / "reports"
    reports.mkdir()
    gen = generate(raw, n_skus=6, start="2024-01-01", end="2025-03-31")
    run_pipeline(raw, lake, spark=spark)
    run_forecasting(lake, n_origins=2)
    rec = reconcile(raw, lake)
    (reports / "reconciliation.json").write_text(json.dumps(rec))
    db = base / "aapurti.db"
    serving.write_sqlite(serving.build_tables(lake, reports), db)
    return {"raw": raw, "lake": lake, "db": db, "reconciliation": rec, "gen": gen, "reports": reports}
