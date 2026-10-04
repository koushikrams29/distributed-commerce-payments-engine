import { useCallback, useEffect, useMemo, useState } from "react";

import { useLiveData } from "../app/LiveData";
import { useSessionContext } from "../app/session";
import { useResource } from "../app/useResource";
import { StatusBadge } from "../components/StatusBadge";
import { TestOrderDialog } from "../components/TestOrderDialog";
import { CopyId } from "../components/ui/CopyId";
import { Icon } from "../components/ui/Icon";
import { PageHeader, Panel } from "../components/ui/Panel";
import { EmptyState, ErrorState, SkeletonRows, StaleNotice } from "../components/ui/States";
import { TimeAgo, useNow } from "../components/ui/Time";
import { useToast } from "../components/ui/Toast";
import { fetchOrderSummary, fetchOrders } from "../lib/api";
import { formatCount, formatDateTime, formatDuration, formatMoney, shortId } from "../lib/format";
import {
  RANGES,
  createdWindow,
  isRangeKey,
  isSortKey,
  matchesQuery,
  newSince,
  orderAge,
  sortOrders,
  withLiveStatus,
  type RangeKey,
  type SortKey,
} from "../lib/orderList";
import { navigate, orderPath, useSearchParams } from "../lib/router";
import { overdueThresholds } from "../lib/saga";
import { ORDER_STATUSES, isOrderStatus, type OrderRecord, type OrderStatus } from "../types";

const PAGE_SIZE = 50;

