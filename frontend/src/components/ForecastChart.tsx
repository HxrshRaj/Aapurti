import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ForecastResponse } from "../api";
import { useFetch } from "../useFetch";
import Panel from "./Panel";

type Props = { skuId: string; plantId: string };

export default function ForecastChart({ skuId, plantId }: Props) {
  const qs = new URLSearchParams();
  if (skuId) qs.set("sku_id", skuId);
  if (plantId) qs.set("plant_id", plantId);
  const { state, retry } = useFetch<ForecastResponse>(`/api/forecast?${qs.toString()}`);

  return (
    <Panel
      title="Forecast vs actual"
      subtitle="Daily units. Forecast covers the last 28 days (held out) and the next 28 days."
      state={state}
      retry={retry}
      isEmpty={(d) => d.series.length === 0}
      emptyText="No demand history for this SKU / plant combination. Try clearing a filter."
    >
      {(d) => {
        const firstForecast = d.series.find((p) => p.forecast != null)?.date;
        return (
          <>
            <div className="chart" role="img" aria-label="Line chart of actual versus forecast daily demand">
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={d.series} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={32} />
                  <YAxis tick={{ fontSize: 11 }} width={48} />
                  <Tooltip />
                  <Legend />
                  {firstForecast && <ReferenceLine x={firstForecast} stroke="var(--muted)" strokeDasharray="4 4" label={{ value: "forecast starts", fontSize: 11, fill: "var(--muted)" }} />}
                  <Line type="monotone" dataKey="actual" name="Actual" stroke="var(--c1)" dot={false} strokeWidth={2} connectNulls />
                  <Line type="monotone" dataKey="forecast" name="Forecast" stroke="var(--c2)" dot={false} strokeWidth={2} strokeDasharray="6 3" connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="muted small">
              Held-out WAPE for this selection: <strong>{d.wape_holdout == null ? "n/a" : `${(d.wape_holdout * 100).toFixed(1)}%`}</strong>
              {" · "}model(s): {d.models.join(", ") || "n/a"}
            </p>
          </>
        );
      }}
    </Panel>
  );
}
