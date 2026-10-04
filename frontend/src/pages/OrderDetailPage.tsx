import { useMemo } from "react";

import { useLiveData, useLiveRefresh } from "../app/LiveData";
import { traceUrl, useToolLinks } from "../app/toolLinks";
import { useResource } from "../app/useResource";
import { SagaTrack } from "../components/SagaTrack";
import { PaymentBadge, ReservationBadge, StatusBadge } from "../components/StatusBadge";
import { Timeline } from "../components/Timeline";
import { CopyId } from "../components/ui/CopyId";
import { Icon } from "../components/ui/Icon";
import { KeyValues, Panel } from "../components/ui/Panel";
import { EmptyState, ErrorState, Loadable, SkeletonRows } from "../components/ui/States";
import { TimeAgo, useNow } from "../components/ui/Time";
import {
  fetchOrder,
  fetchOrderEvents,
  fetchOrderSummary,
  fetchPaymentForOrder,
  fetchProducts,
  fetchReservations,
} from "../lib/api";
import { formatDateTime, formatDuration, formatMoney, shortId } from "../lib/format";
import { buildTimeline, traceIds } from "../lib/orderTimeline";
import { Link } from "../lib/router";
import { deriveSaga, explainOrder, overdueThresholds } from "../lib/saga";
import { isUuid, type DashboardEvent } from "../types";

export function OrderDetailPage({ orderId }: { orderId: string }) {
  if (!isUuid(orderId)) {
    return (
      <div className="page">
        <ErrorState
          title="That isn't an order ID"
          message={`“${orderId}” is not a UUID. Order IDs look like 3f2b9c1e-8d4a-4e2b-9a7c-1b2c3d4e5f60.`}
        />
        <p>
          <Link to="/orders">Back to orders</Link>
        </p>
      </div>
    );
  }
  return <OrderDetail orderId={orderId.toLowerCase()} />;
}

