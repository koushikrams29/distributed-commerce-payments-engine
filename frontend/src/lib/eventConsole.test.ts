import { describe, expect, it } from "vitest";

import type { FeedEntry } from "../dashboard/state";
import { eventOutcome, matchesFilters, perMinute, stepGaps, type ConsoleFilters } from "./eventConsole";

const NOW = Date.parse("2026-10-04T12:00:00.000Z");
const secondsAgo = (seconds: number) => new Date(NOW - seconds * 1000).toISOString();

function entry(
  seq: number,
  type: string,
  data: Record<string, unknown>,
  receivedAt: string,
  traceId: string | null = null,
): FeedEntry {
  return { seq, event: { type, data, receivedAt, traceId } };
}

const NO_FILTERS: ConsoleFilters = { type: null, source: null, outcome: null, orderId: null, text: "" };

// Newest first, as the live feed keeps it.
const feed: FeedEntry[] = [
  entry(5, "payment.failed", { order_id: "o-2", reason: "card declined" }, secondsAgo(5)),
  entry(4, "inventory.reserved", { order_id: "o-2" }, secondsAgo(20)),
  entry(3, "payment.succeeded", { order_id: "o-1", amount: "40.00" }, secondsAgo(30), "abc123"),
  entry(2, "inventory.reserved", { order_id: "o-1" }, secondsAgo(32)),
  entry(1, "order.created", { order_id: "o-1" }, secondsAgo(120)),
];

describe("eventOutcome", () => {
  it("classifies failures, compensation and normal progress", () => {
    expect(eventOutcome(feed[0] as FeedEntry)).toBe("failed");
    expect(eventOutcome(feed[2] as FeedEntry)).toBe("ok");
    expect(eventOutcome(entry(9, "inventory.failed", { order_id: "o-3" }, secondsAgo(1)))).toBe("failed");
    expect(eventOutcome(entry(9, "order.cancelled", { order_id: "o-3" }, secondsAgo(1)))).toBe("compensation");
  });
});

describe("stepGaps", () => {
  it("measures each event from the previous one for the same order", () => {
    const gaps = stepGaps(feed);
    expect(gaps.get(2)).toBe(88_000);
    expect(gaps.get(3)).toBe(2_000);
    expect(gaps.get(5)).toBe(15_000);
    expect(gaps.has(1)).toBe(false);
    expect(gaps.has(4)).toBe(false);
  });

  it("ignores events without an order or a readable time", () => {
    const gaps = stepGaps([
      entry(2, "order.created", { order_id: "o-9" }, "not a time"),
      entry(1, "payment.refunded", {}, secondsAgo(1)),
    ]);
    expect(gaps.size).toBe(0);
  });
});

describe("matchesFilters", () => {
  const matching = (filters: Partial<ConsoleFilters>) =>
    feed.filter((item) => matchesFilters(item, { ...NO_FILTERS, ...filters })).map((item) => item.seq);

  it("passes everything without filters", () => {
    expect(matching({})).toEqual([5, 4, 3, 2, 1]);
  });

  it("filters by type, publishing service, order and outcome", () => {
    expect(matching({ type: "inventory.reserved" })).toEqual([4, 2]);
    expect(matching({ source: "payment-service" })).toEqual([5, 3]);
    expect(matching({ orderId: "o-1" })).toEqual([3, 2, 1]);
    expect(matching({ outcome: "failures" })).toEqual([5]);
  });

  it("searches type, payload and trace ID, ignoring case", () => {
    expect(matching({ text: "DECLINED" })).toEqual([5]);
    expect(matching({ text: "abc1" })).toEqual([3]);
    expect(matching({ text: "  order.created " })).toEqual([1]);
  });
});

describe("perMinute", () => {
  it("counts events received in the last minute", () => {
    expect(perMinute(feed, NOW)).toBe(4);
    expect(perMinute([], NOW)).toBe(0);
  });
});
