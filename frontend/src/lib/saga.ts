import {
  isOrderStatus,
  type DashboardEvent,
  type OrderEvent,
  type OrderRecord,
  type OrderStatus,
  type OverdueOrders,
  type Payment,
  type Reservation,
} from "../types";
import { formatDuration } from "./format";

export type StepState = "complete" | "active" | "retrying" | "waiting" | "failed" | "skipped";

export type StepKey = "placed" | "reserved" | "paid" | "committed" | "fulfilled";

export interface SagaStep {
  key: StepKey;
  label: string;
  /** The service that performs the step. */
  service: string;
  state: StepState;
  at: string | null;
  note: string | null;
}

export interface SagaView {
  steps: SagaStep[];
  /** When the order reached a terminal status; null while in flight. */
  finishedAt: string | null;
  /** Placed → terminal status, or → now while in flight. */
  durationMs: number;
  /** In flight past the reconciler's timeout for its status. */
  overdue: boolean;
  /** Outbox rows the relay has not published yet. */
  unpublished: number;
}

const STEP_DEFINITIONS: { key: StepKey; label: string; service: string }[] = [
  { key: "placed", label: "Order placed", service: "order-service" },
  { key: "reserved", label: "Stock reserved", service: "inventory-service" },
  { key: "paid", label: "Payment captured", service: "payment-service" },
  { key: "committed", label: "Stock committed", service: "inventory-service" },
  { key: "fulfilled", label: "Fulfilled", service: "notification-service" },
];

/** How many steps are done once an order holds each status. */
const STEPS_DONE: Record<Exclude<OrderStatus, "cancelled">, number> = {
  pending: 1,
  reserved: 2,
  paid: 3,
  fulfilled: 5,
};

interface Transition {
  status: OrderStatus;
  previous: OrderStatus | null;
  at: string;
}

export function transitions(events: OrderEvent[]): Transition[] {
  return events.flatMap((event) => {
    if (event.eventType !== "order.status_changed") return [];
    const { status, previous_status, occurred_at } = event.payload;
    if (!isOrderStatus(status)) return [];
    return [
      {
        status,
        previous: isOrderStatus(previous_status) ? previous_status : null,
        at: typeof occurred_at === "string" ? occurred_at : event.createdAt,
      },
    ];
  });
}

function reachedAt(list: Transition[], status: OrderStatus): string | null {
  return list.find((item) => item.status === status)?.at ?? null;
}

/** The last status before cancellation, from the transition history or the evidence left behind. */
export function statusBeforeCancel(
  list: Transition[],
  payment: Payment | null,
  reservations: Reservation[],
): Exclude<OrderStatus, "cancelled" | "fulfilled"> {
  const previous = list.find((item) => item.status === "cancelled")?.previous;
  if (previous === "pending" || previous === "reserved" || previous === "paid") return previous;
  if (payment) return "reserved";
  return reservations.length > 0 ? "reserved" : "pending";
}

export function overdueThresholds(overdue: OverdueOrders[]): Partial<Record<OrderStatus, number>> {
  return Object.fromEntries(overdue.map((item) => [item.status, item.afterMinutes]));
}

export interface SagaInput {
  order: OrderRecord;
  events: OrderEvent[];
  payment: Payment | null;
  reservations: Reservation[];
  /** Reconciler timeouts in minutes, by status. */
  thresholds: Partial<Record<OrderStatus, number>>;
  now: number;
}

export function deriveSaga({ order, events, payment, reservations, thresholds, now }: SagaInput): SagaView {
  const history = transitions(events);
  const paidSends = events.filter((event) => event.eventType === "order.paid").length;
  const unpublished = events.filter((event) => event.publishedAt === null).length;
  const terminal = order.status === "fulfilled" || order.status === "cancelled";
  const finishedAt = terminal ? (reachedAt(history, order.status) ?? order.updatedAt) : null;
  const durationMs = Date.parse(finishedAt ?? new Date(now).toISOString()) - Date.parse(order.createdAt);

  // The reconciler measures pending/reserved from creation and paid from the last update.
  const threshold = thresholds[order.status];
  const clockStart = order.status === "paid" ? order.updatedAt : order.createdAt;
  const overdue =
    !terminal && threshold !== undefined && now - Date.parse(clockStart) > threshold * 60_000;

  const timeFor: Record<StepKey, string | null> = {
    placed: order.createdAt,
    reserved: reachedAt(history, "reserved"),
    paid: reachedAt(history, "paid"),
    committed: reachedAt(history, "fulfilled"),
    fulfilled:
      events.find((event) => event.eventType === "order.fulfilled")?.publishedAt ??
      reachedAt(history, "fulfilled"),
  };

  let done: number;
  let failedIndex: number | null = null;
  if (order.status === "cancelled") {
    const before = statusBeforeCancel(history, payment, reservations);
    done = STEPS_DONE[before];
    failedIndex = done;
  } else {
    done = STEPS_DONE[order.status];
  }

  const steps = STEP_DEFINITIONS.map((definition, index): SagaStep => {
    const base = { ...definition, at: timeFor[definition.key], note: null };
    if (index < done) return { ...base, state: "complete" };
    if (failedIndex !== null) {
      return index === failedIndex
        ? { ...base, state: "failed", at: finishedAt, note: failureNote(definition.key, payment) }
        : { ...base, state: "skipped", at: null };
    }
    if (index > done) return { ...base, state: "waiting", at: null };
    // The step the order is waiting on right now.
    if (definition.key === "committed" && paidSends > 1) {
      return {
        ...base,
        state: "retrying",
        at: null,
        note: `order.paid re-sent ${paidSends - 1}× by the reconciler`,
      };
    }
    const waitingFor = formatDuration(now - Date.parse(clockStart));
    return {
      ...base,
      state: "active",
      at: null,
      note: overdue ? `Waiting ${waitingFor} — past the ${threshold} min timeout` : `Waiting ${waitingFor}`,
    };
  });

  return { steps, finishedAt, durationMs, overdue, unpublished };
}

