import { describe, expect, it } from "vitest";

import { parseMessage } from "./useDashboardSocket";

describe("parseMessage", () => {
  it("recognises the ready handshake", () => {
    expect(parseMessage(JSON.stringify({ type: "ready" }))).toBe("ready");
  });

  it("maps a relayed event, including its trace", () => {
    const message = JSON.stringify({
      type: "payment.succeeded",
      data: { order_id: "o-1" },
      received_at: "2026-10-04T10:00:00.000Z",
      trace_id: "4bf92f3577b34da6a3ce929d0e0e4736",
    });
    expect(parseMessage(message)).toEqual({
      type: "payment.succeeded",
      data: { order_id: "o-1" },
      receivedAt: "2026-10-04T10:00:00.000Z",
      traceId: "4bf92f3577b34da6a3ce929d0e0e4736",
    });
  });

  it("tolerates missing or malformed fields", () => {
    const parsed = parseMessage(JSON.stringify({ type: "order.created", data: [1, 2], trace_id: 7 }));
    expect(parsed).toMatchObject({ type: "order.created", data: {}, traceId: null });
    expect(typeof (parsed as { receivedAt: string }).receivedAt).toBe("string");
  });

  it("rejects frames that aren't events", () => {
    expect(parseMessage("not json")).toBeNull();
    expect(parseMessage(JSON.stringify({ data: {} }))).toBeNull();
  });
});
