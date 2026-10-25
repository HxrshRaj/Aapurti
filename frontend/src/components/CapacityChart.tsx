import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CapacityResponse } from "../api";
import { useFetch } from "../useFetch";
import Panel from "./Panel";

export default function CapacityChart({ plantId }: { plantId: string }) {
  const { state, retry } = useFetch<CapacityResponse>(`/api/capacity${plantId ? `?plant_id=${encodeURIComponent(plantId)}` : ""}`);
  return (
    <Panel
      title="Capacity utilization"
      subtitle="Latest month, run hours ÷ available hours, by line. Lines above 90% are flagged."
      state={state}
      retry={retry}
      isEmpty={(d) => d.latest_by_line.length === 0}
      emptyText="No capacity records for this plant."
    >
      {(d) => {
        const rows = d.latest_by_line.map((r) => ({ line: r.line_id, pct: r.utilization == null ? 0 : Math.round(r.utilization * 1000) / 10 }));
        return (
          <div className="chart" role="img" aria-label="Bar chart of latest-month utilization by production line">
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={rows} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" vertical={false} />
                <XAxis dataKey="line" tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 11 }} width={44} />
                <Tooltip formatter={(v: number) => `${v}%`} />
                <ReferenceLine y={90} stroke="var(--bad)" strokeDasharray="4 4" />
                <Bar dataKey="pct" name="Utilization" radius={[3, 3, 0, 0]}>
                  {rows.map((r) => (
                    <Cell key={r.line} fill={r.pct > 90 ? "var(--bad)" : "var(--c1)"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        );
      }}
    </Panel>
  );
}
