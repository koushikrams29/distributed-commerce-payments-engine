import type { Order, OrderRecord, OrderStatus } from "../types";

export const RANGES = {
  "1h": { label: "Last hour", ms: 3_600_000 },
  "24h": { label: "Last 24 hours", ms: 86_400_000 },
  "7d": { label: "Last 7 days", ms: 7 * 86_400_000 },
  all: { label: "All time", ms: null },
  custom: { label: "Custom", ms: null },
} as const;

export type RangeKey = keyof typeof RANGES;

export function isRangeKey(value: string | null): value is RangeKey {
  return value !== null && Object.prototype.hasOwnProperty.call(RANGES, value);
}

export interface CreatedWindow {
  createdFrom: string | null;
  createdTo: string | null;
}

/** The created_at window to request, as ISO instants with an offset (the API rejects naive times). */
export function createdWindow(
  range: RangeKey,
  custom: { from: string | null; to: string | null },
  now: number,
): CreatedWindow {
  if (range === "custom") return { createdFrom: custom.from, createdTo: custom.to };
  const span = RANGES[range].ms;
  return { createdFrom: span === null ? null : new Date(now - span).toISOString(), createdTo: null };
}

export type SortKey = "created" | "updated" | "total" | "age";
export type SortDirection = "asc" | "desc";

export function isSortKey(value: string | null): value is SortKey {
  return value === "created" || value === "updated" || value === "total" || value === "age";
}

/** Time an order has taken: to its last update once finished, to now while in flight. */
export function orderAge(order: OrderRecord, now: number): number {
  const finished = order.status === "fulfilled" || order.status === "cancelled";
  return (finished ? Date.parse(order.updatedAt) : now) - Date.parse(order.createdAt);
}

export function sortOrders(
  rows: OrderRecord[],
  key: SortKey,
  direction: SortDirection,
  now: number,
): OrderRecord[] {
  const value = (order: OrderRecord): number => {
    switch (key) {
      case "created":
        return Date.parse(order.createdAt);
      case "updated":
        return Date.parse(order.updatedAt);
      case "total":
        return order.totalAmount;
      case "age":
        return orderAge(order, now);
    }
  };
  const sign = direction === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => (value(a) - value(b)) * sign || a.id.localeCompare(b.id));
}

/** Matches an order or customer ID by prefix, ignoring case and dashes typed or not. */
export function matchesQuery(order: OrderRecord, query: string): boolean {
  const needle = query.trim().toLowerCase().replace(/-/g, "");
  if (!needle) return true;
  return [order.id, order.userId].some((id) => id.replace(/-/g, "").startsWith(needle));
}

const RANK: Record<OrderStatus, number> = { pending: 0, reserved: 1, paid: 2, fulfilled: 3, cancelled: 3 };

/** Applies newer live status changes to rows fetched earlier, without reordering them. */
export function withLiveStatus(rows: OrderRecord[], live: Record<string, Order>): OrderRecord[] {
  return rows.map((row) => {
    const update = live[row.id];
    if (!update || RANK[update.status] <= RANK[row.status]) return row;
    return { ...row, status: update.status, updatedAt: update.updatedAt };
  });
}

/** Orders placed (seen live) after the list was loaded that it doesn't show yet. */
export function newSince(
  live: Record<string, Order>,
  shown: Set<string>,
  loadedAt: number,
  status: OrderStatus | null,
): number {
  let count = 0;
  for (const order of Object.values(live)) {
    if (shown.has(order.id) || !order.createdAt) continue;
    if (Date.parse(order.createdAt) <= loadedAt) continue;
    if (status && order.status !== status) continue;
    count += 1;
  }
  return count;
}
