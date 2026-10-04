import { describe, expect, it } from "vitest";

import { WORK_QUEUES, eventRoute, publishedBy, serviceForQueue } from "./topology";

describe("topology", () => {
  it("mirrors the queue bindings each service declares", () => {
    const bindings = Object.fromEntries(WORK_QUEUES.map((item) => [item.queue, item.routingKeys]));
    expect(bindings).toEqual({
      "order.events": [
        "inventory.reserved",
        "inventory.failed",
        "inventory.committed",
        "payment.succeeded",
        "payment.failed",
      ],
      "inventory.events": ["order.created", "order.cancelled", "order.paid"],
      "payment.events": ["charge.requested", "refund.requested"],
      "notification.events": ["order.fulfilled"],
      "recommendation.events": ["payment.succeeded"],
    });
  });

  it("knows who publishes what", () => {
    expect(publishedBy("payment-service")).toEqual(["payment.succeeded", "payment.failed", "payment.refunded"]);
    expect(publishedBy("notification-service")).toEqual([]);
  });

  it("maps queues back to their service", () => {
    expect(serviceForQueue("inventory.events")).toBe("inventory-service");
    expect(serviceForQueue("gateway.dashboard")).toBeNull();
  });

  it("treats unknown event types, including prototype names, as unrouted", () => {
    expect(eventRoute("constructor")).toEqual({ source: null, consumers: [] });
    expect(eventRoute("shipment.created")).toEqual({ source: null, consumers: [] });
  });
});
