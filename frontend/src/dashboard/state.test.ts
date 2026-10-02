import { describe, expect, it } from "vitest";

import type { DashboardEvent, Order, OrderStatus } from "../types";
import {
  FEED_LIMIT,
  ORDER_LIMIT,
  dashboardReducer,
  initialDashboardState,
  selectMetrics,
  sortByActivity,
  type DashboardState,
} from "./state";

const ORDER_ID = "11111111-1111-1111-1111-111111111111";
const USER_ID = "22222222-2222-2222-2222-222222222222";

function statusChanged(
  status: OrderStatus,
  previous: OrderStatus | null,
  occurredAt: string,
  orderId = ORDER_ID,
): DashboardEvent {
  return {
    type: "order.status_changed",
    data: {
      order_id: orderId,
      user_id: USER_ID,
      status,
      previous_status: previous,
      total_amount: "40.00",
      occurred_at: occurredAt,
    },
    receivedAt: occurredAt,
  };
}

function snapshotOrder(overrides: Partial<Order> = {}): Order {
  return {
    id: ORDER_ID,
    userId: USER_ID,
    status: "pending",
    totalAmount: 40,
    createdAt: "2026-10-02T10:00:00Z",
    updatedAt: "2026-10-02T10:00:00Z",
    itemCount: 2,
    ...overrides,
  };
}

function reduce(...actions: Parameters<typeof dashboardReducer>[1][]): DashboardState {
  return actions.reduce(dashboardReducer, initialDashboardState);
}

describe("live status changes", () => {
  it("adds a newly placed order with its creation time", () => {
    const state = reduce({
      type: "event",
      event: statusChanged("pending", null, "2026-10-02T10:00:00Z"),
    });

    expect(state.orders[ORDER_ID]).toMatchObject({
      status: "pending",
      totalAmount: 40,
      createdAt: "2026-10-02T10:00:00Z",
      itemCount: null,
    });
  });

  it("leaves the creation time unknown when the first event seen is a later transition", () => {
    const state = reduce({
      type: "event",
      event: statusChanged("paid", "reserved", "2026-10-02T10:05:00Z"),
    });

    expect(state.orders[ORDER_ID]?.createdAt).toBeNull();
  });

  it("moves an order forward through the lifecycle", () => {
    const state = reduce(
      { type: "event", event: statusChanged("pending", null, "2026-10-02T10:00:00Z") },
      { type: "event", event: statusChanged("reserved", "pending", "2026-10-02T10:00:01Z") },
      { type: "event", event: statusChanged("paid", "reserved", "2026-10-02T10:00:02Z") },
    );

    expect(state.orders[ORDER_ID]?.status).toBe("paid");
    expect(state.orders[ORDER_ID]?.updatedAt).toBe("2026-10-02T10:00:02Z");
  });

  it("ignores a delayed event that would move an order backwards", () => {
    const state = reduce(
      { type: "event", event: statusChanged("paid", "reserved", "2026-10-02T10:00:02Z") },
      { type: "event", event: statusChanged("reserved", "pending", "2026-10-02T10:00:01Z") },
    );

    expect(state.orders[ORDER_ID]?.status).toBe("paid");
    expect(state.orders[ORDER_ID]?.updatedAt).toBe("2026-10-02T10:00:02Z");
  });

  it("ignores malformed status changes but still shows them in the feed", () => {
    const state = reduce({
      type: "event",
      event: { type: "order.status_changed", data: { status: "teleported" }, receivedAt: "x" },
    });

    expect(state.orders).toEqual({});
    expect(state.feed).toHaveLength(1);
  });
});