function failureNote(step: StepKey, payment: Payment | null): string {
  if (step === "reserved") return "No stock was reserved";
  if (step === "paid") {
    if (payment?.status === "failed") return "Charge declined";
    if (payment?.status === "refunded") return "Captured late, then refunded";
    return "No successful charge";
  }
  return "Stopped here";
}

export type Tone = "info" | "success" | "warning" | "danger";

export interface Explanation {
  tone: Tone;
  title: string;
  detail: string;
}

/**
 * What happened to an order that did not simply succeed, in operator terms,
 * from the evidence the services keep: transitions, the charge, reservations.
 */
export function explainOrder(
  input: SagaInput,
  view: SagaView,
  liveEvents: DashboardEvent[] = [],
): Explanation | null {
  const { order, events, payment, reservations, thresholds } = input;
  const history = transitions(events);
  const reason = (type: string) => {
    const value = liveEvents.find((event) => event.type === type)?.data.reason;
    return typeof value === "string" ? value : null;
  };
  const released = reservations.length > 0 && reservations.every((item) => item.status === "released");
  const stockNote = released
    ? " Its reserved stock was released back to inventory."
    : reservations.some((item) => item.status === "held")
      ? " Reserved stock is still held and will be released when the reservation expires."
      : "";

  if (order.status === "cancelled") {
    const before = statusBeforeCancel(history, payment, reservations);
    const elapsed = view.durationMs;
    const timedOut = (status: OrderStatus) => {
      const minutes = thresholds[status];
      return minutes !== undefined && elapsed >= minutes * 60_000;
    };

    if (before === "pending") {
      if (timedOut("pending")) {
        return {
          tone: "danger",
          title: "Timed out waiting for stock",
          detail: `No reservation arrived within ${thresholds.pending} min, so the reconciler cancelled the order after ${formatDuration(elapsed)}.`,
        };
      }
      const why = reason("inventory.failed");
      return {
        tone: "danger",
        title: "Stock could not be reserved",
        detail: why
          ? `Inventory rejected the reservation: ${why}. No payment was attempted.`
          : `Inventory rejected the reservation (insufficient stock or an unknown product) ${formatDuration(elapsed)} after the order was placed. No payment was attempted.`,
      };
    }

    if (payment?.status === "refunded") {
      return {
        tone: "warning",
        title: "Paid after cancellation, then refunded",
        detail: `The charge succeeded after the order had already been cancelled, so the customer was refunded.${stockNote}`,
      };
    }
    if (payment?.status === "succeeded") {
      const requested = events.some((event) => event.eventType === "refund.requested");
      return {
        tone: "danger",
        title: requested ? "Refund pending" : "Charged but cancelled",
        detail: requested
          ? "The charge landed after cancellation. A refund was requested and is waiting for the payment service."
          : "The order is cancelled but its charge succeeded and no refund has been requested. Check the payment consumer and its dead letters.",
      };
    }
    if (payment?.status === "failed") {
      return {
        tone: "danger",
        title: "Payment declined",
        detail: `${reason("payment.failed") ?? "The charge was declined by the payment service"}.${stockNote}`,
      };
    }
    if (timedOut("reserved")) {
      return {
        tone: "danger",
        title: "Timed out waiting for payment",
        detail: `No payment result arrived within ${thresholds.reserved} min, so the reconciler cancelled the order.${stockNote}`,
      };
    }
    return {
      tone: "danger",
      title: "Cancelled after reservation",
      detail: `The order was cancelled before a charge was recorded.${stockNote}`,
    };
  }

  if (view.unpublished > 0) {
    return {
      tone: "warning",
      title: "Events waiting for the outbox relay",
      detail: `${view.unpublished} event${view.unpublished === 1 ? " has" : "s have"} been written but not yet published to RabbitMQ, so the next service has not heard about this order.`,
    };
  }

  if (view.overdue) {
    const minutes = thresholds[order.status];
    if (order.status === "paid") {
      return {
        tone: "warning",
        title: "Stock commit is overdue",
        detail: `Paid but not committed for over ${minutes} min. The reconciler re-sends order.paid until inventory confirms; check inventory.events and its dead letters.`,
      };
    }
    return {
      tone: "warning",
      title: `Stuck in ${order.status}`,
      detail: `Past the ${minutes} min timeout for ${order.status} orders. The reconciler cancels it on its next pass.`,
    };
  }
  return null;
}
