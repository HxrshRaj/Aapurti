"""Databricks notebooks import real modules; Power BI exports and DAX stay consistent with the model."""
import ast
import importlib
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def test_databricks_notebooks_are_valid_source_format_and_imports_resolve():
    nbs = sorted((ROOT / "databricks").glob("*.py"))
    assert len(nbs) >= 5
    for nb in nbs:
        text = nb.read_text()
        assert text.startswith("# Databricks notebook source"), nb
        assert text.count("# COMMAND ----------") >= 1, nb
        code = "\n".join(l for l in text.splitlines() if not l.startswith("# MAGIC"))
        for node in ast.walk(ast.parse(code)):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("aapurti"):
                mod = importlib.import_module(node.module)
                for alias in node.names:
                    if not hasattr(mod, alias.name):          # `from pkg import submodule`
                        importlib.import_module(f"{node.module}.{alias.name}")


def test_powerbi_exports_form_a_valid_star_schema(mini_env):
    from aapurti import serving
    tables = serving.build_tables(mini_env["lake"], mini_env["reports"])
    names = serving.write_powerbi(tables, mini_env["raw"].parent / "pbi")
    out = mini_env["raw"].parent / "pbi"
    assert set(names) >= {"dim_date", "dim_plant", "dim_sku", "fact_daily_demand", "fact_forecast"}
    dates = set(pd.read_csv(out / "dim_date.csv")["date"])
    assert set(pd.read_csv(out / "fact_daily_demand.csv")["demand_date"]) <= dates
    assert set(pd.read_csv(out / "fact_capacity_monthly.csv")["month_start"]) <= dates
    skus = set(pd.read_csv(out / "dim_sku.csv")["sku_id"])
    for f, col in (("fact_daily_demand", "sku_id"), ("fact_inventory_position", "sku_id"), ("fact_forecast", "sku_id")):
        assert set(pd.read_csv(out / f"{f}.csv")[col]) <= skus
    plants = set(pd.read_csv(out / "dim_plant.csv")["plant_id"])
    assert set(pd.read_csv(out / "fact_forecast.csv")["plant_id"]) <= plants


def test_dax_references_only_exported_columns():
    dax = (ROOT / "powerbi" / "measures.dax").read_text()
    from aapurti import serving  # noqa: F401  (columns come from the committed export headers)
    data = ROOT / "powerbi" / "data"
    if not data.exists():
        return
    cols = {f.stem: set(pd.read_csv(f, nrows=1).columns) for f in data.glob("*.csv")}
    for table, col in re.findall(r"(\w+)\[(\w+)\]", dax):
        assert table in cols, table
        assert col in cols[table], (table, col)
    for m in ("Forecast WAPE", "Days of Cover", "Stockout Risk %", "Utilization", "Units YoY %", "Forecast Accuracy"):
        assert f"{m} =" in dax
