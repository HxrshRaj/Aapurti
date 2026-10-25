import type { DataQuality } from "../api";
import { useFetch } from "../useFetch";
import Panel from "./Panel";

export default function DataQualityPanel() {
  const { state, retry } = useFetch<DataQuality>("/api/data-quality");
  return (
    <Panel
      title="Data quality"
      subtitle="Rows quarantined by the silver layer, and source-to-gold reconciliation."
      state={state}
      retry={retry}
      isEmpty={(d) => d.row_counts.length === 0}
      emptyText="No data-quality metrics have been produced yet."
    >
      {(d) => (
        <>
          <p className={`pill ${d.reconciled ? "ok" : "bad"}`}>
            {d.reconciled ? "Reconciled: no unexplained variance" : "Reconciliation has unexplained variance"}
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Table</th>
                  <th className="r">Bronze</th>
                  <th className="r">Silver</th>
                  <th className="r">Quarantined</th>
                </tr>
              </thead>
              <tbody>
                {d.row_counts.map((r) => (
                  <tr key={r.table}>
                    <td>{r.table}</td>
                    <td className="r">{r.bronze_rows.toLocaleString("en-IN")}</td>
                    <td className="r">{r.silver_rows.toLocaleString("en-IN")}</td>
                    <td className="r">{r.quarantined_rows.toLocaleString("en-IN")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>Quarantine reasons</h3>
          <ul className="reasons">
            {d.quarantine.map((q) => (
              <li key={`${q.source_table}-${q.reason}`}>
                <span>
                  {q.source_table} · {q.reason.replace(/_/g, " ")}
                </span>
                <strong>{q.rows.toLocaleString("en-IN")}</strong>
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}
