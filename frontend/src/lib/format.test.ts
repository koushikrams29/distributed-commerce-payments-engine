import { describe, expect, it } from "vitest";

import { durationBetween, formatDuration, formatPercent, formatRate, shortId } from "./format";

describe("formatDuration", () => {
  it.each([
    [450, "450 ms"],
    [2_340, "2.3 s"],
    [42_000, "42 s"],
    [60_000, "1 min"],
    [125_000, "2 min 5 s"],
    [3_600_000, "1 h"],
    [5_400_000, "1 h 30 min"],
    [3 * 86_400_000, "3 d"],
  ])("formats %d ms as %s", (ms, expected) => {
    expect(formatDuration(ms)).toBe(expected);
  });

  it("shows a dash for negative or invalid durations", () => {
    expect(formatDuration(-1)).toBe("—");
    expect(formatDuration(Number.NaN)).toBe("—");
  });
});

describe("durationBetween", () => {
  it("returns milliseconds between two instants, or null when either is missing", () => {
    expect(durationBetween("2026-10-04T10:00:00Z", "2026-10-04T10:00:01.500Z")).toBe(1500);
    expect(durationBetween(null, "2026-10-04T10:00:00Z")).toBeNull();
  });
});

describe("rates and ratios", () => {
  it("formats message rates and percentages", () => {
    expect(formatRate(0)).toBe("0/s");
    expect(formatRate(0.05)).toBe("<0.1/s");
    expect(formatRate(2.25)).toBe("2.3/s");
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(0.5)).toBe("50%");
    expect(formatPercent(0.042)).toBe("4.2%");
  });

  it("shortens IDs to their first eight characters", () => {
    expect(shortId("3f2b9c1e-8d4a-4e2b-9a7c-1b2c3d4e5f60")).toBe("3f2b9c1e");
  });
});
