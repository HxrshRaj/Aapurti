"""Delta Lake support behind --format delta. Runs in a subprocess (separate SparkSession with the Delta jars)."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(importlib.util.find_spec("delta") is None, reason="delta-spark not installed")

SCRIPT = """
import json, sys
from aapurti.pipeline.run import run_pipeline
print("RESULT" + json.dumps(run_pipeline(sys.argv[1], sys.argv[2], "delta")["counts"]))
"""


def test_pipeline_writes_delta_tables(tmp_path):
    out = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT / "reference" / "fixture"), str(tmp_path)],
                         capture_output=True, text=True, cwd=ROOT, timeout=600,
                         env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")})
    assert out.returncode == 0, out.stderr[-2000:]
    counts = json.loads(out.stdout.split("RESULT")[1].splitlines()[0])
    assert (tmp_path / "gold" / "inventory_position" / "_delta_log").is_dir()
    assert (tmp_path / "silver" / "quarantine" / "_delta_log").is_dir()
    assert counts["gold.inventory_position"] == 4
    assert counts["silver.quarantine"] == 6      # same quarantine total as the parquet fixture run
