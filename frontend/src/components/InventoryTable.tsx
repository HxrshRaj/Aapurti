import { useState } from "react";
import type { RiskRow } from "../api";
import { useFetch } from "../useFetch";
import Panel from "./Panel";

const fmt = (v: number | null, d = 0) => (v == null ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: d }));

export default function InventoryTable({ plantId }: { plantId: string }) {
  const [risk, setRisk] = useState("");
  const qs = new URLSearchParams({ limit: "25" });
  if (plantId) qs.set("plant_id", plantId);
  if (risk) qs.set("risk", risk);
  const { state, retry } = useFetch<{ rows: RiskRow[] }>(`/api/inventory/risk?${qs.toString()}`);

  return (
    <Panel
      title="Inventory risk"
      subtitle="HIGH: cover shorter than supplier lead time. MEDIUM: below reorder point."
      state={state}
      retry={retry}
      isEmpty={(d) => d.rows.length === 0}
      emptyText="No SKUs match this risk level at the selected plant."
      actions={
        <label className="inline">
          <span className="sr-only">Risk level</span>
          <select value={risk} onChange={(e) => setRisk(e.target.value)} aria-label="Risk level">
            <option value="">All risk levels</option>
            <option value="HIGH">High</option>
            <option value="MEDIUM">Medium</option>
            <option value="LOW">Low</option>
          </select>
        </label>
      }
    >
      {(d) => (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Plant</th>
                <th>SKU</th>
                <th>Category</th>
                <th className="r">On hand</th>
                <th className="r">Avg/day</th>
                <th className="r">Lead (d)</th>
                <th className="r">Days of cover</th>
                <th className="r">Reorder pt</th>
                <th>Risk</th>
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={`${r.plant_id}-${r.sku_id}`}>
                  <td>{r.plant_id}</td>
                  <td>{r.sku_id}</td>
                  <td>{r.category}</td>
                  <td className="r">{fmt(r.on_hand)}</td>
                  <td className="r">{fmt(r.avg_daily_demand, 1)}</td>
                  <td className="r">{r.lead_time_days}</td>
                  <td className="r">{fmt(r.days_of_cover, 1)}</td>
                  <td className="r">{fmt(r.reorder_point, 0)}</td>
                  <td>
                    <span className={`badge ${r.stockout_risk.toLowerCase()}`}>{r.stockout_risk}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
