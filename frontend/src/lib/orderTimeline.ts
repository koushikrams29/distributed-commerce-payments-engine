import type { TimelineEntry } from "../components/Timeline";
import type { DashboardEvent, OrderEvent, OrderRecord, Payment, Reservation } from "../types";
import { isOrderStatus } from "../types";
import { formatMoney } from "./format";
import type { Tone } from "./saga";
import { eventRoute } from "./topology";

/** Live events whose facts no service stores, so the stream is their only record. */
const LIVE_ONLY = new Set(["inventory.failed", "payment.failed", "inventory.committed"]);

function money(value: unknown): string {
  const amount = Number(value);
  return Number.isFinite(amount) ? formatMoney(amount) : "";
}

function recipients(type: string): string | undefined {
  const consumers = eventRoute(type).consumers;
  return consumers.length ? `Delivered to ${consumers.join(", ")}` : undefined;
}

function outboxEntry(event: OrderEvent, paidSendsSoFar: number): TimelineEntry {
  const base = {
    key: `outbox:${event.id}`,
    at: event.createdAt,
    source: "order-service",
    eventType: event.eventType,
    traceId: event.traceId,
    unpublished: event.publishedAt === null,
  };
  const { payload } = event;
  switch (event.eventType) {
    case "order.status_changed": {
      const status = isOrderStatus(payload.status) ? payload.status : "unknown";
      const previous = isOrderStatus(payload.previous_status) ? payload.previous_status : null;
      const tone: Tone = status === "cancelled" ? "danger" : status === "fulfilled" ? "success" : "info";
      return {
        ...base,
        at: typeof payload.occurred_at === "string" ? payload.occurred_at : event.createdAt,
        title: previous ? `Status ${previous} → ${status}` : `Order placed (${status})`,
        tone,
        detail: "Shown on the live console",
      };
    }
    case "order.created":
      return { ...base, title: "Saga started: stock requested", tone: "info", detail: recipients(event.eventType) };
    case "charge.requested":
      return {
        ...base,
        title: `Charge requested ${money(payload.amount)}`.trim(),
        tone: "info",
        detail: typeof payload.idempotency_key === "string" ? `Idempotency key ${payload.idempotency_key}` : undefined,
      };
    case "order.paid":
      return paidSendsSoFar === 0
        ? { ...base, title: "Stock commit requested", tone: "info", detail: recipients(event.eventType) }
        : {
            ...base,
            title: "Stock commit re-sent by the reconciler",
            tone: "warning",
            detail: "Inventory had not confirmed the commit in time",
          };
    case "order.cancelled":
      return { ...base, title: "Compensation: release reserved stock", tone: "warning", detail: recipients(event.eventType) };
    case "refund.requested":
      return { ...base, title: "Refund requested for a late charge", tone: "warning", detail: recipients(event.eventType) };
    case "order.fulfilled":
      return { ...base, title: "Fulfilment published", tone: "success", detail: recipients(event.eventType) };
    default:
      return { ...base, title: event.eventType, tone: "info" };
  }
}

function liveEntry(event: DashboardEvent, index: number): TimelineEntry {
  const reason = typeof event.data.reason === "string" ? event.data.reason : null;
  const source = eventRoute(event.type).source ?? "unknown";
  const common = {
    key: `live:${index}:${event.type}:${event.receivedAt}`,
    at: event.receivedAt,
    source,
    eventType: event.type,
    traceId: event.traceId ?? null,
    live: true,
  };
  switch (event.type) {
    case "inventory.failed":
      return { ...common, title: "Reservation rejected", tone: "danger", detail: reason ?? undefined };
    case "payment.failed":
      return { ...common, title: "Charge declined", tone: "danger", detail: reason ?? undefined };
    default:
      return { ...common, title: "Stock committed", tone: "success" };
  }
}

export interface TimelineInput {
  order: OrderRecord;
  events: OrderEvent[];
  payment: Payment | null;
  reservations: Reservation[];
  /** Live events for this order seen in this session. */
  liveEvents: DashboardEvent[];
}

/** Everything known about one order, from every service, oldest first. */
export function buildTimeline({ events, payment, reservations, liveEvents }: TimelineInput): TimelineEntry[] {
  const entries: TimelineEntry[] = [];

  let paidSends = 0;
  for (const event of events) {
    entries.push(outboxEntry(event, paidSends));
    if (event.eventType === "order.paid") paidSends += 1;
  }

  for (const reservation of reservations) {
    entries.push({
      key: `reservation:${reservation.id}`,
      at: reservation.createdAt,
      source: "inventory-service",
      title: `Reserved ${reservation.qty} × ${reservation.productName}`,
      tone: "info",
      detail: `Now ${reservation.status}`,
    });
  }

  if (payment) {
    const outcome: Record<Payment["status"], [string, Tone]> = {
      pending: ["Charge pending", "info"],
      succeeded: ["Charge succeeded", "success"],
      failed: ["Charge declined", "danger"],
      refunded: ["Charge captured, later refunded", "warning"],
    };
    const [title, tone] = outcome[payment.status];
    entries.push({
      key: `payment:${payment.paymentId}`,
      at: payment.createdAt,
      source: "payment-service",
      title: `${title} ${formatMoney(payment.amount)}`,
      tone,
      detail: `Idempotency key ${payment.idempotencyKey}`,
    });
    for (const entry of payment.ledger) {
      entries.push({
        key: `ledger:${entry.id}`,
        at: entry.createdAt,
        source: "payment-service",
        title:
          entry.direction === "debit"
            ? `Ledger debit ${formatMoney(entry.amount)}`
            : `Ledger credit ${formatMoney(entry.amount)} (refund)`,
        tone: entry.direction === "debit" ? "success" : "warning",
      });
    }
  }

  liveEvents.forEach((event, index) => {
    if (LIVE_ONLY.has(event.type)) entries.push(liveEntry(event, index));
  });

  return entries.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
}

/** Distinct traces behind an order, in the order they first appear. */
export function traceIds(events: OrderEvent[], liveEvents: DashboardEvent[]): string[] {
  const ids = [...events.map((event) => event.traceId), ...liveEvents.map((event) => event.traceId ?? null)];
  return [...new Set(ids.filter((id): id is string => typeof id === "string"))];
}
