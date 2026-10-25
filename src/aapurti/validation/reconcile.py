"""Source-to-gold reconciliation, computed with pandas independently of Spark."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

SIGN = {"RECEIPT": 1, "ISSUE": -1, "ADJUSTMENT": 1}


def _read(lake: Path, layer: str, name: str) -> pd.DataFrame:
    return pd.read_parquet(lake / layer / name)


def _quarantined(q: pd.DataFrame, table: str) -> pd.DataFrame:
    sub = q[q["source_table"] == table]
    if not len(sub):
        return pd.DataFrame()
    rec = pd.DataFrame([json.loads(x) for x in sub["record"]])
    rec["reason"] = sub["reason"].to_numpy()
    return rec


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0)


def _net(df: pd.DataFrame) -> float:
    if not len(df):
        return 0.0
    return float((_num(df["quantity"]) * df["movement_type"].map(SIGN).fillna(0)).sum())


def reconcile(raw_dir, lake_dir) -> dict:
    raw, lake = Path(raw_dir), Path(lake_dir)
    q = _read(lake, "silver", "quarantine")
    checks: list[dict] = []

    def add(name, source, pipeline, quarantined, tol=0.0, note=""):
        variance = source - pipeline - quarantined
        checks.append({"check": name, "source": float(source), "pipeline": float(pipeline),
                       "quarantined": float(quarantined), "unexplained_variance": float(variance),
                       "ok": bool(abs(variance) <= tol), "note": note})

    raw_demand = pd.read_csv(raw / "demand_daily.csv", dtype=str)
    raw_cap = pd.read_csv(raw / "machine_capacity.csv", dtype=str)
    raw_mov = pd.read_json(raw / "inventory_movements.jsonl", lines=True, dtype=False)

    # Row counts: every source row is either in silver or in quarantine.
    for tbl, src in (("demand_daily", raw_demand), ("machine_capacity", raw_cap), ("inventory_movements", raw_mov)):
        add(f"rows: {tbl}", len(src), len(_read(lake, "silver", tbl)), int((q["source_table"] == tbl).sum()),
            note=f"bronze rows = {len(_read(lake, 'bronze', tbl))}; source rows = silver rows + quarantined rows")

    # Demand units: source total = gold total + units sitting in quarantined rows.
    gold_d = _read(lake, "gold", "daily_demand")
    qd = _quarantined(q, "demand_daily")
    q_units = _num(qd["units"]).sum() if len(qd) else 0.0
    add("demand units (total)", _num(raw_demand["units"]).sum(), gold_d["units"].sum(), q_units,
        note="source = gold + units in quarantined rows (duplicates, orphans, negatives, out-of-range)")
    by_reason = qd.assign(u=_num(qd["units"])).groupby("reason")["u"].sum().to_dict() if len(qd) else {}

    # Movements: signed net quantity.
    silver_m = _read(lake, "silver", "inventory_movements")
    qm = _quarantined(q, "inventory_movements")
    add("inventory net movement (units)", _net(raw_mov), _net(silver_m), _net(qm),
        note="rows with an unrecognised movement type contribute 0 to the signed net on both sides")

    # Capacity hours.
    cap_gold = _read(lake, "gold", "capacity_utilization")
    qc = _quarantined(q, "machine_capacity")
    add("capacity run_hours", _num(raw_cap["run_hours"]).sum(), cap_gold["run_hours"].sum(),
        _num(qc["run_hours"]).sum() if len(qc) else 0.0, tol=1e-6,
        note="source = gold + hours in quarantined rows (run>available, negatives, duplicates)")

    # Inventory position recomputed independently in pandas.
    inv = _read(lake, "gold", "inventory_position").set_index(["plant_id", "sku_id"])
    opening = _read(lake, "silver", "inventory_opening").set_index(["plant_id", "sku_id"])["opening_qty"]
    as_of = pd.Timestamp(inv["as_of_date"].iloc[0])
    sm = silver_m.assign(signed=lambda d: d["quantity"].where(d["movement_type"] != "ISSUE", -d["quantity"]))
    netq = sm[pd.to_datetime(sm["movement_date"]) <= as_of].groupby(["plant_id", "sku_id"])["signed"].sum()
    expected_oh = opening.add(netq, fill_value=0).reindex(inv.index)
    diff = float((inv["on_hand"] - expected_oh).abs().sum())
    checks.append({"check": "inventory on_hand (gold vs pandas recompute)", "source": float(expected_oh.sum()),
                   "pipeline": float(inv["on_hand"].sum()), "quarantined": 0.0, "unexplained_variance": diff,
                   "ok": diff < 1e-6, "note": "opening + signed movements up to as-of, recomputed with pandas"})

    d28 = gold_d[pd.to_datetime(gold_d["demand_date"]) > as_of - pd.Timedelta(days=28)]
    exp_avg = (d28.groupby(["plant_id", "sku_id"])["units"].sum() / 28).reindex(inv.index).fillna(0)
    diff = float((inv["avg_daily_demand"] - exp_avg).abs().sum())
    checks.append({"check": "avg daily demand 28d (gold vs pandas recompute)", "source": float(exp_avg.sum()),
                   "pipeline": float(inv["avg_daily_demand"].sum()), "quarantined": 0.0, "unexplained_variance": diff,
                   "ok": diff < 1e-6, "note": "sum of units in trailing 28 days / 28"})

    return {"checks": checks, "all_ok": all(c["ok"] for c in checks),
            "quarantined_units_by_reason": {k: float(v) for k, v in by_reason.items()},
            "quarantine_rows_by_reason": q.groupby(["source_table", "reason"]).size().rename("rows")
                                           .reset_index().to_dict("records")}


def to_markdown(rec: dict) -> str:
    lines = ["| Check | Source | Pipeline | Quarantined | Unexplained variance | OK |",
             "|---|---:|---:|---:|---:|:--:|"]
    for c in rec["checks"]:
        lines.append(f"| {c['check']} | {c['source']:,.2f} | {c['pipeline']:,.2f} | {c['quarantined']:,.2f} | "
                     f"{c['unexplained_variance']:,.4f} | {'yes' if c['ok'] else 'NO'} |")
    return "\n".join(lines)
