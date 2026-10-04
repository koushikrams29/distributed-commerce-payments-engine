import { isOrderStatus, type DashboardEvent, type Order, type OrderStatus } from "../types";

// Enough history for the event console to filter and correlate a burst of
// orders; each entry is a few hundred bytes.
export const FEED_LIMIT = 500;
export const ORDER_LIMIT = 200;

export interface FeedEntry {
  seq: number;
  event: DashboardEvent;
}

export interface DashboardState {
  orders: Record<string, Order>;
  feed: FeedEntry[];
  eventsReceived: number;
  snapshotLoaded: boolean;
}

export type DashboardAction =
  | { type: "snapshot"; orders: Order[] }
  | { type: "event"; event: DashboardEvent };

export const initialDashboardState: DashboardState = {
  orders: {},
  feed: [],
  eventsReceived: 0,
  snapshotLoaded: false,
};

/**
 * Position in the order lifecycle. Transitions only move forward, and the two
 * terminal states can never follow each other, so "further along wins" merges
 * a snapshot with live events correctly no matter which arrived first — no
 * timestamps (and no clock skew between services) involved.
 */
const LIFECYCLE_RANK: Record<OrderStatus, number> = {
  pending: 0,
  reserved: 1,
  paid: 2,
  fulfilled: 3,
  cancelled: 3,
};

function furthest(a: OrderStatus, b: OrderStatus): OrderStatus {
  return LIFECYCLE_RANK[b] > LIFECYCLE_RANK[a] ? b : a;
}

export function dashboardReducer(
  state: DashboardState,
  action: DashboardAction,
): DashboardState {
  switch (action.type) {
    case "snapshot":
      return { ...state, orders: mergeSnapshot(state.orders, action.orders), snapshotLoaded: true };
    case "event":
      return applyEvent(state, action.event);
  }
}

function mergeSnapshot(current: Record<string, Order>, snapshot: Order[]): Record<string, Order> {
  const orders = { ...current };
  for (const incoming of snapshot) {
    const existing = orders[incoming.id];
    orders[incoming.id] = existing
      ? {
          ...incoming,
          status: furthest(existing.status, incoming.status),
          updatedAt: later(existing.updatedAt, incoming.updatedAt),
        }
      : incoming;
  }
  return prune(orders);
}

function applyEvent(state: DashboardState, event: DashboardEvent): DashboardState {
  const feed = [{ seq: state.eventsReceived + 1, event }, ...state.feed].slice(0, FEED_LIMIT);
  const next = { ...state, feed, eventsReceived: state.eventsReceived + 1 };
  if (event.type !== "order.status_changed") return next;

  const change = parseStatusChange(event);
  if (!change) return next;

  const existing = state.orders[change.orderId];
  const order: Order = existing
    ? {
        ...existing,
        status: furthest(existing.status, change.status),
        updatedAt: later(existing.updatedAt, change.occurredAt),
      }
    : {
        id: change.orderId,
        userId: change.userId,
        status: change.status,
        totalAmount: change.totalAmount,
        createdAt: change.previousStatus === null ? change.occurredAt : null,
        updatedAt: change.occurredAt,
        itemCount: null,
      };
  return { ...next, orders: prune({ ...state.orders, [order.id]: order }) };
}

interface StatusChange {
  orderId: string;
  userId: string;
  status: OrderStatus;
  previousStatus: OrderStatus | null;
  totalAmount: number;
  occurredAt: string;
}

function parseStatusChange(event: DashboardEvent): StatusChange | null {
  const { order_id, user_id, status, previous_status, total_amount, occurred_at } = event.data;
  if (typeof order_id !== "string" || typeof user_id !== "string" || !isOrderStatus(status)) {
    return null;
  }
  return {
    orderId: order_id,
    userId: user_id,
    status,
    previousStatus: isOrderStatus(previous_status) ? previous_status : null,
    totalAmount: Number(total_amount ?? 0),
    occurredAt: typeof occurred_at === "string" ? occurred_at : event.receivedAt,
  };
}

function later(a: string, b: string): string {
  return Date.parse(b) > Date.parse(a) ? b : a;
}

/** Keeps memory bounded on a dashboard left open for days. */
function prune(orders: Record<string, Order>): Record<string, Order> {
  const all = Object.values(orders);
  if (all.length <= ORDER_LIMIT) return orders;
  return Object.fromEntries(
    sortByActivity(all)
      .slice(0, ORDER_LIMIT)
      .map((order) => [order.id, order]),
  );
}

export function sortByActivity(orders: Order[]): Order[] {
  return [...orders].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
}

export interface DashboardMetrics {
  byStatus: Record<OrderStatus, number>;
  inFlight: number;
  revenue: number;
  /** Fulfilled share of finished orders; null until any order has finished. */
  successRate: number | null;
}

export function selectMetrics(state: DashboardState): DashboardMetrics {
  const byStatus: Record<OrderStatus, number> = {
    pending: 0,
    reserved: 0,
    paid: 0,
    fulfilled: 0,
    cancelled: 0,
  };
  let revenue = 0;
  for (const order of Object.values(state.orders)) {
    byStatus[order.status] += 1;
    if (order.status === "paid" || order.status === "fulfilled") {
      revenue += order.totalAmount;
    }
  }
  const finished = byStatus.fulfilled + byStatus.cancelled;
  return {
    byStatus,
    inFlight: byStatus.pending + byStatus.reserved + byStatus.paid,
    revenue,
    successRate: finished === 0 ? null : byStatus.fulfilled / finished,
  };
}
