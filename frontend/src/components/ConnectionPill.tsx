import type { ConnectionState } from "../dashboard/useDashboardSocket";

const LABELS: Record<ConnectionState, string> = {
  connecting: "Connecting",
  live: "Live",
  reconnecting: "Reconnecting",
  offline: "Offline",
  forbidden: "Access denied",
};

const DESCRIPTIONS: Record<ConnectionState, string> = {
  connecting: "Opening the live event stream",
  live: "Receiving events as they happen",
  reconnecting: "Stream interrupted; retrying",
  offline: "Can't reach the gateway; still retrying with backoff",
  forbidden: "The gateway refused the live stream for this account",
};

export function ConnectionPill({ state, compact = false }: { state: ConnectionState; compact?: boolean }) {
  return (
    <span
      className={`pill pill--${state}`}
      role="status"
      aria-live="polite"
      title={DESCRIPTIONS[state]}
    >
      <span className="pill__dot" aria-hidden="true" />
      <span className={compact ? "visually-hidden" : undefined}>{LABELS[state]}</span>
    </span>
  );
}
