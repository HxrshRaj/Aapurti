import type { ReactNode } from "react";
import type { Remote } from "../useFetch";

type Props<T> = {
  title: string;
  subtitle?: string;
  state: Remote<T>;
  retry: () => void;
  isEmpty?: (data: T) => boolean;
  emptyText?: string;
  children: (data: T) => ReactNode;
  actions?: ReactNode;
};

/** Card with consistent loading / error (with retry) / empty / success states. */
export default function Panel<T>({ title, subtitle, state, retry, isEmpty, emptyText, children, actions }: Props<T>) {
  return (
    <section className="card" aria-label={title}>
      <header className="card-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p className="muted">{subtitle}</p>}
        </div>
        {actions}
      </header>
      {state.status === "loading" && (
        <div className="state" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" /> Loading {title.toLowerCase()}…
        </div>
      )}
      {state.status === "error" && (
        <div className="state error" role="alert">
          <p>Could not load {title.toLowerCase()}.</p>
          <p className="muted small">{state.error}</p>
          <button type="button" onClick={retry}>
            Retry
          </button>
        </div>
      )}
      {state.status === "success" &&
        (isEmpty?.(state.data) ? (
          <div className="state empty">{emptyText ?? "No data for this selection."}</div>
        ) : (
          children(state.data)
        ))}
    </section>
  );
}
