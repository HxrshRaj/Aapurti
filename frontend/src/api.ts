export type Plant = { plant_id: string; plant_name: string };
export type SkuOption = { sku_id: string; sku_name: string; volume_class: string; plant_id: string };
export type Filters = { plants: Plant[]; skus: SkuOption[]; as_of: string; notice: string };

export type Kpis = {
  as_of: string;
  forecast_wape: number | null;
  forecast_accuracy: number | null;
  units_last_30d: number;
  avg_days_of_cover: number | null;
  high_risk_skus: number;
  medium_risk_skus: number;
  tracked_sku_plants: number;
  inventory_value: number;
  utilization_latest_month: number | null;
  utilization_month: string;
  dq_quarantine_rate: number;
};

export type ForecastPoint = { date: string; actual: number | null; forecast: number | null; is_future: number | null };
export type ForecastResponse = { series: ForecastPoint[]; models: string[]; wape_holdout: number | null };

export type RiskRow = {
  plant_id: string;
  sku_id: string;
  sku_name: string;
  category: string;
  volume_class: string;
  on_hand: number;
  avg_daily_demand: number;
  lead_time_days: number;
  days_of_cover: number | null;
  safety_stock: number;
  reorder_point: number;
  stockout_risk: "HIGH" | "MEDIUM" | "LOW";
};

export type CapacityResponse = {
  monthly: { month: string; plant_id: string; line_id: string; utilization: number | null; run_hours: number; available_hours: number }[];
  latest_by_line: { line_id: string; plant_id: string; utilization: number | null }[];
};

export type DataQuality = {
  row_counts: { table: string; bronze_rows: number; silver_rows: number; quarantined_rows: number }[];
  quarantine: { source_table: string; reason: string; rows: number }[];
  reconciliation: { check: string; source: number; pipeline: number; quarantined: number; unexplained_variance: number; ok: boolean }[];
  reconciled: boolean | null;
};

export async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal });
  if (!res.ok) {
    let detail = "";
    try {
      detail = (await res.json()).detail ?? "";
    } catch {
      /* body was not JSON */
    }
    throw new Error(`${res.status} ${res.statusText}${detail ? `: ${detail}` : ""}`);
  }
  return (await res.json()) as T;
}
