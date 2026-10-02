import type { ConnectionState } from "../dashboard/useDashboardSocket";

const LABELS: Record<ConnectionState, string> = {
  connecting: "Connecting…",
  live: "Live",
  reconnecting: "Reconnecting…",
  forbidden: "Access denied",
};

export function ConnectionPill({ state }: { state: ConnectionState }) {
  return (
    <span className={`pill pill--${state}`} role="status" aria-live="polite">
      <span className="pill__dot" aria-hidden="true" />
      {LABELS[state]}
    </span>
  );
}
