import { describe, expect, it } from "vitest";

import type { OrderEvent, OrderRecord, OrderStatus, Payment, Reservation } from "../types";
import { deriveSaga, explainOrder, statusBeforeCancel, transitions, type SagaInput } from "./saga";

const ORDER_ID = "11111111-1111-4111-8111-111111111111";
const PLACED = "2026-10-04T10:00:00.000Z";
const at = (seconds: number) => new Date(Date.parse(PLACED) + seconds * 1000).toISOString();

function order(status: OrderStatus, updatedAt = at(5)): OrderRecord {
  return {
    id: ORDER_ID,
    userId: "22222222-2222-4222-8222-222222222222",
    status,
    totalAmount: 40,
    createdAt: PLACED,
    updatedAt,
    items: [{ id: "i1", productId: "p1", qty: 2, unitPrice: 20 }],
  };
}

let nextId = 0;
function outbox(eventType: string, createdAt: string, payload: Record<string, unknown> = {}, published = true): OrderEvent {
  nextId += 1;
  return {
    id: `e${nextId}`,
    eventType,
    payload,
    createdAt,
    publishedAt: published ? createdAt : null,
    traceId: null,
  };
}

function changed(status: OrderStatus, previous: OrderStatus | null, seconds: number): OrderEvent {
  return outbox("order.status_changed", at(seconds), {
    status,
    previous_status: previous,
    occurred_at: at(seconds),
  });
}

function payment(status: Payment["status"]): Payment {
  return {
    paymentId: "pay-1",
    orderId: ORDER_ID,
    status,
    amount: 40,
    idempotencyKey: "charge-1",
    gatewayReference: null,
    lastError: status === "unknown" ? "provider timeout" : null,
    createdAt: at(2),
    updatedAt: at(2),
    ledger: [],
  };
}

function reservation(status: Reservation["status"]): Reservation {
  return {
    id: "r1",
    orderId: ORDER_ID,
    productId: "p1",
    productName: "Widget",
    qty: 2,
    status,
    expiresAt: at(900),
    createdAt: at(1),
  };
}

function input(overrides: Partial<SagaInput>): SagaInput {
  return {
    order: order("pending"),
    events: [changed("pending", null, 0)],
    payment: null,
    reservations: [],
    thresholds: { pending: 15, reserved: 15, paid: 10 },
    now: Date.parse(at(30)),
    ...overrides,
  };
}

const states = (view: ReturnType<typeof deriveSaga>) => view.steps.map((step) => step.state);

describe("transitions", () => {
  it("reads status changes and ignores other events and unknown statuses", () => {
    const list = transitions([
      changed("pending", null, 0),
      outbox("order.created", at(0)),
      outbox("order.status_changed", at(1), { status: "teleported" }),
      changed("reserved", "pending", 2),
    ]);
    expect(list).toEqual([
      { status: "pending", previous: null, at: at(0) },
      { status: "reserved", previous: "pending", at: at(2) },
    ]);
  });
});

describe("statusBeforeCancel", () => {
  it("prefers the recorded previous status", () => {
    expect(statusBeforeCancel([{ status: "cancelled", previous: "paid", at: at(9) }], null, [])).toBe("paid");
  });

  it("falls back to the evidence left behind", () => {
    expect(statusBeforeCancel([], payment("failed"), [])).toBe("reserved");
    expect(statusBeforeCancel([], null, [reservation("released")])).toBe("reserved");
    expect(statusBeforeCancel([], null, [])).toBe("pending");
  });
});

