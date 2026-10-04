import { Fragment, useMemo, useState } from "react";

import { useLiveData } from "../app/LiveData";
import { useSessionContext } from "../app/session";
import { queueUrl, useToolLinks } from "../app/toolLinks";
import { useResource } from "../app/useResource";
import { RecentEvents } from "../components/RecentEvents";
import { PaymentBadge } from "../components/StatusBadge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { CopyId } from "../components/ui/CopyId";
import { Icon } from "../components/ui/Icon";
import { KeyValues, PageHeader, Panel } from "../components/ui/Panel";
import { EmptyState, Loadable, SkeletonRows } from "../components/ui/States";
import { TimeAgo, useNow } from "../components/ui/Time";
import { useToast } from "../components/ui/Toast";
import { ToolLink } from "../components/ui/ToolLink";
import {
  fetchDeadLetters,
  fetchOrderSummary,
  fetchOrders,
  fetchPayments,
  fetchQueues,
  replayDeadLetters,
} from "../lib/api";
import { eventOutcome } from "../lib/eventConsole";
import { formatCount, formatDateTime, formatDuration, formatMoney } from "../lib/format";
import { OUTBOX_LAG_MS } from "../lib/health";
import { Link, orderPath, useSearchParams } from "../lib/router";
import { serviceForQueue } from "../lib/topology";

interface PendingReplay {
  queue: string;
  limit: number | null;
  count: number;
}