describe("snapshot merge", () => {
  it("keeps a live update that is newer than the snapshot", () => {
    // The socket is opened before the snapshot request, so a transition can
    // arrive live while the (now stale) snapshot is still in flight.
    const state = reduce(
      { type: "event", event: statusChanged("reserved", "pending", "2026-10-02T10:00:01Z") },
      { type: "snapshot", orders: [snapshotOrder({ status: "pending" })] },
    );

    expect(state.orders[ORDER_ID]).toMatchObject({
      status: "reserved",
      itemCount: 2,
      createdAt: "2026-10-02T10:00:00Z",
    });
  });

  it("takes the snapshot status when it is further along", () => {
    const state = reduce(
      { type: "event", event: statusChanged("pending", null, "2026-10-02T10:00:00Z") },
      {
        type: "snapshot",
        orders: [snapshotOrder({ status: "fulfilled", updatedAt: "2026-10-02T10:01:00Z" })],
      },
    );

    expect(state.orders[ORDER_ID]?.status).toBe("fulfilled");
    expect(state.snapshotLoaded).toBe(true);
  });

  it("never lets a terminal status be replaced by the other terminal status", () => {
    const state = reduce(
      { type: "event", event: statusChanged("cancelled", "pending", "2026-10-02T10:00:01Z") },
      { type: "snapshot", orders: [snapshotOrder({ status: "fulfilled" })] },
    );

    expect(state.orders[ORDER_ID]?.status).toBe("cancelled");
  });

  it("caps the number of tracked orders, keeping the most recently active", () => {
    const orders = Array.from({ length: ORDER_LIMIT + 5 }, (_, index) =>
      snapshotOrder({
        id: `order-${index}`,
        updatedAt: new Date(Date.UTC(2026, 9, 2, 10, 0, index)).toISOString(),
      }),
    );

    const state = reduce({ type: "snapshot", orders });

    expect(Object.keys(state.orders)).toHaveLength(ORDER_LIMIT);
    expect(state.orders["order-0"]).toBeUndefined();
    expect(state.orders[`order-${ORDER_LIMIT + 4}`]).toBeDefined();
  });
});

describe("feed", () => {
  it("lists events newest first and keeps only the most recent ones", () => {
    const events = Array.from({ length: FEED_LIMIT + 10 }, (_, index) => ({
      type: "event" as const,
      event: { type: "payment.succeeded", data: { n: index }, receivedAt: "t" },
    }));

    const state = reduce(...events);

    expect(state.feed).toHaveLength(FEED_LIMIT);
    expect(state.feed[0]?.event.data.n).toBe(FEED_LIMIT + 9);
    expect(state.eventsReceived).toBe(FEED_LIMIT + 10);
  });
});

describe("metrics", () => {
  it("counts statuses, captured revenue and the success rate", () => {
    const state = reduce({
      type: "snapshot",
      orders: [
        snapshotOrder({ id: "a", status: "fulfilled", totalAmount: 100 }),
        snapshotOrder({ id: "b", status: "paid", totalAmount: 50 }),
        snapshotOrder({ id: "c", status: "cancelled", totalAmount: 999 }),
        snapshotOrder({ id: "d", status: "pending", totalAmount: 10 }),
        snapshotOrder({ id: "e", status: "fulfilled", totalAmount: 25 }),
      ],
    });

    const metrics = selectMetrics(state);

    expect(metrics.byStatus).toEqual({
      pending: 1,
      reserved: 0,
      paid: 1,
      fulfilled: 2,
      cancelled: 1,
    });
    expect(metrics.inFlight).toBe(2);
    expect(metrics.revenue).toBe(175);
    expect(metrics.successRate).toBeCloseTo(2 / 3);
  });

  it("has no success rate before any order finishes", () => {
    expect(selectMetrics(initialDashboardState).successRate).toBeNull();
  });
});

describe("sortByActivity", () => {
  it("puts the most recently updated order first", () => {
    const sorted = sortByActivity([
      snapshotOrder({ id: "old", updatedAt: "2026-10-02T09:00:00Z" }),
      snapshotOrder({ id: "new", updatedAt: "2026-10-02T11:00:00Z" }),
    ]);

    expect(sorted.map((order) => order.id)).toEqual(["new", "old"]);
  });
});