describe("deriveSaga", () => {
  it("marks the step after the current status active with how long it has waited", () => {
    const view = deriveSaga(input({}));
    expect(states(view)).toEqual(["complete", "active", "waiting", "waiting", "waiting"]);
    expect(view.steps[1]?.note).toBe("Waiting 30 s");
    expect(view.finishedAt).toBeNull();
    expect(view.overdue).toBe(false);
  });

  it("completes every step of a fulfilled order and stops the clock", () => {
    const view = deriveSaga(
      input({
        order: order("fulfilled", at(4)),
        events: [
          changed("pending", null, 0),
          changed("reserved", "pending", 1),
          changed("paid", "reserved", 2),
          outbox("order.paid", at(2)),
          changed("fulfilled", "paid", 4),
          outbox("order.fulfilled", at(4)),
        ],
        now: Date.parse(at(600)),
      }),
    );
    expect(states(view)).toEqual(["complete", "complete", "complete", "complete", "complete"]);
    expect(view.finishedAt).toBe(at(4));
    expect(view.durationMs).toBe(4000);
    expect(view.steps[2]?.at).toBe(at(2));
  });

  it("shows the commit step retrying when the reconciler re-sent order.paid", () => {
    const view = deriveSaga(
      input({
        order: order("paid", at(2)),
        events: [
          changed("pending", null, 0),
          changed("reserved", "pending", 1),
          changed("paid", "reserved", 2),
          outbox("order.paid", at(2)),
          outbox("order.paid", at(700)),
        ],
        now: Date.parse(at(720)),
      }),
    );
    expect(view.steps[3]?.state).toBe("retrying");
    expect(view.steps[3]?.note).toBe("order.paid re-sent 1× by the reconciler");
  });

  it("measures paid orders from their last update when deciding they are overdue", () => {
    const view = deriveSaga(
      input({
        order: order("paid", at(60)),
        events: [changed("pending", null, 0), changed("reserved", "pending", 1), changed("paid", "reserved", 60)],
        now: Date.parse(at(60 + 11 * 60)),
      }),
    );
    expect(view.overdue).toBe(true);
    expect(view.steps[3]?.note).toBe("Waiting 11 min — past the 10 min timeout");
  });

  it("fails the step after the last completed one for a cancelled order and skips the rest", () => {
    const view = deriveSaga(
      input({
        order: order("cancelled", at(3)),
        events: [changed("pending", null, 0), changed("reserved", "pending", 1), changed("cancelled", "reserved", 3)],
        payment: payment("failed"),
        reservations: [reservation("released")],
      }),
    );
    expect(states(view)).toEqual(["complete", "complete", "failed", "skipped", "skipped"]);
    expect(view.steps[2]?.note).toBe("Charge declined");
    expect(view.steps[2]?.at).toBe(at(3));
  });

  it("counts unpublished outbox rows", () => {
    const view = deriveSaga(input({ events: [changed("pending", null, 0), outbox("order.created", at(0), {}, false)] }));
    expect(view.unpublished).toBe(1);
  });
});

describe("explainOrder", () => {
  const explain = (overrides: Partial<SagaInput>, live: Parameters<typeof explainOrder>[2] = []) => {
    const value = input(overrides);
    return explainOrder(value, deriveSaga(value), live);
  };

  it("says nothing about a healthy in-flight order", () => {
    expect(explain({})).toBeNull();
  });

  it("explains a stock rejection with the reason seen live", () => {
    const result = explain(
      { order: order("cancelled", at(1)), events: [changed("pending", null, 0), changed("cancelled", "pending", 1)] },
      [{ type: "inventory.failed", data: { order_id: ORDER_ID, reason: "insufficient stock" }, receivedAt: at(1) }],
    );
    expect(result?.title).toBe("Stock could not be reserved");
    expect(result?.detail).toContain("insufficient stock");
  });

  it("recognises a reconciler timeout while waiting for stock", () => {
    const result = explain({
      order: order("cancelled", at(16 * 60)),
      events: [changed("pending", null, 0), changed("cancelled", "pending", 16 * 60)],
    });
    expect(result?.title).toBe("Timed out waiting for stock");
  });

  it("flags a charge that landed after cancellation without a refund", () => {
    const result = explain({
      order: order("cancelled", at(3)),
      events: [changed("pending", null, 0), changed("reserved", "pending", 1), changed("cancelled", "reserved", 3)],
      payment: payment("succeeded"),
    });
    expect(result).toMatchObject({ tone: "danger", title: "Charged but cancelled" });
  });

  it("reports a pending refund once one was requested", () => {
    const result = explain({
      order: order("cancelled", at(3)),
      events: [
        changed("pending", null, 0),
        changed("reserved", "pending", 1),
        changed("cancelled", "reserved", 3),
        outbox("refund.requested", at(4)),
      ],
      payment: payment("succeeded"),
    });
    expect(result?.title).toBe("Refund pending");
  });

  it("notes refunded late charges and released stock", () => {
    const result = explain({
      order: order("cancelled", at(3)),
      events: [changed("pending", null, 0), changed("reserved", "pending", 1), changed("cancelled", "reserved", 3)],
      payment: payment("refunded"),
      reservations: [reservation("released")],
    });
    expect(result?.tone).toBe("warning");
    expect(result?.detail).toContain("released back to inventory");
  });

  it("points at the outbox relay when events are unpublished", () => {
    const result = explain({ events: [changed("pending", null, 0), outbox("order.created", at(0), {}, false)] });
    expect(result?.title).toBe("Events waiting for the outbox relay");
  });

  it("calls out an overdue in-flight order", () => {
    const result = explain({ now: Date.parse(at(20 * 60)) });
    expect(result?.title).toBe("Stuck in pending");
  });
});
