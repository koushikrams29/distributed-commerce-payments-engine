import { describe, expect, it } from "vitest";

import { matchRoute, orderPath } from "./router";

describe("matchRoute", () => {
  it("matches every page, with or without a trailing slash", () => {
    expect(matchRoute("/")).toEqual({ name: "overview" });
    expect(matchRoute("/orders")).toEqual({ name: "orders" });
    expect(matchRoute("/orders/")).toEqual({ name: "orders" });
    expect(matchRoute("/events")).toEqual({ name: "events" });
    expect(matchRoute("/payments")).toEqual({ name: "payments" });
    expect(matchRoute("/inventory")).toEqual({ name: "inventory" });
    expect(matchRoute("/failures")).toEqual({ name: "failures" });
    expect(matchRoute("/services")).toEqual({ name: "services" });
  });

  it("extracts the order ID from a detail path", () => {
    const id = "3f2b9c1e-8d4a-4e2b-9a7c-1b2c3d4e5f60";
    expect(matchRoute(`/orders/${id}`)).toEqual({ name: "order", orderId: id });
    expect(matchRoute(orderPath("a b"))).toEqual({ name: "order", orderId: "a b" });
  });

  it("returns not-found for anything else", () => {
    expect(matchRoute("/orders/1/items")).toEqual({ name: "not-found" });
    expect(matchRoute("/dashboard")).toEqual({ name: "not-found" });
    expect(matchRoute("/constructor")).toEqual({ name: "not-found" });
  });
});
