import type { DashboardMetrics } from "../dashboard/state";
import { formatMoney } from "../lib/format";
import { ORDER_STATUSES } from "../types";

export function MetricCards({ metrics }: { metrics: DashboardMetrics }) {
  const total = ORDER_STATUSES.reduce((sum, status) => sum + metrics.byStatus[status], 0);
  return (
    <section className="metrics" aria-label="Order metrics">
      <div className="metric-grid">
        <Metric label="In flight" value={metrics.inFlight.toString()} hint="pending · reserved · paid" />
        <Metric label="Fulfilled" value={metrics.byStatus.fulfilled.toString()} tone="success" />
        <Metric label="Cancelled" value={metrics.byStatus.cancelled.toString()} tone="danger" />
        <Metric label="Captured revenue" value={formatMoney(metrics.revenue)} hint="paid + fulfilled" />
        <Metric
          label="Success rate"
          value={metrics.successRate === null ? "—" : `${Math.round(metrics.successRate * 100)}%`}
          hint="fulfilled ÷ finished"
        />
      </div>

      <div className="pipeline" role="img" aria-label="Orders by status">
        {total === 0 ? (
          <div className="pipeline__empty">No orders yet</div>
        ) : (
          ORDER_STATUSES.filter((status) => metrics.byStatus[status] > 0).map((status) => (
            <div
              key={status}
              className={`pipeline__segment pipeline__segment--${status}`}
              style={{ flexGrow: metrics.byStatus[status] }}
              title={`${status}: ${metrics.byStatus[status]}`}
            >
              <span>
                {status} {metrics.byStatus[status]}
              </span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

interface MetricProps {
  label: string;
  value: string;
  hint?: string;
  tone?: "success" | "danger";
}

function Metric({ label, value, hint, tone }: MetricProps) {
  return (
    <div className={`metric${tone ? ` metric--${tone}` : ""}`}>
      <div className="metric__label">{label}</div>
      <div className="metric__value">{value}</div>
      {hint && <div className="metric__hint">{hint}</div>}
    </div>
  );
}
