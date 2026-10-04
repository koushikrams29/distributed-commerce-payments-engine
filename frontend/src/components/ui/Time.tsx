import { useSyncExternalStore } from "react";

import { formatDateTime, formatRelative } from "../../lib/format";

const TICK_MS = 10_000;
let now = Date.now();
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | undefined;

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  // One shared clock for every relative time on screen, not one timer each.
  timer ??= setInterval(() => {
    now = Date.now();
    for (const notify of listeners) notify();
  }, TICK_MS);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      clearInterval(timer);
      timer = undefined;
    }
  };
}

/** The current time, updated every 10 seconds. */
export function useNow(): number {
  return useSyncExternalStore(subscribe, () => now);
}

export function TimeAgo({ iso }: { iso: string | null }) {
  const current = useNow();
  if (!iso) return <span className="muted">—</span>;
  return (
    <time dateTime={iso} title={formatDateTime(iso)}>
      {formatRelative(iso, Math.max(current, Date.now()))}
    </time>
  );
}
