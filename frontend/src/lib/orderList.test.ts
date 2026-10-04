import { describe, expect, it } from "vitest";

import type { Order, OrderRecord, OrderStatus } from "../types";
import {
  createdWindow,
  isRangeKey,
  isSortKey,
  matchesQuery,
  newSince,
  orderAge,
  sortOrders,
  withLiveStatus,
} from "./orderList";

const NOW = Date.parse("2026-10-04T12:00:00.000Z");
const minutesAgo = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();

function record(id: string, overrides: Partial<OrderRecord> = {}): OrderRecord {
  return {
    id,
    userId: "aaaaaaaa-0000-4000-8000-000000000000",
    status: "pending",
    totalAmount: 10,
    createdAt: minutesAgo(10),
    updatedAt: minutesAgo(9),
    items: [],
    ...overrides,
  };
}

function live(id: string, status: OrderStatus, createdAt: string | null, updatedAt = minutesAgo(0)): Order {
  return { id, userId: "u", status, totalAmount: 10, createdAt, updatedAt, itemCount: null };
}

describe("createdWindow", () => {
  it("turns a preset range into an ISO lower bound", () => {
    expect(createdWindow("1h", { from: null, to: null }, NOW)).toEqual({
      createdFrom: "2026-10-04T11:00:00.000Z",
      createdTo: null,
    });
  });

  it("has no bounds for all time and passes custom bounds through", () => {
    expect(createdWindow("all", { from: "x", to: "y" }, NOW)).toEqual({ createdFrom: null, createdTo: null });
    expect(createdWindow("custom", { from: "a", to: null }, NOW)).toEqual({ createdFrom: "a", createdTo: null });
  });
});

describe("guards", () => {
  it("accepts only known range and sort keys", () => {
    expect(isRangeKey("24h")).toBe(true);
    expect(isRangeKey("toString")).toBe(false);
    expect(isRangeKey(null)).toBe(false);
    expect(isSortKey("age")).toBe(true);
    expect(isSortKey("status")).toBe(false);
  });
});

describe("orderAge", () => {
  it("runs to now while in flight and stops at the last update once finished", () => {
    expect(orderAge(record("a"), NOW)).toBe(10 * 60_000);
    expect(orderAge(record("a", { status: "fulfilled" }), NOW)).toBe(60_000);
  });
});

describe("sortOrders", () => {
  const rows = [
    record("b", { totalAmount: 30, createdAt: minutesAgo(5) }),
    record("a", { totalAmount: 10, createdAt: minutesAgo(1) }),
    record("c", { totalAmount: 30, createdAt: minutesAgo(9) }),
  ];

  it("sorts by the chosen key in either direction", () => {
    expect(sortOrders(rows, "created", "desc", NOW).map((row) => row.id)).toEqual(["a", "b", "c"]);
    expect(sortOrders(rows, "created", "asc", NOW).map((row) => row.id)).toEqual(["c", "b", "a"]);
  });

  it("breaks ties by ID so the order is stable", () => {
    expect(sortOrders(rows, "total", "desc", NOW).map((row) => row.id)).toEqual(["b", "c", "a"]);
  });

  it("does not mutate its input", () => {
    sortOrders(rows, "total", "asc", NOW);
    expect(rows.map((row) => row.id)).toEqual(["b", "a", "c"]);
  });
});

describe("matchesQuery", () => {
  const order = record("3f2b9c1e-8d4a-4e2b-9a7c-1b2c3d4e5f60");

  it("matches order or customer ID prefixes, with or without dashes", () => {
    expect(matchesQuery(order, "3F2B")).toBe(true);
    expect(matchesQuery(order, "3f2b9c1e8d4a")).toBe(true);
    expect(matchesQuery(order, "3f2b9c1e-8d")).toBe(true);
    expect(matchesQuery(order, "aaaaaaaa")).toBe(true);
    expect(matchesQuery(order, "")).toBe(true);
  });

  it("does not match in the middle of an ID", () => {
    expect(matchesQuery(order, "9c1e")).toBe(false);
  });
});

describe("withLiveStatus", () => {
  it("applies newer statuses but never moves an order backwards", () => {
    const rows = [record("a", { status: "reserved" }), record("b", { status: "paid" })];
    const result = withLiveStatus(rows, {
      a: live("a", "paid", null, minutesAgo(0)),
      b: live("b", "reserved", null),
    });
    expect(result[0]).toMatchObject({ status: "paid", updatedAt: minutesAgo(0) });
    expect(result[1]).toBe(rows[1]);
  });
});

describe("newSince", () => {
  it("counts orders placed after loading that the list doesn't show", () => {
    const loadedAt = NOW - 60_000;
    const orders = {
      shown: live("shown", "pending", minutesAgo(0)),
      fresh: live("fresh", "pending", minutesAgo(0)),
      freshPaid: live("freshPaid", "paid", minutesAgo(0)),
      old: live("old", "pending", minutesAgo(5)),
      unknown: live("unknown", "pending", null),
    };
    expect(newSince(orders, new Set(["shown"]), loadedAt, null)).toBe(2);
    expect(newSince(orders, new Set(["shown"]), loadedAt, "pending")).toBe(1);
  });
});
