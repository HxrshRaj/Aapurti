import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const filters = {
  plants: [{ plant_id: "P01", plant_name: "Pune" }, { plant_id: "P02", plant_name: "Chennai" }],
  skus: [
    { sku_id: "S001", sku_name: "Valve S001", volume_class: "A", plant_id: "P01" },
    { sku_id: "S002", sku_name: "Pump S002", volume_class: "B", plant_id: "P02" },
  ],
  as_of: "2025-12-31",
  notice: "SYNTHETIC",
};
const kpis = {
  as_of: "2025-12-31", forecast_wape: 0.136, forecast_accuracy: 0.864, units_last_30d: 250000, avg_days_of_cover: 21.4,
  high_risk_skus: 7, medium_risk_skus: 5, tracked_sku_plants: 75, inventory_value: 1, utilization_latest_month: 0.74,
  utilization_month: "2025-12", dq_quarantine_rate: 0.02,
};
const forecast = {
  series: [
    { date: "2025-12-01", actual: 100, forecast: null, is_future: null },
    { date: "2025-12-04", actual: 110, forecast: 105, is_future: 0 },
  ],
  models: ["gradient_boosting"], wape_holdout: 0.12,
};
const risk = {
  rows: [{ plant_id: "P01", sku_id: "S001", sku_name: "Valve S001", category: "Valves", volume_class: "A", on_hand: 120,
    avg_daily_demand: 30, lead_time_days: 10, days_of_cover: 4, safety_stock: 5, reorder_point: 305, stockout_risk: "HIGH" }],
};
const capacity = { monthly: [], latest_by_line: [{ line_id: "P01-L1", plant_id: "P01", utilization: 0.93 }] };
const dq = {
  row_counts: [{ table: "demand_daily", bronze_rows: 100, silver_rows: 98, quarantined_rows: 2 }],
  quarantine: [{ source_table: "demand_daily", reason: "unknown_sku", rows: 2 }],
  reconciliation: [], reconciled: true,
};

type Handler = (url: string) => { status?: number; body: unknown };
function mockFetch(overrides: Record<string, Handler> = {}) {
  const calls: string[] = [];
  const base: Record<string, Handler> = {
    "/api/filters": () => ({ body: filters }),
    "/api/kpis": () => ({ body: kpis }),
    "/api/forecast": () => ({ body: forecast }),
    "/api/inventory/risk": () => ({ body: risk }),
    "/api/capacity": () => ({ body: capacity }),
    "/api/data-quality": () => ({ body: dq }),
  };
  const handlers = { ...base, ...overrides };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const key = Object.keys(handlers).find((k) => url.startsWith(k))!;
    const { status = 200, body } = handlers[key](url);
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }));
  return calls;
}

beforeEach(() => mockFetch());
afterEach(() => vi.unstubAllGlobals());

describe("Dashboard", () => {
  it("shows loading states first, then data", async () => {
    render(<App />);
    expect(screen.getByLabelText("Loading KPIs")).toBeInTheDocument();
    expect(await screen.findByText("86.4%")).toBeInTheDocument();
    expect(screen.getByText("7 high")).toBeInTheDocument();
    expect(await screen.findByText("HIGH")).toBeInTheDocument();
    expect(await screen.findByText(/Reconciled: no unexplained variance/)).toBeInTheDocument();
    expect(screen.getByText(/unknown sku/)).toBeInTheDocument();
  });

  it("labels the data as synthetic and links the Excel export", async () => {
    render(<App />);
    expect(screen.getByRole("note")).toHaveTextContent(/synthetic/i);
    expect(screen.getByRole("link", { name: /download excel/i })).toHaveAttribute("href", "/export.xlsx");
    await screen.findByText("86.4%");
  });

  it("shows an empty state when a selection has no forecast data", async () => {
    mockFetch({ "/api/forecast": () => ({ body: { series: [], models: [], wape_holdout: null } }) });
    render(<App />);
    expect(await screen.findByText(/No demand history for this SKU/)).toBeInTheDocument();
  });

  it("shows an error with a working Retry button", async () => {
    let fail = true;
    mockFetch({ "/api/inventory/risk": () => (fail ? { status: 500, body: { detail: "db locked" } } : { body: risk }) });
    render(<App />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/Could not load inventory risk/);
    expect(alert).toHaveTextContent(/db locked/);
    fail = false;
    await userEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("HIGH")).toBeInTheDocument();
    expect(screen.queryByText(/Could not load inventory risk/)).not.toBeInTheDocument();
  });

  it("one failing panel does not blank the others", async () => {
    mockFetch({ "/api/capacity": () => ({ status: 503, body: { detail: "down" } }) });
    render(<App />);
    expect(await screen.findByText(/Could not load capacity utilization/)).toBeInTheDocument();
    expect(await screen.findByText("86.4%")).toBeInTheDocument();
  });

  it("re-queries with the selected plant and SKU", async () => {
    const calls = mockFetch();
    render(<App />);
    await screen.findByText("86.4%");
    await waitFor(() => expect(screen.getByLabelText("Plant")).not.toBeDisabled());
    await userEvent.selectOptions(screen.getByLabelText("Plant"), "P02");
    await waitFor(() => expect(calls.some((c) => c.startsWith("/api/forecast?") && c.includes("plant_id=P02"))).toBe(true));
    expect(screen.queryByRole("option", { name: /S001/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("SKU"), "S002");
    await waitFor(() => expect(calls.some((c) => c.includes("sku_id=S002") && c.includes("plant_id=P02"))).toBe(true));
  });

  it("reports a filter failure and recovers on retry", async () => {
    let fail = true;
    mockFetch({ "/api/filters": () => (fail ? { status: 500, body: {} } : { body: filters }) });
    render(<App />);
    const msg = await screen.findByText(/Could not load filters/);
    fail = false;
    await userEvent.click(within(msg.closest("div")!).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("option", { name: /P01 Pune/ })).toBeInTheDocument();
  });
});
