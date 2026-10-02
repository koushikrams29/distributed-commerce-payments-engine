import type { OrderStatus } from "../types";

export function StatusBadge({ status }: { status: OrderStatus }) {
  return <span className={`badge badge--${status}`}>{status}</span>;
}
