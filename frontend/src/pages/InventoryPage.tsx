import { useMemo } from "react";

import { useLiveData, useLiveRefresh } from "../app/LiveData";
import { useResource } from "../app/useResource";
import { ReservationBadge } from "../components/StatusBadge";
import { CopyId } from "../components/ui/CopyId";
import { PageHeader, Panel } from "../components/ui/Panel";
import { EmptyState, Loadable, SkeletonRows } from "../components/ui/States";
import { TimeAgo, useNow } from "../components/ui/Time";
import { affectsStock } from "../dashboard/events";
import { fetchProducts, fetchReservations } from "../lib/api";
import { formatCount, formatDateTime, formatMoney, formatPreciseTime, titleCase } from "../lib/format";
import { Link, orderPath, useSearchParams } from "../lib/router";
import { RESERVATION_STATUSES, isReservationStatus, type Product, type ReservationStatus } from "../types";

const LOW_STOCK = 5;

function StockBar({ product }: { product: Product }) {
  const total = product.available + product.reserved + product.committed;
  if (total === 0) return <div className="stockbar stockbar--empty" aria-hidden="true" />;
  const width = (value: number) => `${(value / total) * 100}%`;
  return (
    <div
      className="stockbar"
      role="img"
      aria-label={`${product.available} available, ${product.reserved} reserved, ${product.committed} committed`}
    >
      <span className="stockbar__segment stockbar__segment--available" style={{ width: width(product.available) }} />
      <span className="stockbar__segment stockbar__segment--reserved" style={{ width: width(product.reserved) }} />
      <span className="stockbar__segment stockbar__segment--committed" style={{ width: width(product.committed) }} />
    </div>
  );
}

function StockFlow({ products, released }: { products: Product[]; released: number | null }) {
  const sum = (key: "available" | "reserved" | "committed") =>
    products.reduce((total, product) => total + product[key], 0);
  return (
    <div className="stock-flow" aria-label="How stock moves">
      <div className="stock-flow__node stock-flow__node--available">
        <span className="stock-flow__count">{formatCount(sum("available"))}</span>
        <span>Available</span>
      </div>
      <span className="stock-flow__arrow" aria-hidden="true">→</span>
      <div className="stock-flow__node stock-flow__node--reserved">
        <span className="stock-flow__count">{formatCount(sum("reserved"))}</span>
        <span>Reserved</span>
        <span className="stock-flow__hint">held for an order</span>
      </div>
      <span className="stock-flow__arrow" aria-hidden="true">→</span>
      <div className="stock-flow__node stock-flow__node--committed">
        <span className="stock-flow__count">{formatCount(sum("committed"))}</span>
        <span>Committed</span>
        <span className="stock-flow__hint">sold</span>
      </div>
      <div className="stock-flow__release">
        <span aria-hidden="true">↩</span> Reserved → Released returns units to Available
        {released !== null && <> · {formatCount(released)} of the last 100 reservations were released</>}
      </div>
    </div>
  );
}

