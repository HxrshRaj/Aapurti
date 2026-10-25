"""End-to-end batch run: generate -> Spark pipeline -> forecasting -> reconcile -> serving DB + Power BI exports."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aapurti import config, serving  # noqa: E402
from aapurti.forecasting.run import run_forecasting  # noqa: E402
from aapurti.generator import generate  # noqa: E402
from aapurti.pipeline.run import run_pipeline  # noqa: E402
from aapurti.validation.reconcile import reconcile, to_markdown  # noqa: E402


def main(fmt: str = "parquet") -> None:
    config.REPORTS_DIR.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    gen = generate(config.RAW_DIR)
    gen_s = time.perf_counter() - t0
    (config.REPORTS_DIR / "generator.json").write_text(json.dumps({**gen, "seconds": round(gen_s, 1)}, indent=2))

    res = run_pipeline(config.RAW_DIR, config.LAKE_DIR, fmt)
    (config.REPORTS_DIR / "pipeline_run.json").write_text(json.dumps(res, indent=2))

    fc = run_forecasting(config.LAKE_DIR)
    (config.REPORTS_DIR / "forecast_run.json").write_text(json.dumps(fc, indent=2, default=str))

    rec = reconcile(config.RAW_DIR, config.LAKE_DIR)
    (config.REPORTS_DIR / "reconciliation.json").write_text(json.dumps(rec, indent=2))
    (config.REPORTS_DIR / "reconciliation.md").write_text(to_markdown(rec) + "\n")

    tables = serving.build_tables(config.LAKE_DIR)
    serving.write_sqlite(tables, config.DB_PATH)
    serving.write_powerbi(tables, config.ROOT / "powerbi" / "data")
    print(json.dumps({"pipeline": res["timings_s"], "forecast_s": fc["seconds"], "reconciled": rec["all_ok"]}, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "parquet")
