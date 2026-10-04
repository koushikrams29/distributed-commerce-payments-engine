/**
 * Who publishes each event and whose queue it lands in. Mirrors the consumer
 * bindings in each service's app/events/consumers.py; the gateway additionally
 * receives every event for the live console.
 */

export const SERVICE_NAMES = [
  "order-service",
  "inventory-service",
  "payment-service",
  "notification-service",
  "recommendation-service",
] as const;

export type ServiceName = (typeof SERVICE_NAMES)[number];

export interface EventRoute {
  source: ServiceName | null;
  consumers: ServiceName[];
}

const EVENT_ROUTES = new Map<string, EventRoute>([
  ["order.created", { source: "order-service", consumers: ["inventory-service"] }],
  ["order.cancelled", { source: "order-service", consumers: ["inventory-service"] }],
  ["order.paid", { source: "order-service", consumers: ["inventory-service"] }],
  ["charge.requested", { source: "order-service", consumers: ["payment-service"] }],
  ["refund.requested", { source: "order-service", consumers: ["payment-service"] }],
  ["order.fulfilled", { source: "order-service", consumers: ["notification-service"] }],
  ["order.status_changed", { source: "order-service", consumers: [] }],
  ["inventory.reserved", { source: "inventory-service", consumers: ["order-service"] }],
  ["inventory.failed", { source: "inventory-service", consumers: ["order-service"] }],
  ["inventory.committed", { source: "inventory-service", consumers: ["order-service"] }],
  ["payment.succeeded", { source: "payment-service", consumers: ["order-service", "recommendation-service"] }],
  ["payment.failed", { source: "payment-service", consumers: ["order-service"] }],
  ["payment.refunded", { source: "payment-service", consumers: [] }],
]);

export const KNOWN_EVENT_TYPES = [...EVENT_ROUTES.keys()];

export function eventRoute(type: string): EventRoute {
  return EVENT_ROUTES.get(type) ?? { source: null, consumers: [] };
}

export interface WorkQueue {
  queue: string;
  service: ServiceName;
  routingKeys: string[];
}

/** Each service's durable queue and the routing keys bound to it. */
export const WORK_QUEUES: WorkQueue[] = SERVICE_NAMES.map((service) => ({
  queue: `${service.replace("-service", "")}.events`,
  service,
  routingKeys: KNOWN_EVENT_TYPES.filter((type) => eventRoute(type).consumers.includes(service)),
}));

export function publishedBy(service: ServiceName): string[] {
  return KNOWN_EVENT_TYPES.filter((type) => eventRoute(type).source === service);
}

export function serviceForQueue(queue: string): ServiceName | null {
  return WORK_QUEUES.find((item) => item.queue === queue)?.service ?? null;
}
