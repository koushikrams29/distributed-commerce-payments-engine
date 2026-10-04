export const ORDER_STATUSES = [
  "pending",
  "reserved",
  "paid",
  "fulfilled",
  "cancelled",
] as const;

export type OrderStatus = (typeof ORDER_STATUSES)[number];

export const PAYMENT_STATUSES = ["pending", "succeeded", "failed", "refunded"] as const;
export type PaymentStatus = (typeof PAYMENT_STATUSES)[number];

export const RESERVATION_STATUSES = ["held", "committed", "released"] as const;
export type ReservationStatus = (typeof RESERVATION_STATUSES)[number];

/** An order as the live view tracks it: from the snapshot or from status events. */
export interface Order {
  id: string;
  userId: string;
  status: OrderStatus;
  totalAmount: number;
  /** Null when the order was first seen through a live event, not the snapshot. */
  createdAt: string | null;
  updatedAt: string;
  itemCount: number | null;
}

export interface OrderItem {
  id: string;
  productId: string;
  qty: number;
  unitPrice: number;
}

/** An order as the order service stores it. */
export interface OrderRecord {
  id: string;
  userId: string;
  status: OrderStatus;
  totalAmount: number;
  createdAt: string;
  updatedAt: string;
  items: OrderItem[];
}

/** One outbox row: an event the order service emitted about an order. */
export interface OrderEvent {
  id: string;
  eventType: string;
  payload: Record<string, unknown>;
  createdAt: string;
  /** Null while the row waits for the outbox relay. */
  publishedAt: string | null;
  traceId: string | null;
}

export interface OverdueOrders {
  status: OrderStatus;
  count: number;
  afterMinutes: number;
}

export interface OrderSummary {
  counts: Record<OrderStatus, number>;
  total: number;
  outbox: { unpublished: number; oldestUnpublishedAt: string | null };
  overdue: OverdueOrders[];
  reconcilerEnabled: boolean;
  reconcileIntervalSeconds: number;
  generatedAt: string;
}

export interface LedgerEntry {
  id: string;
  direction: "debit" | "credit";
  amount: number;
  createdAt: string;
}

export interface Payment {
  paymentId: string;
  orderId: string;
  status: PaymentStatus;
  amount: number;
  idempotencyKey: string;
  createdAt: string;
  ledger: LedgerEntry[];
}

export interface PaymentSummary {
  counts: Record<PaymentStatus, number>;
  total: number;
  captured: number;
  refunded: number;
  net: number;
  generatedAt: string;
}

export interface Product {
  id: string;
  name: string;
  price: number;
  /** Units that can still be reserved; held units are already deducted. */
  available: number;
  reserved: number;
  committed: number;
}

export interface Reservation {
  id: string;
  orderId: string;
  productId: string;
  productName: string;
  qty: number;
  status: ReservationStatus;
  expiresAt: string;
  createdAt: string;
}

export interface Page<T> {
  items: T[];
  nextCursor: string | null;
}

export type HealthStatus = "up" | "degraded" | "down";

export interface ComponentHealth {
  name: string;
  kind: "service" | "infrastructure";
  status: HealthStatus;
  detail: string | null;
  latencyMs: number | null;
}

export interface SystemHealth {
  components: ComponentHealth[];
  checkedAt: string;
}

export interface QueueStats {
  name: string;
  ready: number;
  unacknowledged: number;
  consumers: number;
  retrying: number;
  deadLettered: number;
  publishRate: number;
  deliverRate: number;
}

export interface QueueOverview {
  queues: QueueStats[];
  checkedAt: string;
}

export interface DeadLetter {
  routingKey: string | null;
  payload: Record<string, unknown> | string;
  orderId: string | null;
  retryCount: number | null;
  lastError: string | null;
  deadLetteredAt: string | null;
  messageId: string | null;
}

export interface DeadLetterPage {
  queue: string;
  total: number;
  messages: DeadLetter[];
}

/** One message relayed by the gateway from the commerce.events exchange. */
export interface DashboardEvent {
  type: string;
  data: Record<string, unknown>;
  receivedAt: string;
  /** Trace that produced the event, when the publisher was traced. */
  traceId?: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

function isOneOf<T extends string>(values: readonly T[], value: unknown): value is T {
  return typeof value === "string" && (values as readonly string[]).includes(value);
}

export function isOrderStatus(value: unknown): value is OrderStatus {
  return isOneOf(ORDER_STATUSES, value);
}

export function isPaymentStatus(value: unknown): value is PaymentStatus {
  return isOneOf(PAYMENT_STATUSES, value);
}

export function isReservationStatus(value: unknown): value is ReservationStatus {
  return isOneOf(RESERVATION_STATUSES, value);
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID.test(value);
}
