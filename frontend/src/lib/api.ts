import {
  ORDER_STATUSES,
  PAYMENT_STATUSES,
  isOrderStatus,
  isPaymentStatus,
  isReservationStatus,
  type DeadLetterPage,
  type HealthStatus,
  type LedgerEntry,
  type Order,
  type OrderEvent,
  type OrderRecord,
  type OrderStatus,
  type OrderSummary,
  type Page,
  type Payment,
  type PaymentStatus,
  type PaymentSummary,
  type Product,
  type QueueOverview,
  type Reservation,
  type ReservationStatus,
  type SystemHealth,
  type TokenPair,
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "Cannot reach the gateway");
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response));
  }
  return (await response.json()) as T;
}

async function errorDetail(response: Response): Promise<string> {
  if (response.status === 429) {
    const retryAfter = response.headers.get("Retry-After");
    return retryAfter
      ? `Too many requests — try again in ${retryAfter}s`
      : "Too many requests — try again shortly";
  }
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const { detail } = body as { detail: unknown };
      if (typeof detail === "string") return detail;
    }
  } catch {
    // Non-JSON error body (e.g. an HTML page from a proxy).
  }
  return response.statusText || `Request failed (${response.status})`;
}

function authorized(token: string, signal?: AbortSignal): RequestInit {
  return { headers: { Authorization: `Bearer ${token}` }, signal };
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function login(email: string, password: string): Promise<TokenPair> {
  // OAuth2 password flow: form-encoded, and the email goes in `username`.
  return request<TokenPair>("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password }),
  });
}

export function refreshTokens(refreshToken: string): Promise<TokenPair> {
  return request<TokenPair>("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

// ---------- Orders ----------

interface OrderItemDto {
  id: string;
  product_id: string;
  qty: number;
  unit_price: string;
}

interface OrderDto {
  id: string;
  user_id: string;
  status: string;
  total_amount: string;
  created_at: string;
  updated_at: string;
  items: OrderItemDto[];
}

function toOrderRecord(dto: OrderDto): OrderRecord {
  return {
    id: dto.id,
    userId: dto.user_id,
    status: isOrderStatus(dto.status) ? dto.status : "pending",
    // Decimal arrives as a string; display totals tolerate float rounding.
    totalAmount: Number(dto.total_amount),
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
    items: dto.items.map((item) => ({
      id: item.id,
      productId: item.product_id,
      qty: item.qty,
      unitPrice: Number(item.unit_price),
    })),
  };
}

export function toLiveOrder(record: OrderRecord): Order {
  return {
    id: record.id,
    userId: record.userId,
    status: record.status,
    totalAmount: record.totalAmount,
    createdAt: record.createdAt,
    updatedAt: record.updatedAt,
    itemCount: record.items.length,
  };
}

export interface OrderFilters {
  status?: OrderStatus | null;
  createdFrom?: string | null;
  createdTo?: string | null;
  cursor?: string | null;
  limit?: number;
}

export async function fetchOrders(
  token: string,
  filters: OrderFilters = {},
  signal?: AbortSignal,
): Promise<Page<OrderRecord>> {
  const body = await request<{ items: OrderDto[]; next_cursor: string | null }>(
    `/api/v1/orders${query({
      status: filters.status,
      created_from: filters.createdFrom,
      created_to: filters.createdTo,
      cursor: filters.cursor,
      limit: filters.limit ?? 50,
    })}`,
    authorized(token, signal),
  );
  return { items: body.items.map(toOrderRecord), nextCursor: body.next_cursor };
}

export async function fetchRecentOrders(token: string, limit = 100): Promise<Order[]> {
  const page = await fetchOrders(token, { limit });
  return page.items.map(toLiveOrder);
}

export async function fetchOrder(
  token: string,
  orderId: string,
  signal?: AbortSignal,
): Promise<OrderRecord> {
  return toOrderRecord(
    await request<OrderDto>(`/api/v1/orders/${orderId}`, authorized(token, signal)),
  );
}

interface OrderEventDto {
  id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
  published_at: string | null;
  trace_id: string | null;
}

export async function fetchOrderEvents(
  token: string,
  orderId: string,
  signal?: AbortSignal,
): Promise<OrderEvent[]> {
  const body = await request<OrderEventDto[]>(
    `/api/v1/orders/${orderId}/events`,
    authorized(token, signal),
  );
  return body.map((dto) => ({
    id: dto.id,
    eventType: dto.event_type,
    payload: dto.payload,
    createdAt: dto.created_at,
    publishedAt: dto.published_at,
    traceId: dto.trace_id,
  }));
}

interface OrderSummaryDto {
  counts: Record<string, number>;
  total: number;
  outbox: { unpublished: number; oldest_unpublished_at: string | null };
  overdue: { status: string; count: number; after_minutes: number }[];
  reconciler_enabled: boolean;
  reconcile_interval_seconds: number;
  generated_at: string;
}

function countsFor<T extends string>(
  statuses: readonly T[],
  counts: Record<string, number>,
): Record<T, number> {
  return Object.fromEntries(statuses.map((status) => [status, counts[status] ?? 0])) as Record<
    T,
    number
  >;
}

export async function fetchOrderSummary(
  token: string,
  signal?: AbortSignal,
): Promise<OrderSummary> {
  const dto = await request<OrderSummaryDto>("/api/v1/orders/summary", authorized(token, signal));
  return {
    counts: countsFor(ORDER_STATUSES, dto.counts),
    total: dto.total,
    outbox: {
      unpublished: dto.outbox.unpublished,
      oldestUnpublishedAt: dto.outbox.oldest_unpublished_at,
    },
    overdue: dto.overdue.flatMap((item) =>
      isOrderStatus(item.status)
        ? [{ status: item.status, count: item.count, afterMinutes: item.after_minutes }]
        : [],
    ),
    reconcilerEnabled: dto.reconciler_enabled,
    reconcileIntervalSeconds: dto.reconcile_interval_seconds,
    generatedAt: dto.generated_at,
  };
}

export function createOrder(
  token: string,
  items: { productId: string; qty: number }[],
): Promise<OrderRecord> {
  return request<OrderDto>("/api/v1/orders", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      idempotency_key: crypto.randomUUID(),
      items: items.map((item) => ({ product_id: item.productId, qty: item.qty })),
    }),
  }).then(toOrderRecord);
}

