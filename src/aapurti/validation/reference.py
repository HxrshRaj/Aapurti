"""Compares calcs.py and the Spark pipeline output with the hand-computed values in reference/."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .. import calcs
from ..config import ROOT

REF_DIR = ROOT / "reference"


def _parse_inputs(s: str) -> dict[str, float]:
    return {k: float(v) for k, v in (kv.split("=") for kv in s.split(";"))}


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def check_calcs(ref_path: Path | None = None) -> list[dict]:
    """Approved calculation cases vs the pure-Python implementations."""
    ref = pd.read_csv(ref_path or REF_DIR / "approved_calculations.csv", dtype=str, keep_default_na=False)
    out = []
    for r in ref.itertuples():
        i = _parse_inputs(r.inputs)
        if r.metric == "days_of_cover":
            got = calcs.days_of_cover(i["on_hand"], i["avg_daily_demand"])
        elif r.metric == "safety_stock":
            got = calcs.safety_stock(i["sigma"], i["lead_time_days"], i["z"])
        elif r.metric == "utilization":
            got = calcs.utilization(i["run_hours"], i["available_hours"])
        elif r.metric == "stockout_risk":
            got = calcs.stockout_risk(i["on_hand"], i["avg_daily_demand"], i["lead_time_days"], i["reorder_point"])
        else:
            raise ValueError(r.metric)
        exp = r.expected if r.expected != "" else None
        if exp is None:
            ok = got is None
        elif _is_number(exp):
            ok = got is not None and abs(got - float(exp)) <= float(r.tolerance)
        else:
            ok = got == exp
        out.append({"metric": r.metric, "case_id": r.case_id, "expected": exp, "actual": got,
                    "tolerance": r.tolerance, "ok": bool(ok)})
    return out


def check_fixture(lake_dir, expected_path: Path | None = None) -> list[dict]:
    """Pipeline gold/quarantine output on the fixture dataset vs hand-computed expectations."""
    lake = Path(lake_dir)
    exp = pd.read_csv(expected_path or REF_DIR / "fixture_expected.csv", dtype=str, keep_default_na=False)
    inv = pd.read_parquet(lake / "gold" / "inventory_position").assign(key=lambda d: d.plant_id + "|" + d.sku_id)
    cap = pd.read_parquet(lake / "gold" / "capacity_utilization").assign(key=lambda d: d.month + "|" + d.line_id)
    q = pd.read_parquet(lake / "silver" / "quarantine").groupby(["source_table", "reason"]).size()
    out = []
    for r in exp.itertuples():
        if r.table == "inventory_position":
            got = inv.set_index("key").loc[r.key, r.field]
        elif r.table == "capacity_utilization":
            got = cap.set_index("key").loc[r.key, r.field]
        else:
            t, reason = r.key.split("|")
            got = q.get((t, reason), 0)
        if r.expected == "":
            ok = got is None or pd.isna(got)
        elif _is_number(r.expected):
            ok = (not pd.isna(got)) and abs(float(got) - float(r.expected)) <= float(r.tolerance)
        else:
            ok = got == r.expected
        out.append({"table": r.table, "key": r.key, "field": r.field, "expected": r.expected or None,
                    "actual": None if (not isinstance(got, str) and pd.isna(got)) else got, "ok": bool(ok)})
    return out
