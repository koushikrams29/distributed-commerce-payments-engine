import { describeEvent } from "../dashboard/events";
import type { FeedEntry } from "../dashboard/state";
import type { ConnectionState } from "../dashboard/useDashboardSocket";
import { formatPreciseTime, shortId } from "../lib/format";
import { Link, orderPath } from "../lib/router";
import { EmptyState } from "./ui/States";

const WAITING: Record<ConnectionState, string> = {
  connecting: "Connecting to the event stream…",
  live: "Connected. Events appear here as orders move through the saga.",
  reconnecting: "Reconnecting to the event stream…",
  offline: "The event stream is offline; events will resume when the gateway is reachable.",
  forbidden: "The gateway refused the event stream for this account.",
};

/** A compact list of the latest bus events, for panels beside other content. */
export function RecentEvents({
  entries,
  connection,
}: {
  entries: FeedEntry[];
  connection: ConnectionState;
}) {
  if (entries.length === 0) {
    return <EmptyState compact title="No events yet" detail={WAITING[connection]} />;
  }
  return (
    <ol className="feed">
      {entries.map(({ seq, event }) => {
        const description = describeEvent(event);
        const orderId = typeof event.data.order_id === "string" ? event.data.order_id : null;
        return (
          <li key={seq} className={`feed__item feed__item--${description.tone}`}>
            <div className="feed__title">{description.title}</div>
            <div className="feed__meta">
              <span className="mono">{event.type}</span>
              {orderId && (
                <Link className="mono" to={orderPath(orderId)}>
                  {shortId(orderId)}
                </Link>
              )}
              <time dateTime={event.receivedAt}>{formatPreciseTime(event.receivedAt)}</time>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