// ---------- Payments ----------

interface PaymentDto {
  payment_id: string;
  order_id: string;
  status: string;
  amount: string;
  idempotency_key: string;
  created_at: string;
  ledger_entries: { id: string; direction: string; amount: string; created_at: string }[];
}

function toPayment(dto: PaymentDto): Payment {
  return {
    paymentId: dto.payment_id,
    orderId: dto.order_id,
    status: isPaymentStatus(dto.status) ? dto.status : "pending",
    amount: Number(dto.amount),
    idempotencyKey: dto.idempotency_key,
    createdAt: dto.created_at,
    ledger: dto.ledger_entries.map(
      (entry): LedgerEntry => ({
        id: entry.id,
        direction: entry.direction === "credit" ? "credit" : "debit",
        amount: Number(entry.amount),
        createdAt: entry.created_at,
      }),
    ),
  };
}

export async function fetchPayments(
  token: string,
  filters: { status?: PaymentStatus | null; cursor?: string | null; limit?: number } = {},
  signal?: AbortSignal,
): Promise<Page<Payment>> {
  const body = await request<{ items: PaymentDto[]; next_cursor: string | null }>(
    `/api/v1/payments${query({
      status: filters.status,
      cursor: filters.cursor,
      limit: filters.limit ?? 50,
    })}`,
    authorized(token, signal),
  );
  return { items: body.items.map(toPayment), nextCursor: body.next_cursor };
}

