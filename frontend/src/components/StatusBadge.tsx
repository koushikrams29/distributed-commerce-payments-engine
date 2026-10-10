import type { ReactNode } from "react";

import { titleCase } from "../lib/format";
import type { HealthStatus, OrderStatus, PaymentStatus, ReservationStatus } from "../types";

export type BadgeTone = "neutral" | "info" | "accent" | "success" | "warning" | "danger";

const ORDER_TONES: Record<OrderStatus, BadgeTone> = {
  pending: "neutral",
  reserved: "info",
  paid: "accent",
  fulfilled: "success",
  cancelled: "danger",
};

const PAYMENT_TONES: Record<PaymentStatus, BadgeTone> = {
  pending: "neutral",
  unknown: "warning",
  succeeded: "success",
  failed: "danger",
  refunded: "warning",
};

const RESERVATION_TONES: Record<ReservationStatus, BadgeTone> = {
  held: "info",
  committed: "success",
  released: "neutral",
};

const HEALTH_TONES: Record<HealthStatus, BadgeTone> = {
  up: "success",
  degraded: "warning",
  down: "danger",
};

export function Badge({ tone, children }: { tone: BadgeTone; children: ReactNode }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

export function StatusBadge({ status }: { status: OrderStatus }) {
  return <Badge tone={ORDER_TONES[status]}>{titleCase(status)}</Badge>;
}

export function PaymentBadge({ status }: { status: PaymentStatus }) {
  return <Badge tone={PAYMENT_TONES[status]}>{titleCase(status)}</Badge>;
}

export function ReservationBadge({ status }: { status: ReservationStatus }) {
  return <Badge tone={RESERVATION_TONES[status]}>{titleCase(status)}</Badge>;
}

export function HealthBadge({ status }: { status: HealthStatus }) {
  return <Badge tone={HEALTH_TONES[status]}>{titleCase(status)}</Badge>;
}

export function orderTone(status: OrderStatus): BadgeTone {
  return ORDER_TONES[status];
}