/** `datetime-local` works in local wall time; the API wants an instant with an offset. */
function toInputValue(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function fromInputValue(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

const SORT_LABELS: Record<SortKey, string> = {
  created: "Placed",
  updated: "Updated",
  total: "Total",
  age: "Duration",
};

export function OrdersPage() {
  const { api } = useSessionContext();
  const { state } = useLiveData();
  const notify = useToast();
  const now = useNow();
  const [params, setParams] = useSearchParams();

  const status: OrderStatus | null = isOrderStatus(params.get("status")) ? (params.get("status") as OrderStatus) : null;
  const rangeParam = params.get("range");
  const range: RangeKey = isRangeKey(rangeParam) ? rangeParam : "all";
  const customFrom = params.get("from");
  const customTo = params.get("to");
  const query = params.get("q") ?? "";
  const sortParam = params.get("sort");
  const sort: SortKey = isSortKey(sortParam) ? sortParam : "created";
  const direction = params.get("dir") === "asc" ? "asc" : "desc";

  const [testOrderOpen, setTestOrderOpen] = useState(false);
  const [extra, setExtra] = useState<{ items: OrderRecord[]; nextCursor: string | null } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);

  const summary = useResource(fetchOrderSummary, [], { pollMs: 30_000 });
  const first = useResource(
    (token, signal) =>
      fetchOrders(
        token,
        {
          status,
          ...createdWindow(range, { from: customFrom, to: customTo }, Date.now()),
          limit: PAGE_SIZE,
        },
        signal,
      ),
    [status, range, customFrom, customTo],
  );

  useEffect(() => {
    setExtra(null);
    setMoreError(null);
  }, [status, range, customFrom, customTo, first.updatedAt]);

  const loaded = useMemo(() => {
    if (!first.data) return [];
    const seen = new Set(first.data.items.map((order) => order.id));
    const rest = (extra?.items ?? []).filter((order) => !seen.has(order.id));
    return [...first.data.items, ...rest];
  }, [first.data, extra]);
  const nextCursor = extra ? extra.nextCursor : (first.data?.nextCursor ?? null);

  const rows = useMemo(
    () =>
      sortOrders(
        withLiveStatus(loaded, state.orders).filter((order) => matchesQuery(order, query)),
        sort,
        direction,
        now,
      ),
    [loaded, state.orders, query, sort, direction, now],
  );

  const shownIds = useMemo(() => new Set(loaded.map((order) => order.id)), [loaded]);
  const unseen =
    first.updatedAt && range !== "custom"
      ? newSince(state.orders, shownIds, first.updatedAt, status)
      : 0;

  const thresholds = summary.data ? overdueThresholds(summary.data.overdue) : {};

  const loadMore = useCallback(async () => {
    if (!nextCursor) return;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await api.withToken((token) =>
        fetchOrders(token, {
          status,
          ...createdWindow(range, { from: customFrom, to: customTo }, Date.now()),
          cursor: nextCursor,
          limit: PAGE_SIZE,
        }),
      );
      setExtra((current) => ({
        items: [...(current?.items ?? []), ...page.items],
        nextCursor: page.nextCursor,
      }));
    } catch (error) {
      setMoreError(error instanceof Error ? error.message : "Couldn't load more orders");
    } finally {
      setLoadingMore(false);
    }
  }, [api, nextCursor, status, range, customFrom, customTo]);

  const toggleSort = (key: SortKey) => {
    if (key === sort) setParams({ dir: direction === "desc" ? "asc" : null });
    else setParams({ sort: key === "created" ? null : key, dir: null });
  };

  const sortHeader = (key: SortKey, className = "") => (
    <th
      scope="col"
      className={className}
      aria-sort={sort === key ? (direction === "asc" ? "ascending" : "descending") : "none"}
    >
      <button type="button" className="sort-button" onClick={() => toggleSort(key)}>
        {SORT_LABELS[key]}
        <span className="sort-button__arrow" aria-hidden="true">
          {sort === key ? (direction === "asc" ? "↑" : "↓") : ""}
        </span>
      </button>
    </th>
  );

  const counts = summary.data?.counts;

  return (
    <div className="page">
      <PageHeader
        title="Orders"
        description="Every order and where it is in the saga. Statuses update live."
        actions={
          <button className="button" type="button" onClick={() => setTestOrderOpen(true)}>
            <Icon name="plus" /> Test order
          </button>
        }
      />

      <div className="tabs" role="tablist" aria-label="Filter by status">
        {[null, ...ORDER_STATUSES].map((value) => {
          const selected = value === status;
          const count = value === null ? summary.data?.total : counts?.[value];
          return (
            <button
              key={value ?? "all"}
              type="button"
              role="tab"
              aria-selected={selected}
              className={selected ? "tab tab--active" : "tab"}
              onClick={() => setParams({ status: value })}
            >
              {value === null ? "All" : value.charAt(0).toUpperCase() + value.slice(1)}
              {count !== undefined && <span className="tab__count">{formatCount(count)}</span>}
            </button>
          );
        })}
      </div>

      <div className="toolbar">
        <label className="field field--inline">
          <span>Placed</span>
          <select value={range} onChange={(event) => setParams({ range: event.target.value === "all" ? null : event.target.value, from: null, to: null })}>
            {(Object.keys(RANGES) as RangeKey[]).map((key) => (
              <option key={key} value={key}>
                {RANGES[key].label}
              </option>
            ))}
          </select>
        </label>
        {range === "custom" && (
          <>
            <label className="field field--inline">
              <span>From</span>
              <input
                type="datetime-local"
                value={toInputValue(customFrom)}
                onChange={(event) => setParams({ from: fromInputValue(event.target.value) })}
              />
            </label>
            <label className="field field--inline">
              <span>To</span>
              <input
                type="datetime-local"
                value={toInputValue(customTo)}
                onChange={(event) => setParams({ to: fromInputValue(event.target.value) })}
              />
            </label>
          </>
        )}
        <label className="field field--inline field--grow">
          <span>Find</span>
          <input
            type="search"
            className="mono"
            placeholder="Order or customer ID prefix"
            value={query}
            onChange={(event) => setParams({ q: event.target.value })}
            spellCheck={false}
          />
        </label>
      </div>

      <Panel
        title={status ? `${status.charAt(0).toUpperCase()}${status.slice(1)} orders` : "All orders"}
        meta={
          first.data
            ? `${formatCount(rows.length)} shown${query ? ` matching “${query}” in ${formatCount(loaded.length)} loaded` : ""}${nextCursor ? " · more available" : ""}`
            : undefined
        }
        actions={
          <button
            type="button"
            className="icon-button"
            onClick={first.reload}
            aria-label="Refresh orders"
            title="Refresh"
            disabled={first.loading || first.refreshing}
          >
            <Icon name="refresh" />
          </button>
        }
        id="orders"
      >
        {unseen > 0 && (
          <button type="button" className="notice notice--info notice--button" onClick={first.reload}>
            {unseen} new {unseen === 1 ? "order" : "orders"} placed since this list loaded — show
          </button>
        )}
        {first.error && first.data && (
          <StaleNotice error={first.error} updatedAt={first.updatedAt} onRetry={first.reload} />
        )}
        {first.data === undefined ? (
          first.loading ? (
            <SkeletonRows rows={8} columns={6} />
          ) : (
            <ErrorState message={first.error ?? "Unknown error"} onRetry={first.reload} />
          )
        ) : rows.length === 0 ? (
          <EmptyState
            title={query ? "No loaded orders match" : "No orders here"}
            detail={
              query
                ? nextCursor
                  ? "The search only covers loaded orders. Load more, or paste a full order ID into the lookup above."
                  : "Try a different prefix or clear the search."
                : status || range !== "all"
                  ? "Nothing matches these filters. Widen the date range or pick another status."
                  : "Orders appear here as soon as they are placed. Place a test order to see the saga run."
            }
            action={
              query || status || range !== "all" ? (
                <button
                  className="button button--secondary"
                  type="button"
                  onClick={() => setParams({ q: null, status: null, range: null, from: null, to: null })}
                >
                  Clear filters
                </button>
              ) : undefined
            }
          />
        ) : (
          <div className="table-scroll">
            <table className="table table--responsive table--clickable">
              <thead>
                <tr>
                  <th scope="col">Order</th>
                  <th scope="col">Customer</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num">
                    Items
                  </th>
                  {sortHeader("total", "num")}
                  {sortHeader("created")}
                  {sortHeader("updated")}
                  {sortHeader("age", "num")}
                </tr>
              </thead>
              <tbody>
                {rows.map((order) => {
                  const age = orderAge(order, now);
                  const threshold = thresholds[order.status];
                  const overdue =
                    threshold !== undefined &&
                    order.status !== "paid" &&
                    age > threshold * 60_000;
                  return (
                    <tr key={order.id} onClick={(event) => {
                      if ((event.target as HTMLElement).closest("a, button")) return;
                      navigate(orderPath(order.id));
                    }}>
                      <td data-label="Order">
                        <CopyId id={order.id} to={orderPath(order.id)} label="order ID" />
                      </td>
                      <td data-label="Customer" className="mono muted" title={order.userId}>
                        {shortId(order.userId)}
                      </td>
                      <td data-label="Status">
                        <StatusBadge status={order.status} />
                        {overdue && <span className="tag tag--warning">overdue</span>}
                      </td>
                      <td data-label="Items" className="num">
                        {order.items.reduce((sum, item) => sum + item.qty, 0)}
                      </td>
                      <td data-label="Total" className="num">
                        {formatMoney(order.totalAmount)}
                      </td>
                      <td data-label="Placed" className="muted nowrap" title={formatDateTime(order.createdAt)}>
                        {formatDateTime(order.createdAt)}
                      </td>
                      <td data-label="Updated" className="muted">
                        <TimeAgo iso={order.updatedAt} />
                      </td>
                      <td data-label="Duration" className={overdue ? "num text-warning" : "num muted"}>
                        {formatDuration(age)}
                      </td>
                    </tr>
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

      <TestOrderDialog
        open={testOrderOpen}
        onClose={() => setTestOrderOpen(false)}
        onPlaced={(order) => {
          setTestOrderOpen(false);
          notify("success", `Order ${shortId(order.id)} placed — following its saga`);
          navigate(orderPath(order.id));
        }}
      />
    </div>
  );
}
