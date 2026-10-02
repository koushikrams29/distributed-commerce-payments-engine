import { describe, expect, it } from "vitest";

import { BASE_DELAY_MS, MAX_DELAY_MS, reconnectDelay } from "./backoff";

describe("reconnectDelay", () => {
  it("doubles the ceiling with every attempt", () => {
    const atCeiling = () => 1;
    expect(reconnectDelay(0, atCeiling)).toBe(BASE_DELAY_MS);
    expect(reconnectDelay(1, atCeiling)).toBe(BASE_DELAY_MS * 2);
    expect(reconnectDelay(3, atCeiling)).toBe(BASE_DELAY_MS * 8);
  });

  it("never waits longer than the cap", () => {
    expect(reconnectDelay(50, () => 1)).toBe(MAX_DELAY_MS);
  });

  it("spreads clients randomly below the ceiling", () => {
    expect(reconnectDelay(2, () => 0)).toBe(0);
    expect(reconnectDelay(2, () => 0.5)).toBe(BASE_DELAY_MS * 2);
  });
});