export function InventoryPage() {
  const { state } = useLiveData();
  const now = useNow();
  const [params, setParams] = useSearchParams();
  const statusParam = params.get("status");
  const status: ReservationStatus | null = isReservationStatus(statusParam) ? statusParam : null;

  const products = useResource(fetchProducts, [], { pollMs: 30_000 });
  const reservations = useResource(
    (token, signal) => fetchReservations(token, { status, limit: 100 }, signal),
    [status],
  );
  useLiveRefresh(
    affectsStock,
    () => {
      products.reload();
      reservations.reload();
    },
    1500,
  );

  const rejected = useMemo(
    () => state.feed.filter((entry) => entry.event.type === "inventory.failed").slice(0, 20),
    [state.feed],
  );
  // Only meaningful over the unfiltered list.
  const released =
    status === null && reservations.data
      ? reservations.data.filter((item) => item.status === "released").length
      : null;

  return (
    <div className="page">
      <PageHeader
        title="Inventory"
        description="Where every unit is. Stock is deducted when an order reserves it, then either committed when the order is paid or released if the order is cancelled."
      />

      <Panel title="Stock flow" meta="All products" id="stock-flow">
        <div className="panel__body">
          <Loadable resource={products} skeleton={<SkeletonRows rows={2} />}>
            {(items) => <StockFlow products={items} released={released} />}
          </Loadable>
        </div>
      </Panel>

      <Panel
        title="Products"
        meta="Lowest availability first"
        id="products"
        actions={
          <span className="legend">
            <span className="legend__item legend__item--available">Available</span>
            <span className="legend__item legend__item--reserved">Reserved</span>
            <span className="legend__item legend__item--committed">Committed</span>
          </span>
        }
      >
        <Loadable
          resource={products}
          skeleton={<SkeletonRows rows={6} columns={5} />}
          isEmpty={(items) => items.length === 0}
          empty={<EmptyState title="No products" detail="The inventory service has no products yet." />}
        >
          {(items) => (
            <div className="table-scroll">
              <table className="table table--responsive">
                <thead>
                  <tr>
                    <th scope="col">Product</th>
                    <th scope="col" className="num">
                      Price
                    </th>
                    <th scope="col" className="num">
                      Available
                    </th>
                    <th scope="col" className="num">
                      Reserved
                    </th>
                    <th scope="col" className="num">
                      Committed
                    </th>
                    <th scope="col" className="col-bar">
                      Distribution
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {[...items]
                    .sort((a, b) => a.available - b.available || a.name.localeCompare(b.name))
                    .map((product) => (
                      <tr key={product.id}>
                        <td data-label="Product">
                          {product.name}
                          {product.available === 0 ? (
                            <span className="tag tag--danger">out of stock</span>
                          ) : product.available <= LOW_STOCK ? (
                            <span className="tag tag--warning">low</span>
                          ) : null}
                        </td>
                        <td data-label="Price" className="num">
                          {formatMoney(product.price)}
                        </td>
                        <td data-label="Available" className="num">
                          {formatCount(product.available)}
                        </td>
                        <td data-label="Reserved" className="num">
                          {formatCount(product.reserved)}
                        </td>
                        <td data-label="Committed" className="num">
                          {formatCount(product.committed)}
                        </td>
                        <td data-label="Distribution" className="col-bar">
                          <StockBar product={product} />
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </Loadable>
      </Panel>

      <div className="grid grid--two">
        <Panel
          title="Reservation activity"
          meta="Newest first"
          id="reservations"
          actions={
            <select
              className="select--small"
              aria-label="Filter reservations by status"
              value={status ?? ""}
              onChange={(event) => setParams({ status: event.target.value })}
            >
              <option value="">All statuses</option>
              {RESERVATION_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          }
        >
          <Loadable
            resource={reservations}
            skeleton={<SkeletonRows rows={6} columns={4} />}
            isEmpty={(items) => items.length === 0}
            empty={
              <EmptyState
                compact
                title={status ? `No ${status} reservations` : "No reservations yet"}
                detail="Reservations are made when an order is placed."
              />
            }
          >
            {(items) => (
              <div className="table-scroll">
                <table className="table table--responsive table--compact">
                  <thead>
                    <tr>
                      <th scope="col">Reserved</th>
                      <th scope="col">Order</th>
                      <th scope="col">Product</th>
                      <th scope="col" className="num">
                        Qty
                      </th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => {
                      const expired = item.status === "held" && Date.parse(item.expiresAt) < now;
                      return (
                        <tr key={item.id}>
                          <td data-label="Reserved" className="muted">
                            <TimeAgo iso={item.createdAt} />
                          </td>
                          <td data-label="Order">
                            <CopyId id={item.orderId} to={orderPath(item.orderId)} label="order ID" />
                          </td>
                          <td data-label="Product">{item.productName}</td>
                          <td data-label="Qty" className="num">
                            {item.qty}
                          </td>
                          <td data-label="Status">
                            <ReservationBadge status={item.status} />
                            {item.status === "held" && (
                              <span
                                className={expired ? "tag tag--warning" : "muted small"}
                                title={`Expires ${formatDateTime(item.expiresAt)}`}
                              >
                                {expired ? "past expiry" : ` until ${formatDateTime(item.expiresAt)}`}
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Loadable>
        </Panel>

        <Panel title="Rejected reservations" meta="Seen live in this session" id="rejected">
          {rejected.length === 0 ? (
            <EmptyState
              compact
              title="None seen"
              detail={
                <>
                  A rejected reservation cancels its order. Earlier rejections show up as{" "}
                  <Link to="/orders?status=cancelled">cancelled orders</Link>.
                </>
              }
            />
          ) : (
            <ul className="issue-list">
              {rejected.map(({ seq, event }) => {
                const orderId = typeof event.data.order_id === "string" ? event.data.order_id : null;
                const reason = typeof event.data.reason === "string" ? event.data.reason : "No reason given";
                return (
                  <li key={seq} className="issue-list__item">
                    <div className="issue-list__head">
                      {orderId ? (
                        <CopyId id={orderId} to={orderPath(orderId)} label="order ID" />
                      ) : (
                        <span className="muted">Unknown order</span>
                      )}
                      <time className="muted small" dateTime={event.receivedAt}>
                        {formatPreciseTime(event.receivedAt)}
                      </time>
                    </div>
                    <div className="issue-list__detail">{reason}</div>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
