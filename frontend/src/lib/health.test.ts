import { describe, expect, it } from "vitest";

import type { ComponentHealth, OrderSummary, QueueStats, SystemHealth } from "../types";
import { OUTBOX_LAG_MS, QUEUE_BACKLOG, assessSystem, type AssessmentInput } from "./health";

const NOW = Date.parse("2026-10-04T12:00:00.000Z");

function component(name: string, status: ComponentHealth["status"] = "up", detail: string | null = null): ComponentHealth {
  return { name, kind: "service", status, detail, latencyMs: 4 };
}

function health(...components: ComponentHealth[]): SystemHealth {
  return { components, checkedAt: new Date(NOW).toISOString() };
}

function queue(overrides: Partial<QueueStats> = {}): QueueStats {
  return {
    name: "order.events",
    ready: 0,
    unacknowledged: 0,
    consumers: 1,
    retrying: 0,
    deadLettered: 0,
    publishRate: 0,
    deliverRate: 0,
    ...overrides,
  };
}

function summary(overrides: Partial<OrderSummary> = {}): OrderSummary {
  return {
    counts: { pending: 0, reserved: 0, paid: 0, fulfilled: 3, cancelled: 1 },
    total: 4,
    outbox: { unpublished: 0, oldestUnpublishedAt: null },
    overdue: [
      { status: "pending", count: 0, afterMinutes: 15 },
      { status: "paid", count: 0, afterMinutes: 10 },
    ],
    reconcilerEnabled: true,
    reconcileIntervalSeconds: 30,
    generatedAt: new Date(NOW).toISOString(),
    ...overrides,
  };
}

function assess(overrides: Partial<AssessmentInput> = {}) {
  return assessSystem({
    health: health(component("gateway"), component("order-service")),
    queues: { queues: [queue()], checkedAt: new Date(NOW).toISOString() },
    orders: summary(),
    connection: "live",
    now: NOW,
    ...overrides,
  });
}

describe("assessSystem", () => {
  it("is healthy when every check passes", () => {
    expect(assess()).toEqual({ verdict: "healthy", headline: "All systems operational", issues: [] });
  });

  it("stays unknown until the first health check answers", () => {
    expect(assess({ health: undefined }).verdict).toBe("unknown");
  });

  it("is degraded when a component is down and lists the detail", () => {
    const result = assess({ health: health(component("gateway"), component("payment-service", "down", "unreachable")) });
    expect(result.verdict).toBe("degraded");
    expect(result.headline).toBe("Degraded — 1 problem need action");
    expect(result.issues[0]).toEqual({
      severity: "danger",
      text: "payment-service is down — unreachable",
      to: "/services",
    });
  });

  it("is degraded when the health endpoint itself fails", () => {
    const result = assess({ health: undefined, healthError: "Too many requests" });
    expect(result.verdict).toBe("degraded");
    expect(result.issues[0]?.text).toBe("Service health unavailable: Too many requests");
  });

  it("needs attention for dead letters and links to that queue", () => {
    const result = assess({ queues: { queues: [queue({ deadLettered: 2 })], checkedAt: "" } });
    expect(result.verdict).toBe("attention");
    expect(result.issues).toEqual([
      { severity: "warning", text: "2 dead letters on order.events", to: "/failures?queue=order.events" },
    ]);
  });

  it("treats a queue without consumers as a problem and a backlog as a warning", () => {
    const result = assess({
      queues: { queues: [queue({ consumers: 0, ready: QUEUE_BACKLOG + 1 })], checkedAt: "" },
    });
    expect(result.issues.map((issue) => issue.severity)).toEqual(["danger", "warning"]);
  });

  it("only flags the outbox once it lags beyond the threshold", () => {
    const behind = (ms: number) =>
      assess({
        orders: summary({
          outbox: { unpublished: 3, oldestUnpublishedAt: new Date(NOW - ms).toISOString() },
        }),
      });
    expect(behind(OUTBOX_LAG_MS - 1000).verdict).toBe("healthy");
    const late = behind(OUTBOX_LAG_MS + 15_000);
    expect(late.verdict).toBe("degraded");
    expect(late.issues[0]?.text).toBe("Outbox relay is behind: 3 events unpublished, oldest 45 s");
  });

  it("reports overdue orders, a disabled reconciler and an offline stream", () => {
    const result = assess({
      orders: summary({
        overdue: [{ status: "paid", count: 1, afterMinutes: 10 }],
        reconcilerEnabled: false,
      }),
      connection: "offline",
    });
    expect(result.verdict).toBe("attention");
    expect(result.headline).toBe("Operational — 3 items to review");
    expect(result.issues.map((issue) => issue.to)).toEqual(["/orders?status=paid", "/failures", "/events"]);
  });

  it("sorts problems before warnings", () => {
    const result = assess({
      health: health(component("gateway", "degraded"), component("redis", "down")),
    });
    expect(result.issues.map((issue) => issue.severity)).toEqual(["danger", "warning"]);
  });
});
