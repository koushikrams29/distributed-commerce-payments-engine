import { formatMoney, formatTime, shortId } from "../lib/format";
import type { Order } from "../types";
import { StatusBadge } from "./StatusBadge";

interface Props {
  orders: Order[];
  loading: boolean;
}

export function OrdersTable({ orders, loading }: Props) {
  return (
    <section className="panel panel--orders" aria-labelledby="orders-heading">
      <header className="panel__header">
        <h2 id="orders-heading">Orders</h2>
        <span className="panel__meta">by latest activity</span>
      </header>
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Order</th>
              <th scope="col">Customer</th>
              <th scope="col" className="num">Items</th>
              <th scope="col" className="num">Total</th>
              <th scope="col">Status</th>
              <th scope="col">Placed</th>
              <th scope="col">Updated</th>
            </tr>
          </thead>
          <tbody>
            {orders.length === 0 && (
              <tr>
                <td colSpan={7} className="table__empty">
                  {loading ? "Loading orders…" : "No orders yet — they will appear here live."}
                </td>
              </tr>
            )}
            {orders.map((order) => (
              // Keying on updatedAt remounts the row on change, replaying the
              // highlight animation so new activity catches the eye.
              <tr key={`${order.id}:${order.updatedAt}`} className="row-flash">
                <td className="mono" title={order.id}>{shortId(order.id)}</td>
                <td className="mono muted" title={order.userId}>{shortId(order.userId)}</td>
                <td className="num">{order.itemCount ?? "—"}</td>
                <td className="num">{formatMoney(order.totalAmount)}</td>
                <td><StatusBadge status={order.status} /></td>
                <td className="muted">{formatTime(order.createdAt)}</td>
                <td className="muted">{formatTime(order.updatedAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
