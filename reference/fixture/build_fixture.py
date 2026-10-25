"""Builds the tiny hand-designed fixture dataset used by the reference tests.
Expected results are hand-computed in reference/approved_calculations.csv and fixture_expected.csv
(see reference/README.md for the working). Fixture data is SYNTHETIC."""
import json
from datetime import date, timedelta
from pathlib import Path

out = Path(__file__).parent
out.mkdir(exist_ok=True)

def w(name, text):
    (out / name).write_text(text.strip() + "\n")

w("plants.csv", "plant_id,plant_name,region\nP01,Test Plant,West")
w("suppliers.csv", "supplier_id,supplier_name,lead_time_days,reliability\nSUP01,Test Supplier,4,0.95")
w("skus.csv", "sku_id,category,volume_class,unit_cost,supplier_id,sku_name\n"
              "SA,Valves,A,10,SUP01,Valve SA\nSB,Valves,B,20,SUP01,Valve SB\n"
              "SC,Pumps,C,5,SUP01,Pump SC\nSD,Pumps,B,8,SUP01,Pump SD")
w("lines.csv", "line_id,plant_id,rated_units_per_hour\nP01-L1,P01,60")
w("inventory_opening.csv", "plant_id,sku_id,opening_qty\nP01,SA,400\nP01,SB,100\nP01,SC,50\nP01,SD,75")

days = [date(2025, 12, 4) + timedelta(days=i) for i in range(28)]   # 2025-12-04 .. 2025-12-31
dem = ["demand_date,plant_id,sku_id,units,promo_flag"]
for i, d in enumerate(days):
    alt = 8 if i % 2 == 0 else 12
    dem += [f"{d},P01,SA,10,0", f"{d},P01,SB,{alt},0", f"{d},P01,SC,0,0", f"{d},P01,SD,{alt},0"]
dem += ["2025-11-30,P01,SA,-5,0",          # negative -> quarantine negative_units
        f"{days[0]},P01,SA,10,0",          # duplicate of SA on 2025-12-04 -> quarantine duplicate
        "2025-12-10,P01,SX,7,0"]           # orphan SKU -> quarantine unknown_sku
w("demand_daily.csv", "\n".join(dem))

mv = []
def m(i, d, sku, typ, q):
    mv.append({"movement_id": f"M{i:03d}", "movement_date": str(d), "plant_id": "P01", "sku_id": sku,
               "movement_type": typ, "quantity": q})
i = 0
for d in days:                              # daily issues equal to demand
    for sku, base in (("SA", 10), ("SB", None), ("SD", None)):
        i += 1
        k = days.index(d)
        q = 10 if sku == "SA" else (8 if k % 2 == 0 else 12)
        m(i, d, sku, "ISSUE", q)
i += 1; m(i, date(2025, 12, 10), "SA", "RECEIPT", 200)
i += 1; m(i, date(2025, 12, 15), "SA", "ADJUSTMENT", -20)
i += 1; m(i, date(2025, 12, 5), "SB", "RECEIPT", 200)
i += 1; m(i, date(2025, 12, 5), "SD", "RECEIPT", 250)
i += 1; m(i, date(2026, 1, 2), "SB", "RECEIPT", 500)   # after as-of date: must NOT count
lines = [json.dumps(r) for r in mv]
lines.append(json.dumps(mv[0]))                         # duplicate movement_id -> quarantine duplicate
(out / "inventory_movements.jsonl").write_text("\n".join(lines) + "\n")

cap = ["capacity_date,plant_id,line_id,available_hours,run_hours,downtime_hours,units_produced"]
for d, run, down in (("2025-12-01", 18, 0), ("2025-12-02", 12, 2), ("2025-12-03", 24, 0), ("2025-12-04", 6, 1)):
    cap.append(f"{d},P01,P01-L1,24,{run},{down},{run * 50}")
cap.append("2025-12-05,P01,P01-L1,24,30,0,0")        # run > available -> quarantine run_exceeds_available
cap.append("2025-12-01,P01,P01-L1,24,18,0,900")      # duplicate key -> quarantine duplicate
w("machine_capacity.csv", "\n".join(cap))
