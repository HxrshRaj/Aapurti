"""Seeded SYNTHETIC data generator: plants, SKUs, suppliers, demand, inventory movements, line capacity.

Raw files written (all synthetic):
  plants.csv, suppliers.csv, skus.csv, lines.csv, inventory_opening.csv,
  demand_daily.csv, inventory_movements.jsonl, machine_capacity.csv
A small, seeded fraction of rows is deliberately corrupted so the silver layer has something to quarantine.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import END_DATE, SEED, START_DATE

PLANTS = [("P01", "Pune"), ("P02", "Chennai"), ("P03", "Ahmedabad")]
CATEGORIES = ["Bearings", "Valves", "Pumps", "Motors", "Gaskets", "Filters"]
CLASS_LEVEL = {"A": (200, 400), "B": (60, 120), "C": (8, 25)}
WEEKLY = np.array([1.10, 1.12, 1.08, 1.05, 1.00, 0.70, 0.55])  # Mon..Sun


def _dims(rng: np.random.Generator, n_skus: int):
    plants = pd.DataFrame(PLANTS, columns=["plant_id", "plant_name"])
    plants["region"] = ["West", "South", "West"]

    suppliers = pd.DataFrame({
        "supplier_id": [f"SUP{i:02d}" for i in range(1, 9)],
        "supplier_name": [f"Synthetic Supplier {i}" for i in range(1, 9)],
        "lead_time_days": rng.integers(3, 22, 8),
        "reliability": np.round(rng.uniform(0.82, 0.99, 8), 3),
    })

    classes = rng.choice(["A", "B", "C"], n_skus, p=[0.25, 0.35, 0.40])
    skus = pd.DataFrame({
        "sku_id": [f"S{i:03d}" for i in range(1, n_skus + 1)],
        "category": rng.choice(CATEGORIES, n_skus),
        "volume_class": classes,
        "unit_cost": np.round(rng.uniform(3, 180, n_skus), 2),
        "supplier_id": rng.choice(suppliers["supplier_id"], n_skus),
    })
    skus["sku_name"] = skus["category"].str[:-1] + " " + skus["sku_id"]

    rows = []
    for _, s in skus.iterrows():
        n_p = 2 if rng.random() < 0.5 else 1
        for p in rng.choice(plants["plant_id"], n_p, replace=False):
            lo, hi = CLASS_LEVEL[s.volume_class]
            rows.append((s.sku_id, p, rng.uniform(lo, hi), rng.uniform(-0.15, 0.25),
                         rng.uniform(0.05, 0.30), rng.uniform(0, 2 * np.pi), rng.uniform(0.7, 1.3)))
    series = pd.DataFrame(rows, columns=["sku_id", "plant_id", "level", "trend", "annual_amp", "phase", "policy"])

    lines = pd.DataFrame([(f"{p}-L{j}", p, rng.choice([30, 45, 60, 90])) for p, _ in PLANTS for j in range(1, 4)],
                         columns=["line_id", "plant_id", "rated_units_per_hour"])
    lines["rated_units_per_hour"] = lines["rated_units_per_hour"].astype(int)
    return plants, suppliers, skus, series, lines


def _demand(rng, series, dates):
    n = len(dates)
    t = np.arange(n)
    dow = dates.dayofweek.values
    doy = dates.dayofyear.values
    # promo windows: ~4 per year per series, 5-7 days, uplift 1.4-2.0x
    out = []
    for r in series.itertuples():
        promo = np.zeros(n, dtype=int)
        for _ in range(int(rng.integers(8, 13))):
            s = int(rng.integers(0, n - 8))
            promo[s:s + int(rng.integers(5, 8))] = 1
        uplift = rng.uniform(1.4, 2.0)
        mean = (r.level * (1 + r.trend * t / 365.0) * WEEKLY[dow]
                * (1 + r.annual_amp * np.sin(2 * np.pi * doy / 365.25 + r.phase))
                * np.where(promo == 1, uplift, 1.0))
        units = rng.poisson(mean * rng.lognormal(0, 0.12, n))
        out.append(pd.DataFrame({"demand_date": dates, "plant_id": r.plant_id, "sku_id": r.sku_id,
                                 "units": units, "promo_flag": promo}))
    return pd.concat(out, ignore_index=True)


def _inventory(rng, series, skus, suppliers, demand):
    lt_map = skus.merge(suppliers, on="supplier_id").set_index("sku_id")["lead_time_days"].to_dict()
    opening, moves = [], []
    mid = 0
    for r in series.itertuples():
        d = demand[(demand.sku_id == r.sku_id) & (demand.plant_id == r.plant_id)]
        units = d["units"].to_numpy()
        dates = d["demand_date"].to_numpy()
        mean_d = units[:28].mean() + 1e-9
        lt = int(lt_map[r.sku_id])
        rop = mean_d * (lt + 7) * r.policy        # policy<1 => under-protected series
        order_up_to = rop + mean_d * 30
        on_hand = mean_d * 25
        opening.append((r.plant_id, r.sku_id, int(on_hand)))
        on_hand = int(on_hand)
        pipeline: list[tuple[int, int]] = []
        for i, u in enumerate(units):
            arrivals = [q for (day, q) in pipeline if day == i]
            pipeline = [(day, q) for (day, q) in pipeline if day != i]
            for q in arrivals:
                on_hand += q
                mid += 1
                moves.append((f"M{mid:08d}", dates[i], r.plant_id, r.sku_id, "RECEIPT", q))
            issue = min(int(u), on_hand)
            if issue:
                on_hand -= issue
                mid += 1
                moves.append((f"M{mid:08d}", dates[i], r.plant_id, r.sku_id, "ISSUE", issue))
            if i % 90 == 45 and on_hand > 10:    # periodic cycle-count adjustment
                adj = int(rng.integers(-5, 4))
                on_hand += adj
                mid += 1
                moves.append((f"M{mid:08d}", dates[i], r.plant_id, r.sku_id, "ADJUSTMENT", adj))
            on_order = sum(q for _, q in pipeline)
            if on_hand + on_order <= rop:
                qty = int(order_up_to - on_hand - on_order)
                arrive = i + lt + int(rng.integers(0, 3))
                if qty > 0:
                    pipeline.append((arrive, qty))
    opening = pd.DataFrame(opening, columns=["plant_id", "sku_id", "opening_qty"])
    moves = pd.DataFrame(moves, columns=["movement_id", "movement_date", "plant_id", "sku_id", "movement_type", "quantity"])
    return opening, moves


def _capacity(rng, lines, dates):
    rows = []
    dow = dates.dayofweek.values
    doy = dates.dayofyear.values
    for l in lines.itertuples():
        base = rng.uniform(0.55, 0.93)
        avail = np.where(dow < 5, 16.0, np.where(dow == 5, 8.0, 0.0))
        util = np.clip(base + 0.06 * np.sin(2 * np.pi * doy / 365.25) + rng.normal(0, 0.05, len(dates)), 0.2, 1.0)
        run = np.round(avail * util, 2)
        down = np.round(np.clip(avail * rng.uniform(0, 0.08, len(dates)), 0, avail), 2)
        rows.append(pd.DataFrame({
            "capacity_date": dates, "plant_id": l.plant_id, "line_id": l.line_id,
            "available_hours": avail, "run_hours": run, "downtime_hours": down,
            "units_produced": np.round(run * l.rated_units_per_hour * rng.uniform(0.9, 1.0, len(dates))).astype(int)}))
    return pd.concat(rows, ignore_index=True)


def _corrupt(rng, demand, moves, cap, rate=0.004):
    """Inject bad rows. Returns string-typed frames (CSV-ready)."""
    d = demand.copy()
    d["demand_date"] = d["demand_date"].dt.strftime("%Y-%m-%d")
    d = d.astype(object)
    n = len(d)
    idx = rng.choice(n, int(n * rate * 5), replace=False)
    k = len(idx) // 5
    d.loc[idx[:k], "units"] = None                         # null
    d.loc[idx[k:2 * k], "units"] = -rng.integers(1, 50, k)  # negative
    d.loc[idx[2 * k:3 * k], "units"] = 999_999              # out of range
    d.loc[idx[3 * k:4 * k], "sku_id"] = "S999"              # orphan
    d.loc[idx[4 * k:], "demand_date"] = "2024-13-45"        # bad date
    dupes = d.sample(int(n * rate), random_state=SEED)
    d = pd.concat([d, dupes], ignore_index=True)

    m = moves.copy()
    m["movement_date"] = pd.to_datetime(m["movement_date"]).dt.strftime("%Y-%m-%d")
    m = m.astype(object)
    # Ledger garbage is appended as *extra* rows (replays / malformed posts with fresh ids); the genuine
    # movements stay intact so on-hand can still be recovered exactly once the bad rows are quarantined.
    extra = m.iloc[rng.choice(len(m), int(len(m) * rate * 3), replace=False)].copy()
    extra["movement_id"] = "X" + extra["movement_id"].astype(str)
    h = len(extra) // 3
    extra.iloc[:h, extra.columns.get_loc("plant_id")] = "P99"
    extra.iloc[h:2 * h, extra.columns.get_loc("quantity")] = None
    extra.iloc[2 * h:, extra.columns.get_loc("movement_type")] = "TELEPORT"
    m = pd.concat([m, extra, m.sample(int(len(m) * rate), random_state=SEED)], ignore_index=True)

    c = cap.copy()
    c["capacity_date"] = c["capacity_date"].dt.strftime("%Y-%m-%d")
    c = c.astype(object)
    ci = rng.choice(len(c), 30, replace=False)
    c.loc[ci[:15], "run_hours"] = 30.0                      # run > available
    c.loc[ci[15:], "downtime_hours"] = -2.0                 # negative downtime
    return d, m, c


def generate(out_dir: Path, seed: int = SEED, n_skus: int = 48, start: str = START_DATE,
             end: str = END_DATE, corrupt: bool = True) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, end, freq="D")
    plants, suppliers, skus, series, lines = _dims(rng, n_skus)
    demand = _demand(rng, series, dates)
    opening, moves = _inventory(rng, series, skus, suppliers, demand)
    cap = _capacity(rng, lines, dates)
    clean = (demand, moves, cap)
    if corrupt:
        demand, moves, cap = _corrupt(rng, demand, moves, cap)
    else:
        demand = demand.assign(demand_date=demand["demand_date"].dt.strftime("%Y-%m-%d"))
        moves = moves.assign(movement_date=pd.to_datetime(moves["movement_date"]).dt.strftime("%Y-%m-%d"))
        cap = cap.assign(capacity_date=cap["capacity_date"].dt.strftime("%Y-%m-%d"))

    plants.to_csv(out_dir / "plants.csv", index=False)
    suppliers.to_csv(out_dir / "suppliers.csv", index=False)
    skus.to_csv(out_dir / "skus.csv", index=False)
    lines.to_csv(out_dir / "lines.csv", index=False)
    opening.to_csv(out_dir / "inventory_opening.csv", index=False)
    demand.to_csv(out_dir / "demand_daily.csv", index=False)
    cap.to_csv(out_dir / "machine_capacity.csv", index=False)
    with open(out_dir / "inventory_movements.jsonl", "w") as f:
        for rec in moves.to_dict("records"):
            f.write(json.dumps({k: (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v))
                                for k, v in rec.items()}) + "\n")
    return {"rows": {"demand": len(demand), "movements": len(moves), "capacity": len(cap),
                     "series": len(series)},
            "clean_demand_units": int(clean[0]["units"].sum())}
