import { formatMoney, shortId } from "../lib/format";
import type { DashboardEvent } from "../types";

export type EventTone = "info" | "success" | "warning" | "danger";

export interface EventDescription {
  title: string;
  detail: string;
  tone: EventTone;
}

function text(data: Record<string, unknown>, key: string): string | null {
  const value = data[key];
  return typeof value === "string" ? value : null;
}

function order(data: Record<string, unknown>): string {
  const id = text(data, "order_id");
  return id ? `Order ${shortId(id)}` : "Order";
}

function amount(data: Record<string, unknown>): string {
  const raw = text(data, "amount") ?? text(data, "total_amount");
  return raw && !Number.isNaN(Number(raw)) ? ` · ${formatMoney(Number(raw))}` : "";
}

/** Turns a raw bus event into a one-line, human-readable feed entry. */
export function describeEvent(event: DashboardEvent): EventDescription {
  const { data } = event;
  switch (event.type) {
    case "order.status_changed": {
      const previous = text(data, "previous_status");
      const status = text(data, "status") ?? "unknown";
      return {
        title: previous ? `${order(data)} ${previous} → ${status}` : `${order(data)} placed`,
        detail: `Status change${amount(data)}`,
        tone:
          status === "cancelled" ? "danger" : status === "fulfilled" ? "success" : "info",
      };
    }
    case "order.created":
      return { title: `${order(data)} created`, detail: "Saga started", tone: "info" };
    case "inventory.reserved":
      return { title: `${order(data)} stock reserved`, detail: "Inventory", tone: "info" };
    case "inventory.failed":
      return {
        title: `${order(data)} reservation rejected`,
        detail: text(data, "reason") ?? "Reservation failed",
        tone: "danger",
      };
    case "inventory.committed":
      return { title: `${order(data)} stock committed`, detail: "Inventory", tone: "success" };
    case "charge.requested":
      return { title: `${order(data)} charge requested`, detail: `Payment${amount(data)}`, tone: "info" };
    case "payment.succeeded":
      return { title: `${order(data)} payment captured`, detail: `Payment${amount(data)}`, tone: "success" };
    case "payment.failed":
      return {
        title: `${order(data)} payment declined`,
        detail: text(data, "reason") ?? "Payment",
        tone: "danger",
      };
    case "refund.requested":
      return { title: `${order(data)} refund requested`, detail: "Late payment on a cancelled order", tone: "warning" };
    case "payment.refunded":
      return { title: `${order(data)} refunded`, detail: `Payment${amount(data)}`, tone: "warning" };
    case "order.paid":
      return { title: `${order(data)} paid`, detail: "Fulfilment started", tone: "info" };
    case "order.cancelled":
      return { title: `${order(data)} compensation started`, detail: "Release reserved stock", tone: "warning" };
    case "order.fulfilled":
      return { title: `${order(data)} fulfilled`, detail: "Confirmation sent", tone: "success" };
    default:
      return { title: event.type, detail: "Event", tone: "info" };
  }
}

/** Events after which product stock levels may have changed. */
export function affectsStock(event: DashboardEvent): boolean {
  if (event.type.startsWith("inventory.")) return true;
  return event.type === "order.status_changed" && event.data.status === "cancelled";
}