function DeadLetterInspector({
  queue,
  onReplayed,
}: {
  queue: string;
  onReplayed: () => void;
}) {
  const { api } = useSessionContext();
  const notify = useToast();
  const links = useToolLinks();
  const [expanded, setExpanded] = useState<number | null>(null);
  const [pending, setPending] = useState<PendingReplay | null>(null);
  const [replaying, setReplaying] = useState(false);
  const page = useResource((token, signal) => fetchDeadLetters(token, queue, 20, signal), [queue]);

  const confirmReplay = async () => {
    if (!pending) return;
    setReplaying(true);
    try {
      const replayed = await api.withToken((token) => replayDeadLetters(token, pending.queue, pending.limit));
      notify(
        "success",
        replayed === 0
          ? `Nothing to replay on ${pending.queue}`
          : `Replayed ${formatCount(replayed)} message${replayed === 1 ? "" : "s"} to ${pending.queue}`,
      );
      setPending(null);
      page.reload();
      onReplayed();
    } catch (error) {
      notify("danger", `Replay failed: ${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setReplaying(false);
    }
  };

  const total = page.data?.total ?? 0;

  return (
    <Panel
      title={
        <>
          Dead letters on <span className="mono">{queue}</span>
        </>
      }
      meta={page.data ? `${formatCount(total)} waiting · oldest first` : undefined}
      id="dead-letters"
      actions={
        <>
          <ToolLink href={queueUrl(links, `${queue}.dlq`)} title="Open the queue in RabbitMQ">
            RabbitMQ
          </ToolLink>
          <button type="button" className="icon-button" onClick={page.reload} aria-label="Refresh dead letters" title="Refresh">
            <Icon name="refresh" />
          </button>
          <button
            type="button"
            className="button button--secondary"
            disabled={total === 0}
            onClick={() => setPending({ queue, limit: 1, count: 1 })}
          >
            Replay oldest
          </button>
          <button
            type="button"
            className="button"
            disabled={total === 0}
            onClick={() => setPending({ queue, limit: null, count: total })}
          >
            <Icon name="replay" /> Replay all
          </button>
        </>
      }
    >
      <Loadable
        resource={page}
        skeleton={<SkeletonRows rows={4} columns={4} />}
        errorTitle="Couldn't read the dead-letter queue"
        isEmpty={(data) => data.messages.length === 0}
        empty={
          <EmptyState
            compact
            title="No dead letters"
            detail="Every message on this queue was processed or is still within its retries."
          />
        }
      >
        {(data) => (
          <div className="table-scroll">
            <table className="table table--responsive">
              <thead>
                <tr>
                  <th scope="col">Event</th>
                  <th scope="col">Order</th>
                  <th scope="col" className="num">
                    Attempts
                  </th>
                  <th scope="col">Last error</th>
                  <th scope="col">Dead-lettered</th>
                  <th scope="col">
                    <span className="visually-hidden">Payload</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.messages.map((message, index) => {
                  const open = expanded === index;
                  return (
                    <Fragment key={message.messageId ?? index}>
                      <tr>
                        <td data-label="Event" className="mono">
                          {message.routingKey ?? "unknown"}
                        </td>
                        <td data-label="Order">
                          {message.orderId ? (
                            <CopyId id={message.orderId} to={orderPath(message.orderId)} label="order ID" />
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td data-label="Attempts" className="num">
                          {message.retryCount === null ? "—" : message.retryCount + 1}
                        </td>
                        <td data-label="Last error" className="error-text">
                          {message.lastError ?? <span className="muted">not recorded</span>}
                        </td>
                        <td data-label="Dead-lettered" className="muted">
                          {message.deadLetteredAt ? <TimeAgo iso={message.deadLetteredAt} /> : "—"}
                        </td>
                        <td>
                          <button
                            type="button"
                            className="icon-button icon-button--small"
                            onClick={() => setExpanded(open ? null : index)}
                            aria-expanded={open}
                            aria-label={open ? "Hide payload" : "Show payload"}
                          >
                            <Icon name="chevron" size={14} className={open ? "rotate-90" : undefined} />
                          </button>
                        </td>
                      </tr>
                      {open && (
                        <tr className="payload-row">
                          <td colSpan={6}>
                            <pre className="payload">
                              {typeof message.payload === "string"
                                ? message.payload
                                : JSON.stringify(message.payload, null, 2)}
                            </pre>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
            {data.total > data.messages.length && (
              <p className="panel__note">
                Showing the oldest {data.messages.length} of {formatCount(data.total)}.
              </p>
            )}
          </div>
        )}
      </Loadable>

      <ConfirmDialog
        open={pending !== null}
        title={pending?.limit === 1 ? "Replay the oldest dead letter?" : `Replay ${formatCount(pending?.count ?? 0)} dead letters?`}
        confirmLabel={pending?.limit === 1 ? "Replay 1 message" : "Replay all"}
        busy={replaying}
        onConfirm={confirmReplay}
        onCancel={() => setPending(null)}
      >
        <p>
          {pending?.limit === 1 ? "The oldest message" : "Every message"} on{" "}
          <span className="mono">{pending?.queue}.dlq</span> goes back to{" "}
          <span className="mono">{pending?.queue}</span> with a fresh set of retries.
        </p>
        <p>
          Consumers are idempotent, so a message that already took effect is harmless. If the
          cause hasn't been fixed, the message fails again and returns here after its retries.
        </p>
      </ConfirmDialog>
    </Panel>
  );
}

export function FailuresPage() {
  const { state, connection } = useLiveData();
  const links = useToolLinks();
  const now = useNow();
  const [params, setParams] = useSearchParams();
  const queues = useResource(fetchQueues, [], { pollMs: 10_000 });
  const summary = useResource(fetchOrderSummary, [], { pollMs: 15_000 });
  const cancelled = useResource(
    (token, signal) => fetchOrders(token, { status: "cancelled", limit: 10 }, signal),
    [],
  );
  const declined = useResource(
    (token, signal) => fetchPayments(token, { status: "failed", limit: 10 }, signal),
    [],
  );

  const failureEvents = useMemo(
    () => state.feed.filter((entry) => eventOutcome(entry) !== "ok").slice(0, 12),
    [state.feed],
  );

  const selected =
    params.get("queue") ??
    queues.data?.queues.find((queue) => queue.deadLettered > 0)?.name ??
    null;
  const totalDead = queues.data?.queues.reduce((sum, queue) => sum + queue.deadLettered, 0) ?? 0;

  const outbox = summary.data?.outbox;
  const outboxLag = outbox?.oldestUnpublishedAt ? now - Date.parse(outbox.oldestUnpublishedAt) : 0;

  return (
    <div className="page">
      <PageHeader
        title="Failures"
        description="Messages that ran out of retries, events stuck in the outbox, and orders the reconciler is watching."
      />

      <Panel
        title="Dead-letter queues"
        meta={queues.data ? `${formatCount(totalDead)} dead letters across ${queues.data.queues.length} queues` : undefined}
        id="dlq"
        actions={
          <button type="button" className="icon-button" onClick={queues.reload} aria-label="Refresh queues" title="Refresh">
            <Icon name="refresh" />
          </button>
        }
      >
        <Loadable resource={queues} skeleton={<SkeletonRows rows={5} columns={5} />} errorTitle="Couldn't read queue depths">
          {(data) =>
            data.queues.length === 0 ? (
              <EmptyState compact title="No work queues found" detail="The services haven't declared their queues yet." />
            ) : (
              <div className="table-scroll">
                <table className="table table--responsive table--selectable">
                  <thead>
                    <tr>
                      <th scope="col">Queue</th>
                      <th scope="col">Consumer</th>
                      <th scope="col" className="num">
                        Dead letters
                      </th>
                      <th scope="col" className="num">
                        Retrying
                      </th>
                      <th scope="col" className="num">
                        Waiting
                      </th>
                      <th scope="col">
                        <span className="visually-hidden">Inspect</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.queues.map((queue) => {
                      const isSelected = queue.name === selected;
                      return (
                        <tr key={queue.name} className={isSelected ? "row--selected" : undefined}>
                          <td data-label="Queue" className="mono">
                            {queue.name}
                          </td>
                          <td data-label="Consumer" className="mono muted">
                            {serviceForQueue(queue.name) ?? "—"}
                            {queue.consumers === 0 && <span className="tag tag--danger">no consumer</span>}
                          </td>
                          <td data-label="Dead letters" className={queue.deadLettered ? "num text-danger" : "num muted"}>
                            {formatCount(queue.deadLettered)}
                          </td>
                          <td data-label="Retrying" className={queue.retrying ? "num text-warning" : "num muted"}>
                            {formatCount(queue.retrying)}
                          </td>
                          <td data-label="Waiting" className="num muted">
                            {formatCount(queue.ready)}
                          </td>
                          <td>
                            <button
                              type="button"
                              className={isSelected ? "button button--secondary button--small is-active" : "button button--secondary button--small"}
                              onClick={() => setParams({ queue: queue.name })}
                              aria-pressed={isSelected}
                            >
                              Inspect
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )
          }
        </Loadable>
      </Panel>

      {selected && <DeadLetterInspector key={selected} queue={selected} onReplayed={queues.reload} />}

      <div className="grid grid--two">
        <Panel title="Outbox and reconciler" meta="Order service" id="outbox">
          <Loadable resource={summary} skeleton={<SkeletonRows rows={4} columns={2} />}>
            {(data) => (
              <>
                <KeyValues
                  items={[
                    [
                      "Unpublished events",
                      <span key="unpublished" className={outboxLag > OUTBOX_LAG_MS ? "text-danger" : undefined}>
                        {formatCount(data.outbox.unpublished)}
                        {data.outbox.oldestUnpublishedAt && ` · oldest ${formatDuration(outboxLag)}`}
                      </span>,
                    ],
                    [
                      "Reconciler",
                      data.reconcilerEnabled ? (
                        `Runs every ${formatDuration(data.reconcileIntervalSeconds * 1000)}`
                      ) : (
                        <span key="disabled" className="text-warning">
                          Disabled
                        </span>
                      ),
                    ],
                  ]}
                />
                <table className="table table--compact table--responsive">
                  <caption className="table__caption">Orders past their timeout</caption>
                  <thead>
                    <tr>
                      <th scope="col">Status</th>
                      <th scope="col">Timeout</th>
                      <th scope="col">Reconciler action</th>
                      <th scope="col" className="num">
                        Overdue
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.overdue.map((item) => (
                      <tr key={item.status}>
                        <td data-label="Status">
                          <Link to={`/orders?status=${item.status}`}>{item.status}</Link>
                        </td>
                        <td data-label="Timeout" className="muted">
                          {item.afterMinutes} min
                        </td>
                        <td data-label="Reconciler action" className="muted small">
                          {item.status === "paid" ? "Re-sends order.paid" : "Cancels and compensates"}
                        </td>
                        <td data-label="Overdue" className={item.count ? "num text-warning" : "num muted"}>
                          {formatCount(item.count)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </Loadable>
        </Panel>

        <Panel
          title="Failure events"
          meta="Seen live in this session"
          id="failure-events"
          actions={
            <Link className="panel__link" to="/events?outcome=failures">
              All
            </Link>
          }
        >
          <RecentEvents entries={failureEvents} connection={connection} />
        </Panel>

        <Panel
          title="Recent cancellations"
          id="cancellations"
          actions={
            <Link className="panel__link" to="/orders?status=cancelled">
              All
            </Link>
          }
        >
          <Loadable
            resource={cancelled}
            skeleton={<SkeletonRows rows={4} columns={3} />}
            isEmpty={(page) => page.items.length === 0}
            empty={<EmptyState compact title="No cancelled orders" />}
          >
            {(page) => (
              <table className="table table--compact">
                <tbody>
                  {page.items.map((order) => (
                    <tr key={order.id}>
                      <td>
                        <CopyId id={order.id} to={orderPath(order.id)} label="order ID" />
                      </td>
                      <td className="num">{formatMoney(order.totalAmount)}</td>
                      <td className="num muted" title={formatDateTime(order.updatedAt)}>
                        <TimeAgo iso={order.updatedAt} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Loadable>
        </Panel>

        <Panel
          title="Declined charges"
          id="declined"
          actions={
            <Link className="panel__link" to="/payments?status=failed">
              All
            </Link>
          }
        >
          <Loadable
            resource={declined}
            skeleton={<SkeletonRows rows={4} columns={3} />}
            isEmpty={(page) => page.items.length === 0}
            empty={<EmptyState compact title="No declined charges" />}
          >
            {(page) => (
              <table className="table table--compact">
                <tbody>
                  {page.items.map((payment) => (
                    <tr key={payment.paymentId}>
                      <td>
                        <CopyId id={payment.orderId} to={orderPath(payment.orderId)} label="order ID" />
                      </td>
                      <td>
                        <PaymentBadge status={payment.status} />
                      </td>
                      <td className="num">{formatMoney(payment.amount)}</td>
                      <td className="num muted">
                        <TimeAgo iso={payment.createdAt} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Loadable>
        </Panel>
      </div>

      <p className="page-footnote">
        Retry policy: a message that fails is retried after 2 s, 10 s and 30 s, then dead-lettered.{" "}
        <ToolLink href={links.rabbitmqUrl ? `${links.rabbitmqUrl}/#/queues` : null}>All queues in RabbitMQ</ToolLink>
      </p>
    </div>
  );
}
