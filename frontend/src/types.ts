export const ORDER_STATUSES = [
  "pending",
  "reserved",
  "paid",
  "fulfilled",
  "cancelled",
] as const;

export type OrderStatus = (typeof ORDER_STATUSES)[number];

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

export interface Product {
  id: string;
  name: string;
  price: number;
  stockQty: number;
}

/** One message relayed by the gateway from the commerce.events exchange. */
export interface DashboardEvent {
  type: string;
  data: Record<string, unknown>;
  receivedAt: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export function isOrderStatus(value: unknown): value is OrderStatus {
  return (
    typeof value === "string" &&
    (ORDER_STATUSES as readonly string[]).includes(value)
  );
}
