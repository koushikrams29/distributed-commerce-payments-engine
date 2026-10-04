import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import { useLiveRefresh } from "../app/LiveData";
import { useSessionContext } from "../app/session";
import { useResource } from "../app/useResource";
import { PaymentBadge } from "../components/StatusBadge";
import { CopyId } from "../components/ui/CopyId";
import { Icon } from "../components/ui/Icon";
import { PageHeader, Panel, Stat } from "../components/ui/Panel";
import { EmptyState, ErrorState, SkeletonRows, StaleNotice } from "../components/ui/States";
import { TimeAgo } from "../components/ui/Time";
import { fetchPaymentSummary, fetchPayments } from "../lib/api";
import { formatCount, formatDateTime, formatMoney, formatPercent, titleCase } from "../lib/format";
import { orderPath, useSearchParams } from "../lib/router";
import { PAYMENT_STATUSES, isPaymentStatus, type Payment, type PaymentStatus } from "../types";

const PAGE_SIZE = 50;

export function PaymentsPage() {
  const { api } = useSessionContext();
  const [params, setParams] = useSearchParams();
  const statusParam = params.get("status");
  const status: PaymentStatus | null = isPaymentStatus(statusParam) ? statusParam : null;
  const [expanded, setExpanded] = useState<string | null>(null);
  const [extra, setExtra] = useState<{ items: Payment[]; nextCursor: string | null } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);

  const summary = useResource(fetchPaymentSummary, [], { pollMs: 30_000 });
  const first = useResource(
    (token, signal) => fetchPayments(token, { status, limit: PAGE_SIZE }, signal),
    [status],
  );

  useLiveRefresh(
    (event) => event.type.startsWith("payment."),
    () => {
      summary.reload();
      if (!extra) first.reload();
    },
    2000,
  );

  useEffect(() => {
    setExtra(null);
    setMoreError(null);
  }, [status, first.updatedAt]);

  const rows = useMemo(() => {
    if (!first.data) return [];
    const seen = new Set(first.data.items.map((payment) => payment.paymentId));
    return [...first.data.items, ...(extra?.items ?? []).filter((payment) => !seen.has(payment.paymentId))];
  }, [first.data, extra]);
  const nextCursor = extra ? extra.nextCursor : (first.data?.nextCursor ?? null);

  const loadMore = useCallback(async () => {
    if (!nextCursor) return;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await api.withToken((token) =>
        fetchPayments(token, { status, cursor: nextCursor, limit: PAGE_SIZE }),
      );
      setExtra((current) => ({ items: [...(current?.items ?? []), ...page.items], nextCursor: page.nextCursor }));
    } catch (error) {
      setMoreError(error instanceof Error ? error.message : "Couldn't load more payments");
    } finally {
      setLoadingMore(false);
    }
  }, [api, nextCursor, status]);

  const totals = summary.data;
  const attempted = totals ? totals.counts.succeeded + totals.counts.failed + totals.counts.refunded : 0;

  return (
    <div className="page">
      <PageHeader
        title="Payments"
        description={
          <>
            Charges and the double-entry ledger behind them. Each order is charged at most once: its
            idempotency key is <span className="mono nowrap">order-&lt;order id&gt;</span>.
          </>
        }
      />

      <div className="stats">
        <Stat label="Captured" value={totals ? formatMoney(totals.captured) : "—"} hint="Ledger debits" />
        <Stat
          label="Refunded"
          value={totals ? formatMoney(totals.refunded) : "—"}
          hint={totals ? `${formatCount(totals.counts.refunded)} refunds` : "Ledger credits"}
          tone={totals && totals.refunded > 0 ? "warning" : undefined}
        />
        <Stat label="Net" value={totals ? formatMoney(totals.net) : "—"} hint="Captured − refunded" />
        <Stat
          label="Decline rate"
          value={totals ? formatPercent(attempted ? totals.counts.failed / attempted : null) : "—"}
          hint={totals ? `${formatCount(totals.counts.failed)} of ${formatCount(attempted)} charges` : undefined}
          tone={totals && attempted && totals.counts.failed / attempted > 0.2 ? "warning" : undefined}
        />
      </div>
      {summary.error && !summary.data && (
        <div className="notice notice--warning" role="status">
          Totals unavailable: {summary.error}.
          <button className="link-button" type="button" onClick={summary.reload}>
            Retry
          </button>
        </div>
      )}

      <div className="tabs" role="tablist" aria-label="Filter by status">
        {[null, ...PAYMENT_STATUSES].map((value) => {
          const selected = value === status;
          const count = value === null ? totals?.total : totals?.counts[value];
          return (
            <button
              key={value ?? "all"}
              type="button"
              role="tab"
              aria-selected={selected}
              className={selected ? "tab tab--active" : "tab"}
              onClick={() => setParams({ status: value })}
            >
              {value === null ? "All" : titleCase(value)}
              {count !== undefined && <span className="tab__count">{formatCount(count)}</span>}
            </button>
          );
        })}
      </div>

      <Panel
        title="Charges"
        meta={first.data ? `${formatCount(rows.length)} shown${nextCursor ? " · more available" : ""}` : undefined}
        actions={
          <button
            type="button"
            className="icon-button"
            onClick={first.reload}
            aria-label="Refresh payments"
            title="Refresh"
          >
            <Icon name="refresh" />
          </button>
        }
        id="charges"
      >
        {first.error && first.data && (
          <StaleNotice error={first.error} updatedAt={first.updatedAt} onRetry={first.reload} />
        )}
        {first.data === undefined ? (
          first.loading ? (
            <SkeletonRows rows={8} columns={5} />
          ) : (
            <ErrorState message={first.error ?? "Unknown error"} onRetry={first.reload} />
          )
        ) : rows.length === 0 ? (
          <EmptyState
            title={status ? `No ${status} charges` : "No charges yet"}
            detail="A charge is made once an order's stock is reserved."
          />
        ) : (
          <div className="table-scroll">
            <table className="table table--responsive">
              <thead>
                <tr>
                  <th scope="col">Payment</th>
                  <th scope="col">Order</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num">
                    Amount
                  </th>
                  <th scope="col">Idempotency key</th>
                  <th scope="col">Created</th>
                  <th scope="col" className="num">
                    Ledger
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((payment) => {
                  const open = expanded === payment.paymentId;
                  return (
                    <Fragment key={payment.paymentId}>
                      <tr>
                        <td data-label="Payment">
                          <CopyId id={payment.paymentId} label="payment ID" />
                        </td>
                        <td data-label="Order">
                          <CopyId id={payment.orderId} to={orderPath(payment.orderId)} label="order ID" />
                        </td>
                        <td data-label="Status">
                          <PaymentBadge status={payment.status} />
                        </td>
                        <td data-label="Amount" className="num">
                          {formatMoney(payment.amount)}
                        </td>
                        <td data-label="Key" className="mono muted small" title={payment.idempotencyKey}>
                          {payment.idempotencyKey.length > 20
                            ? `${payment.idempotencyKey.slice(0, 20)}…`
                            : payment.idempotencyKey}
                        </td>
                        <td data-label="Created" className="muted">
                          <TimeAgo iso={payment.createdAt} />
                        </td>
                        <td data-label="Ledger" className="num">
                          <button
                            type="button"
                            className="link-button"
                            onClick={() => setExpanded(open ? null : payment.paymentId)}
                            aria-expanded={open}
                          >
                            {payment.ledger.length} {payment.ledger.length === 1 ? "entry" : "entries"}
                          </button>
                        </td>
                      </tr>
                      {open && (
                        <tr className="payload-row">
                          <td colSpan={7}>
                            {payment.ledger.length === 0 ? (
                              <p className="muted small">
                                No ledger entries: declined charges move no money.
                              </p>
                            ) : (
                              <table className="table table--compact table--nested">
                                <thead>
                                  <tr>
                                    <th scope="col">Direction</th>
                                    <th scope="col" className="num">
                                      Amount
                                    </th>
                                    <th scope="col">Recorded</th>
                                    <th scope="col">Entry</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {payment.ledger.map((entry) => (
                                    <tr key={entry.id}>
                                      <td>{entry.direction === "debit" ? "Debit — captured" : "Credit — refunded"}</td>
                                      <td className={entry.direction === "credit" ? "num text-warning" : "num"}>
                                        {entry.direction === "credit" ? "−" : ""}
                                        {formatMoney(entry.amount)}
                                      </td>
                                      <td className="muted">{formatDateTime(entry.createdAt)}</td>
                                      <td>
                                        <CopyId id={entry.id} label="ledger entry ID" />
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {first.data && (nextCursor || moreError) && (
          <div className="panel__footer">
            {moreError && (
              <span className="form-error" role="alert">
                {moreError}
              </span>
            )}
            {nextCursor && (
              <button className="button button--secondary" type="button" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? "Loading…" : `Load ${PAGE_SIZE} more`}
              </button>
            )}
          </div>
        )}
      </Panel>
    </div>
  );
}
