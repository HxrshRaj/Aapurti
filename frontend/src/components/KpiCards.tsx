import type { Kpis } from "../api";
import { useFetch } from "../useFetch";

const pct = (v: number | null, d = 1) => (v == null ? "n/a" : `${(v * 100).toFixed(d)}%`);
const num = (v: number | null, d = 0) => (v == null ? "n/a" : v.toLocaleString("en-IN", { maximumFractionDigits: d }));

export default function KpiCards() {
  const { state, retry } = useFetch<Kpis>("/api/kpis");

  if (state.status === "loading")
    return (
      <div className="kpis" role="status" aria-live="polite" aria-label="Loading KPIs">
        {[0, 1, 2, 3, 4].map((i) => (
          <div className="kpi skeleton" key={i} />
        ))}
      </div>
    );
  if (state.status === "error")
    return (
      <div className="card state error" role="alert">
        <p>Could not load KPIs.</p>
        <p className="muted small">{state.error}</p>
        <button type="button" onClick={retry}>
          Retry
        </button>
      </div>
    );
  const k = state.data;
  const items = [
    { label: "Forecast accuracy (1 − WAPE)", value: pct(k.forecast_accuracy), note: `last 28 days, WAPE ${pct(k.forecast_wape)}` },
    { label: "Stockout risk", value: `${k.high_risk_skus} high`, note: `${k.medium_risk_skus} medium of ${k.tracked_sku_plants} SKU-plants`, tone: k.high_risk_skus > 0 ? "bad" : "ok" },
    { label: "Avg days of cover", value: num(k.avg_days_of_cover, 1), note: `as of ${k.as_of}` },
    { label: "Capacity utilization", value: pct(k.utilization_latest_month), note: k.utilization_month },
    { label: "Demand, last 30 days", value: num(k.units_last_30d), note: `units · quarantined rows ${pct(k.dq_quarantine_rate, 2)}` },
  ];
  return (
    <div className="kpis">
      {items.map((i) => (
        <div className={`kpi ${i.tone ?? ""}`} key={i.label}>
          <span className="kpi-label">{i.label}</span>
          <strong className="kpi-value">{i.value}</strong>
          <span className="muted small">{i.note}</span>
        </div>
      ))}
    </div>
  );
}
