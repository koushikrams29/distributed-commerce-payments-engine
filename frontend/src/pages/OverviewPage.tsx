import { useMemo } from "react";

import { useLiveData, useLiveRefresh } from "../app/LiveData";
import { useResource } from "../app/useResource";
import { RecentEvents } from "../components/RecentEvents";
import { HealthBadge, StatusBadge } from "../components/StatusBadge";
import { CopyId } from "../components/ui/CopyId";
import { Icon } from "../components/ui/Icon";
import { PageHeader, Panel, Stat } from "../components/ui/Panel";
import { EmptyState, Loadable, SkeletonRows } from "../components/ui/States";
import { TimeAgo, useNow } from "../components/ui/Time";
import { sortByActivity } from "../dashboard/state";
import {
  fetchOrderSummary,
  fetchPaymentSummary,
  fetchQueues,
  fetchSystemHealth,
} from "../lib/api";
import { formatCount, formatMoney, formatPercent, formatTime } from "../lib/format";
import { assessSystem, type Verdict } from "../lib/health";
import { Link, orderPath } from "../lib/router";
import type { OrderStatus, OrderSummary } from "../types";

const VERDICT_TONE: Record<Verdict, string> = {
  healthy: "success",
  attention: "warning",
  degraded: "danger",
  unknown: "neutral",
};

const PIPELINE: { status: OrderStatus; label: string; hint: string }[] = [
  { status: "pending", label: "Pending", hint: "awaiting stock" },
  { status: "reserved", label: "Reserved", hint: "awaiting payment" },
  { status: "paid", label: "Paid", hint: "awaiting commit" },
  { status: "fulfilled", label: "Fulfilled", hint: "complete" },
];

function SagaPipeline({ summary }: { summary: OrderSummary }) {
  const overdue = Object.fromEntries(summary.overdue.map((item) => [item.status, item.count]));
  return (
    <div className="pipeline-flow">
      <ol className="pipeline-flow__stages">
        {PIPELINE.map((stage) => (
          <li key={stage.status} className={`stage stage--${stage.status}`}>
            <Link className="stage__link" to={`/orders?status=${stage.status}`}>
              <span className="stage__count">{formatCount(summary.counts[stage.status])}</span>
              <span className="stage__label">{stage.label}</span>
              <span className="stage__hint">{stage.hint}</span>
              {(overdue[stage.status] ?? 0) > 0 && (
                <span className="tag tag--warning">{overdue[stage.status]} overdue</span>
              )}
            </Link>
          </li>
        ))}
      </ol>
      <Link className="stage stage--cancelled stage__link stage--branch" to="/orders?status=cancelled">
        <span className="stage__count">{formatCount(summary.counts.cancelled)}</span>
        <span className="stage__label">Cancelled</span>
        <span className="stage__hint">compensated: stock released, late charges refunded</span>
      </Link>
    </div>
  );
}

