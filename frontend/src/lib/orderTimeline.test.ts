import { describe, expect, it } from "vitest";

import type { DashboardEvent, OrderEvent, OrderRecord, Payment, Reservation } from "../types";
import { buildTimeline, traceIds } from "./orderTimeline";

const ORDER_ID = "11111111-1111-4111-8111-111111111111";
const START = Date.parse("2026-10-04T10:00:00.000Z");
const at = (seconds: number) => new Date(START + seconds * 1000).toISOString();

const order: OrderRecord = {
  id: ORDER_ID,
  userId: "u",
  status: "paid",
  totalAmount: 40,
  createdAt: at(0),
  updatedAt: at(3),
  items: [],
};

function outbox(id: string, eventType: string, seconds: number, extra: Partial<OrderEvent> = {}): OrderEvent {
  return {
    id,
    eventType,
    payload: {},
    createdAt: at(seconds),
    publishedAt: at(seconds),
    traceId: null,
    ...extra,
  };
}

const reservation: Reservation = {
  id: "r1",
  orderId: ORDER_ID,
  productId: "p1",
  productName: "Widget",
  qty: 2,
  status: "committed",
  expiresAt: at(900),
  createdAt: at(1),
};

const payment: Payment = {
  paymentId: "pay-1",
  orderId: ORDER_ID,
  status: "succeeded",
  amount: 40,
  idempotencyKey: "charge-1",
  gatewayReference: "mock-charge-1",
  lastError: null,
  createdAt: at(2),
  updatedAt: at(2),
  ledger: [{ id: "l1", direction: "debit", amount: 40, createdAt: at(2.5) }],
};

describe("buildTimeline", () => {
  it("merges every service's records oldest first", () => {
    const entries = buildTimeline({
      order,
      events: [
        outbox("e1", "order.created", 0, { traceId: "t1" }),
        outbox("e2", "charge.requested", 1.5, { payload: { amount: "40.00", idempotency_key: "charge-1" } }),
        outbox("e3", "order.paid", 3),
      ],
      payment,
      reservations: [reservation],
      liveEvents: [],
    });
    expect(entries.map((entry) => [entry.source, entry.title])).toEqual([
      ["order-service", "Saga started: stock requested"],
      ["inventory-service", "Reserved 2 × Widget"],
      ["order-service", "Charge requested $40.00"],
      ["payment-service", "Charge succeeded $40.00"],
      ["payment-service", "Ledger debit $40.00"],
      ["order-service", "Stock commit requested"],
    ]);
    expect(entries[0]?.traceId).toBe("t1");
    expect(entries[2]?.detail).toBe("Idempotency key charge-1");
  });

  it("marks a repeated order.paid as a reconciler retry", () => {
    const entries = buildTimeline({
      order,
      events: [outbox("e1", "order.paid", 3), outbox("e2", "order.paid", 700)],
      payment: null,
      reservations: [],
      liveEvents: [],
    });
    expect(entries.map((entry) => entry.tone)).toEqual(["info", "warning"]);
    expect(entries[1]?.title).toBe("Stock commit re-sent by the reconciler");
  });

  it("flags rows the outbox relay hasn't published", () => {
    const [entry] = buildTimeline({
      order,
      events: [outbox("e1", "order.created", 0, { publishedAt: null })],
      payment: null,
      reservations: [],
      liveEvents: [],
    });
    expect(entry?.unpublished).toBe(true);
  });

  it("adds only the live events no service stores", () => {
    const live: DashboardEvent[] = [
      { type: "inventory.failed", data: { order_id: ORDER_ID, reason: "insufficient stock" }, receivedAt: at(1) },
      { type: "inventory.reserved", data: { order_id: ORDER_ID }, receivedAt: at(1) },
    ];
    const entries = buildTimeline({ order, events: [], payment: null, reservations: [], liveEvents: live });
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      title: "Reservation rejected",
      tone: "danger",
      detail: "insufficient stock",
      source: "inventory-service",
      live: true,
    });
  });
});

describe("traceIds", () => {
  it("lists distinct traces in first-seen order", () => {
    const ids = traceIds(
      [outbox("e1", "order.created", 0, { traceId: "t1" }), outbox("e2", "order.paid", 1, { traceId: "t2" }), outbox("e3", "x", 2)],
      [{ type: "payment.succeeded", data: {}, receivedAt: at(2), traceId: "t1" }],
    );
    expect(ids).toEqual(["t1", "t2"]);
  });
});
