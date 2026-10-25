import { useCallback, useEffect, useState } from "react";
import { getJson } from "./api";

export type Remote<T> =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "success"; data: T };

/** Fetches `url` (re-fetches when it changes); `retry` re-runs the request after a failure. */
export function useFetch<T>(url: string): { state: Remote<T>; retry: () => void } {
  const [state, setState] = useState<Remote<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setState({ status: "loading" });
    getJson<T>(url, ctrl.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((e: unknown) => {
        if ((e as { name?: string }).name === "AbortError") return;
        setState({ status: "error", error: e instanceof Error ? e.message : String(e) });
      });
    return () => ctrl.abort();
  }, [url, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, retry };
}