function OrderDetail({ orderId }: { orderId: string }) {
  const { state } = useLiveData();
  const links = useToolLinks();
  const now = useNow();

  const order = useResource((token, signal) => fetchOrder(token, orderId, signal), [orderId]);
  const events = useResource((token, signal) => fetchOrderEvents(token, orderId, signal), [orderId]);
  const payment = useResource((token, signal) => fetchPaymentForOrder(token, orderId, signal), [orderId]);
  const reservations = useResource(
    (token, signal) => fetchReservations(token, { orderId, limit: 200 }, signal),
    [orderId],
  );
  const summary = useResource(fetchOrderSummary, []);
  const products = useResource(fetchProducts, []);

  const isThisOrder = (event: DashboardEvent) => event.data.order_id === orderId;
  useLiveRefresh(
    isThisOrder,
    () => {
      order.reload();
      events.reload();
      payment.reload();
      reservations.reload();
    },
    800,
  );

  const liveEvents = useMemo(
    () => state.feed.filter((entry) => entry.event.data.order_id === orderId).map((entry) => entry.event).reverse(),
    [state.feed, orderId],
  );

  if (order.data === undefined) {
    if (order.loading) {
      return (
        <div className="page">
          <SkeletonRows rows={3} />
          <SkeletonRows rows={8} columns={3} />
        </div>
      );
    }
    if (order.errorStatus === 404) {
      return (
        <div className="page">
          <EmptyState
            title="Order not found"
            detail={
              <>
                No order with ID <span className="mono">{orderId}</span>. It may belong to another
                environment.
              </>
            }
            action={
              <Link className="button button--secondary" to="/orders">
                Back to orders
              </Link>
            }
          />
        </div>
      );
    }
    return (
      <div className="page">
        <ErrorState title="Couldn't load this order" message={order.error ?? "Unknown error"} onRetry={order.reload} />
      </div>
    );
  }

  const record = order.data;
  const thresholds = summary.data ? overdueThresholds(summary.data.overdue) : {};
  const sagaInput = events.data
    ? {
        order: record,
        events: events.data,
        payment: payment.data ?? null,
        reservations: reservations.data ?? [],
        thresholds,
        now,
      }
    : null;
  const saga = sagaInput ? deriveSaga(sagaInput) : null;
  const explanation = sagaInput && saga ? explainOrder(sagaInput, saga, liveEvents) : null;
  const traces = events.data ? traceIds(events.data, liveEvents) : [];
  const primaryTrace = traces[0] ? traceUrl(links, traces[0]) : null;
  const productNames = new Map((products.data ?? []).map((product) => [product.id, product.name]));
  const supportingError = [events, payment, reservations].find((resource) => resource.error && resource.data === undefined);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="breadcrumb">
            <Link to="/orders">Orders</Link> / <span className="mono">{shortId(record.id)}</span>
          </div>
          <h1 className="page-header__title page-header__title--with-badge">
            <span>Order</span>
            <CopyId id={record.id} full label="order ID" />
            <StatusBadge status={record.status} />
          </h1>
        </div>
        <div className="page-header__actions">
          {primaryTrace && (
            <a className="button button--secondary" href={primaryTrace} target="_blank" rel="noreferrer">
              <Icon name="trace" /> Open trace
            </a>
          )}
          <Link className="button button--secondary" to={`/events?order=${record.id}`}>
            <Icon name="events" /> Live events
          </Link>
        </div>
      </div>

      {explanation && (
        <div className={`callout callout--${explanation.tone}`} role={explanation.tone === "danger" ? "alert" : "status"}>
          <div className="callout__title">{explanation.title}</div>
          <div className="callout__detail">{explanation.detail}</div>
        </div>
      )}
      {supportingError && (
        <div className="notice notice--warning" role="status">
          Part of this order's history couldn't be loaded: {supportingError.error}.
          <button className="link-button" type="button" onClick={supportingError.reload}>
            Retry
          </button>
        </div>
      )}

      <Panel
        title="Saga"
        meta={
          saga
            ? saga.finishedAt
              ? `Finished in ${formatDuration(saga.durationMs)}`
              : `Running for ${formatDuration(saga.durationMs)}`
            : undefined
        }
        id="saga"
      >
        <div className="panel__body">
          {saga ? <SagaTrack steps={saga.steps} /> : <SkeletonRows rows={2} columns={5} />}
        </div>
      </Panel>

      <div className="grid grid--detail">
        <Panel
          title="Timeline"
          meta="Every service's record of this order"
          id="timeline"
          className="grid__main"
        >
          <Loadable resource={events} skeleton={<SkeletonRows rows={8} columns={2} />}>
            {(outbox) => (
              <Timeline
                entries={buildTimeline({
                  order: record,
                  events: outbox,
                  payment: payment.data ?? null,
                  reservations: reservations.data ?? [],
                  liveEvents,
                })}
              />
            )}
          </Loadable>
        </Panel>

        <div className="grid__side">
          <Panel title="Summary" id="summary">
            <KeyValues
              items={[
                ["Customer", <CopyId key="customer" id={record.userId} label="customer ID" />],
                ["Total", formatMoney(record.totalAmount)],
                ["Placed", formatDateTime(record.createdAt)],
                ["Last change", <TimeAgo key="updated" iso={record.updatedAt} />],
                ["Duration", saga ? formatDuration(saga.durationMs) : "—"],
                [
                  "Traces",
                  traces.length === 0 ? (
                    <span className="muted">none recorded</span>
                  ) : (
                    <span className="trace-list">
                      {traces.map((id) => {
                        const href = traceUrl(links, id);
                        return href ? (
                          <a key={id} className="tool-link mono" href={href} target="_blank" rel="noreferrer">
                            {id.slice(0, 12)}
                            <Icon name="external" size={12} />
                          </a>
                        ) : (
                          <span key={id} className="mono" title={id}>
                            {id.slice(0, 12)}
                          </span>
                        );
                      })}
                    </span>
                  ),
                ],
              ]}
            />
          </Panel>

          <Panel title="Items" meta={`${record.items.length} line${record.items.length === 1 ? "" : "s"}`} id="items">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th scope="col">Product</th>
                  <th scope="col" className="num">
                    Qty
                  </th>
                  <th scope="col" className="num">
                    Price
                  </th>
                </tr>
              </thead>
              <tbody>
                {record.items.map((item) => (
                  <tr key={item.id}>
                    <td>{productNames.get(item.productId) ?? <span className="mono">{shortId(item.productId)}</span>}</td>
                    <td className="num">{item.qty}</td>
                    <td className="num">{formatMoney(item.unitPrice * item.qty)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="Payment" id="payment">
            <Loadable
              resource={payment}
              skeleton={<SkeletonRows rows={3} />}
              isEmpty={(value) => value === null}
              empty={
                <EmptyState
                  compact
                  title="No charge"
                  detail={
                    record.status === "pending" || record.status === "cancelled"
                      ? "Payment is only attempted once stock is reserved."
                      : "The charge hasn't been recorded yet."
                  }
                />
              }
            >
              {(value) =>
                value && (
                  <>
                    <KeyValues
                      items={[
                        ["Status", <PaymentBadge key="status" status={value.status} />],
                        ["Amount", formatMoney(value.amount)],
                        ["Payment", <CopyId key="payment" id={value.paymentId} label="payment ID" />],
                        ["Idempotency key", <span key="key" className="mono wrap">{value.idempotencyKey}</span>],
                      ]}
                    />
                    {value.ledger.length > 0 && (
                      <table className="table table--compact">
                        <caption className="table__caption">Ledger</caption>
                        <thead>
                          <tr>
                            <th scope="col">Entry</th>
                            <th scope="col" className="num">
                              Amount
                            </th>
                            <th scope="col" className="num">
                              When
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {value.ledger.map((entry) => (
                            <tr key={entry.id}>
                              <td>{entry.direction === "debit" ? "Debit (capture)" : "Credit (refund)"}</td>
                              <td className={entry.direction === "credit" ? "num text-warning" : "num"}>
                                {entry.direction === "credit" ? "−" : ""}
                                {formatMoney(entry.amount)}
                              </td>
                              <td className="num muted">{formatDateTime(entry.createdAt)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </>
                )
              }
            </Loadable>
          </Panel>

          <Panel title="Stock reservations" id="reservations">
            <Loadable
              resource={reservations}
              skeleton={<SkeletonRows rows={2} />}
              isEmpty={(items) => items.length === 0}
              empty={
                <EmptyState
                  compact
                  title="No reservations"
                  detail={
                    record.status === "cancelled"
                      ? "Inventory never held stock for this order."
                      : "Inventory hasn't reserved stock yet."
                  }
                />
              }
            >
              {(items) => (
                <table className="table table--compact">
                  <thead>
                    <tr>
                      <th scope="col">Product</th>
                      <th scope="col" className="num">
                        Qty
                      </th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr key={item.id}>
                        <td>{item.productName}</td>
                        <td className="num">{item.qty}</td>
                        <td>
                          <ReservationBadge status={item.status} />
                          {item.status === "held" && (
                            <span className="muted small"> expires {formatDateTime(item.expiresAt)}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Loadable>
          </Panel>
        </div>
      </div>
    </div>
  );
}