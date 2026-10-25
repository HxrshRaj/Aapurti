import "@testing-library/jest-dom/vitest";

// Recharts measures its container; jsdom has no layout engine.
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;
