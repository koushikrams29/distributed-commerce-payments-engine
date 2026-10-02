import { describe, expect, it } from "vitest";

import type { DashboardEvent } from "../types";
import { affectsStock, describeEvent } from "./events";

function event(type: string, data: Record<string, unknown> = {}): DashboardEvent {
  return { type, data, receivedAt: "2026-10-02T10:00:00Z" };
}

const ORDER = { order_id: "abcdef12-0000-0000-0000-000000000000" };

describe("describeEvent", () => {
  it("describes a placed order", () => {
    const description = describeEvent(
      event("order.status_changed", { ...ORDER, status: "pending", previous_status: null }),
    );
    expect(description.title).toBe("Order abcdef12 placed");
    expect(description.tone).toBe("info");
  });

  it("describes a transition and colours terminal states", () => {
    const fulfilled = describeEvent(
      event("order.status_changed", { ...ORDER, status: "fulfilled", previous_status: "paid" }),
    );
    const cancelled = describeEvent(
      event("order.status_changed", { ...ORDER, status: "cancelled", previous_status: "reserved" }),
    );

    expect(fulfilled.title).toBe("Order abcdef12 paid → fulfilled");
    expect(fulfilled.tone).toBe("success");
    expect(cancelled.tone).toBe("danger");
  });

  it("includes the reason for a declined payment", () => {
    const description = describeEvent(event("payment.failed", { ...ORDER, reason: "card declined" }));
    expect(description.detail).toBe("card declined");
    expect(description.tone).toBe("danger");
  });

  it("falls back to the raw routing key for unknown events", () => {
    expect(describeEvent(event("shipping.label_printed")).title).toBe("shipping.label_printed");
  });

  it("copes with a payload that has no order id", () => {
    expect(describeEvent(event("order.fulfilled")).title).toBe("Order fulfilled");
  });
});

describe("affectsStock", () => {
  it.each([
    ["inventory.reserved", {}, true],
    ["inventory.committed", {}, true],
    ["order.status_changed", { status: "cancelled" }, true],
    ["order.status_changed", { status: "paid" }, false],
    ["payment.succeeded", {}, false],
  ])("%s %o → %s", (type, data, expected) => {
    expect(affectsStock(event(type, data))).toBe(expected);
  });
});