/** Null when no charge was ever attempted for the order. */
export async function fetchPaymentForOrder(
  token: string,
  orderId: string,
  signal?: AbortSignal,
): Promise<Payment | null> {
  try {
    return toPayment(
      await request<PaymentDto>(`/api/v1/payments/${orderId}`, authorized(token, signal)),
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

interface PaymentSummaryDto {
  counts: Record<string, number>;
  total: number;
  captured_amount: string;
  refunded_amount: string;
  net_amount: string;
  generated_at: string;
}

export async function fetchPaymentSummary(
  token: string,
  signal?: AbortSignal,
): Promise<PaymentSummary> {
  const dto = await request<PaymentSummaryDto>(
    "/api/v1/payments/summary",
    authorized(token, signal),
  );
  return {
    counts: countsFor(PAYMENT_STATUSES, dto.counts),
    total: dto.total,
    captured: Number(dto.captured_amount),
    refunded: Number(dto.refunded_amount),
    net: Number(dto.net_amount),
    generatedAt: dto.generated_at,
  };
}

// ---------- Inventory ----------

interface ProductDto {
  id: string;
  name: string;
  price: string;
  stock_qty: number;
  reserved_qty: number;
  committed_qty: number;
}

export async function fetchProducts(token: string, signal?: AbortSignal): Promise<Product[]> {
  const body = await request<{ items: ProductDto[] }>(
    "/api/v1/products",
    authorized(token, signal),
  );
  return body.items.map((dto) => ({
    id: dto.id,
    name: dto.name,
    price: Number(dto.price),
    available: dto.stock_qty,
    reserved: dto.reserved_qty,
    committed: dto.committed_qty,
  }));
}

interface ReservationDto {
  id: string;
  order_id: string;
  product_id: string;
  product_name: string;
  qty: number;
  status: string;
  expires_at: string;
  created_at: string;
}

export async function fetchReservations(
  token: string,
  filters: { orderId?: string | null; status?: ReservationStatus | null; limit?: number } = {},
  signal?: AbortSignal,
): Promise<Reservation[]> {
  const body = await request<{ items: ReservationDto[] }>(
    `/api/v1/reservations${query({
      order_id: filters.orderId,
      status: filters.status,
      limit: filters.limit ?? 50,
    })}`,
    authorized(token, signal),
  );
  return body.items.map((dto) => ({
    id: dto.id,
    orderId: dto.order_id,
    productId: dto.product_id,
    productName: dto.product_name,
    qty: dto.qty,
    status: isReservationStatus(dto.status) ? dto.status : "held",
    expiresAt: dto.expires_at,
    createdAt: dto.created_at,
  }));
}

// ---------- Operations (served by the gateway itself) ----------

interface SystemHealthDto {
  components: {
    name: string;
    kind: "service" | "infrastructure";
    status: HealthStatus;
    detail: string | null;
    latency_ms: number | null;
  }[];
  checked_at: string;
}

export async function fetchSystemHealth(
  token: string,
  signal?: AbortSignal,
): Promise<SystemHealth> {
  const dto = await request<SystemHealthDto>("/api/v1/ops/health", authorized(token, signal));
  return {
    components: dto.components.map((component) => ({
      name: component.name,
      kind: component.kind,
      status: component.status,
      detail: component.detail,
      latencyMs: component.latency_ms,
    })),
    checkedAt: dto.checked_at,
  };
}

interface QueueOverviewDto {
  queues: {
    name: string;
    ready: number;
    unacknowledged: number;
    consumers: number;
    retrying: number;
    dead_lettered: number;
    publish_rate: number;
    deliver_rate: number;
  }[];
  checked_at: string;
}

export async function fetchQueues(token: string, signal?: AbortSignal): Promise<QueueOverview> {
  const dto = await request<QueueOverviewDto>("/api/v1/ops/queues", authorized(token, signal));
  return {
    queues: dto.queues.map((queue) => ({
      name: queue.name,
      ready: queue.ready,
      unacknowledged: queue.unacknowledged,
      consumers: queue.consumers,
      retrying: queue.retrying,
      deadLettered: queue.dead_lettered,
      publishRate: queue.publish_rate,
      deliverRate: queue.deliver_rate,
    })),
    checkedAt: dto.checked_at,
  };
}

interface DeadLetterPageDto {
  queue: string;
  total: number;
  messages: {
    routing_key: string | null;
    payload: Record<string, unknown> | string;
    order_id: string | null;
    retry_count: number | null;
    last_error: string | null;
    dead_lettered_at: string | null;
    message_id: string | null;
  }[];
}

export async function fetchDeadLetters(
  token: string,
  queue: string,
  limit = 20,
  signal?: AbortSignal,
): Promise<DeadLetterPage> {
  const dto = await request<DeadLetterPageDto>(
    `/api/v1/ops/dead-letters/${encodeURIComponent(queue)}${query({ limit })}`,
    authorized(token, signal),
  );
  return {
    queue: dto.queue,
    total: dto.total,
    messages: dto.messages.map((message) => ({
      routingKey: message.routing_key,
      payload: message.payload,
      orderId: message.order_id,
      retryCount: message.retry_count,
      lastError: message.last_error,
      deadLetteredAt: message.dead_lettered_at,
      messageId: message.message_id,
    })),
  };
}

export async function replayDeadLetters(
  token: string,
  queue: string,
  limit: number | null,
): Promise<number> {
  const body = await request<{ replayed: number }>(
    `/api/v1/ops/dead-letters/${encodeURIComponent(queue)}/replay`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ limit }),
    },
  );
  return body.replayed;
}