export function OverviewPage() {
  const { state, connection } = useLiveData();
  const now = useNow();
  const health = useResource(fetchSystemHealth, [], { pollMs: 15_000 });
  const queues = useResource(fetchQueues, [], { pollMs: 15_000 });
  const orders = useResource(fetchOrderSummary, [], { pollMs: 30_000 });
  const payments = useResource(fetchPaymentSummary, [], { pollMs: 60_000 });

  useLiveRefresh((event) => event.type === "order.status_changed", orders.reload, 2000);
  useLiveRefresh((event) => event.type.startsWith("payment."), payments.reload, 3000);

  const assessment = assessSystem({
    health: health.data,
    healthError: health.error,
    queues: queues.data,
    queuesError: queues.error,
    orders: orders.data,
    connection,
    now,
  });

  const recentOrders = useMemo(
    () => sortByActivity(Object.values(state.orders)).slice(0, 8),
    [state.orders],
  );
  const deadLetters = queues.data?.queues.reduce((sum, queue) => sum + queue.deadLettered, 0);
  const counts = orders.data?.counts;
  const finished = counts ? counts.fulfilled + counts.cancelled : 0;

  return (
    <div className="page">
      <PageHeader
        title="Overview"
        description="Health of the order pipeline and the services behind it, right now."
      />

      <section
        className={`verdict verdict--${VERDICT_TONE[assessment.verdict]}`}
        aria-labelledby="verdict-heading"
      >
        <div className="verdict__head">
          <span className="verdict__dot" aria-hidden="true" />
          <h2 id="verdict-heading" className="verdict__headline">
            {assessment.headline}
          </h2>
          <span className="verdict__checked">
            {health.data && <>Checked {formatTime(health.data.checkedAt)}</>}
            <button
              type="button"
              className="icon-button icon-button--small"
              onClick={() => {
                health.reload();
                queues.reload();
                orders.reload();
              }}
              aria-label="Check again"
              title="Check again"
            >
              <Icon name="refresh" size={14} />
            </button>
          </span>
        </div>
        {assessment.issues.length > 0 && (
          <ul className="verdict__issues">
            {assessment.issues.map((issue) => (
              <li key={issue.text} className={`verdict__issue verdict__issue--${issue.severity}`}>
                <Link to={issue.to}>{issue.text}</Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="stats">
        <Stat
          label="Orders in flight"
          value={counts ? formatCount(counts.pending + counts.reserved + counts.paid) : "—"}
          hint={counts ? `${formatCount(orders.data?.total ?? 0)} orders in total` : undefined}
        />
        <Stat
          label="Fulfilment rate"
          value={counts ? formatPercent(finished ? counts.fulfilled / finished : null) : "—"}
          hint={counts ? `${formatCount(counts.cancelled)} cancelled` : undefined}
          tone={counts && finished && counts.cancelled / finished > 0.2 ? "warning" : undefined}
        />
        <Stat
          label="Net captured"
          value={payments.data ? formatMoney(payments.data.net) : "—"}
          hint={payments.data ? `${formatMoney(payments.data.refunded)} refunded` : undefined}
        />
        <Stat
          label="Dead letters"
          value={deadLetters === undefined ? "—" : formatCount(deadLetters)}
          hint={<Link to="/failures">Failure operations</Link>}
          tone={deadLetters ? "warning" : undefined}
        />
      </div>

      <div className="grid grid--overview">
        <Panel
          title="Saga pipeline"
          meta="Orders by status, all time"
          id="pipeline"
          className="grid__wide"
        >
          <div className="panel__body">
            <Loadable resource={orders} skeleton={<SkeletonRows rows={2} />}>
              {(summary) => <SagaPipeline summary={summary} />}
            </Loadable>
          </div>
        </Panel>

        <Panel
          title="Services"
          meta={health.refreshing ? "Checking…" : "Polled every 15 s"}
          id="service-health"
          actions={
            <Link className="panel__link" to="/services">
              Details
            </Link>
          }
        >
          <Loadable resource={health} skeleton={<SkeletonRows rows={7} columns={2} />}>
            {(data) => (
              <ul className="health-list">
                {data.components.map((component) => (
                  <li key={component.name} className="health-list__item">
                    <span className={`dot dot--${component.status}`} aria-hidden="true" />
                    <span className="health-list__name mono">{component.name}</span>
                    <span className="health-list__latency">
                      {component.latencyMs !== null ? `${Math.round(component.latencyMs)} ms` : ""}
                    </span>
                    {component.status !== "up" && <HealthBadge status={component.status} />}
                  </li>
                ))}
              </ul>
            )}
          </Loadable>
        </Panel>

        <Panel
          title="Recent orders"
          meta="Updates live"
          id="recent-orders"
          actions={
            <Link className="panel__link" to="/orders">
              All orders
            </Link>
          }
        >
          {!state.snapshotLoaded && recentOrders.length === 0 ? (
            <SkeletonRows rows={6} columns={3} />
          ) : recentOrders.length === 0 ? (
            <EmptyState
              compact
              title="No orders yet"
              detail="Orders appear here the moment they are placed."
            />
          ) : (
            <div className="table-scroll">
              <table className="table table--compact table--dense">
                <thead>
                  <tr>
                    <th scope="col">Order</th>
                    <th scope="col">Status</th>
                    <th scope="col" className="num">
                      Total
                    </th>
                    <th scope="col" className="num">
                      Updated
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {recentOrders.map((order) => (
                    <tr key={order.id}>
                      <td>
                        <CopyId id={order.id} to={orderPath(order.id)} label="order ID" />
                      </td>
                      <td>
                        <StatusBadge status={order.status} />
                      </td>
                      <td className="num">{formatMoney(order.totalAmount)}</td>
                      <td className="num muted">
                        <TimeAgo iso={order.updatedAt} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel
          title="Live activity"
          meta={`${formatCount(state.eventsReceived)} events this session`}
          id="live-activity"
          actions={
            <Link className="panel__link" to="/events">
              Event console
            </Link>
          }
        >
          <RecentEvents entries={state.feed.slice(0, 8)} connection={connection} />
        </Panel>
      </div>
    </div>
  );
}
