import { Fragment, useMemo, useState } from "react";

import { useLiveData } from "../app/LiveData";
import { traceUrl, useToolLinks } from "../app/toolLinks";
import { ConnectionPill } from "../components/ConnectionPill";
import { Badge } from "../components/StatusBadge";
import { Icon } from "../components/ui/Icon";
import { PageHeader, Panel } from "../components/ui/Panel";
import { EmptyState } from "../components/ui/States";
import { useNow } from "../components/ui/Time";
import { describeEvent } from "../dashboard/events";
import { FEED_LIMIT, type FeedEntry } from "../dashboard/state";
import {
  eventOutcome,
  matchesFilters,
  orderIdOf,
  perMinute,
  stepGaps,
  type ConsoleFilters,
  type Outcome,
} from "../lib/eventConsole";
import { formatCount, formatDuration, formatPreciseTime, shortId } from "../lib/format";
import { Link, orderPath, useSearchParams } from "../lib/router";
import { KNOWN_EVENT_TYPES, SERVICE_NAMES, eventRoute } from "../lib/topology";

const OUTCOME_TONES: Record<Outcome, "success" | "danger" | "warning"> = {
  ok: "success",
  failed: "danger",
  compensation: "warning",
};

const OUTCOME_LABELS: Record<Outcome, string> = {
  ok: "OK",
  failed: "Failed",
  compensation: "Compensating",
};

export function EventsPage() {
  const { state, connection } = useLiveData();
  const links = useToolLinks();
  const now = useNow();
  const [params, setParams] = useSearchParams();
  const [frozen, setFrozen] = useState<FeedEntry[] | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  const filters: ConsoleFilters = {
    type: params.get("type"),
    source: params.get("source"),
    outcome: params.get("outcome") === "failures" ? "failures" : null,
    orderId: params.get("order"),
    text: params.get("q") ?? "",
  };

  const feed = frozen ?? state.feed;
  const gaps = useMemo(() => stepGaps(feed), [feed]);
  const rows = feed.filter((entry) => matchesFilters(entry, filters));
  const pendingWhilePaused = frozen ? state.eventsReceived - (frozen[0]?.seq ?? 0) : 0;
  const filtered = Boolean(filters.type || filters.source || filters.outcome || filters.orderId || filters.text);

  return (
    <div className="page">
      <PageHeader
        title="Live events"
        description={
          <>
            Every message on the <span className="mono">commerce.events</span> exchange, as the
            gateway relays it. The last {formatCount(FEED_LIMIT)} are kept in this tab.
          </>
        }
        actions={
          <>
            <ConnectionPill state={connection} />
            <button
              type="button"
              className="button button--secondary"
              onClick={() => setFrozen(frozen ? null : state.feed)}
              aria-pressed={frozen !== null}
            >
              <Icon name={frozen ? "play" : "pause"} /> {frozen ? "Resume" : "Pause"}
            </button>
          </>
        }
      />

      <div className="toolbar">
        <label className="field field--inline field--grow">
          <span>Search</span>
          <input
            type="search"
            placeholder="Type, order, trace or payload text"
            value={filters.text}
            onChange={(event) => setParams({ q: event.target.value })}
            spellCheck={false}
          />
        </label>
        <label className="field field--inline">
          <span>Event</span>
          <select value={filters.type ?? ""} onChange={(event) => setParams({ type: event.target.value })}>
            <option value="">All types</option>
            {KNOWN_EVENT_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <label className="field field--inline">
          <span>Source</span>
          <select value={filters.source ?? ""} onChange={(event) => setParams({ source: event.target.value })}>
            <option value="">All services</option>
            {SERVICE_NAMES.filter((service) =>
              KNOWN_EVENT_TYPES.some((type) => eventRoute(type).source === service),
            ).map((service) => (
              <option key={service} value={service}>
                {service}
              </option>
            ))}
          </select>
        </label>
        <label className="field field--inline field--check">
          <input
            type="checkbox"
            checked={filters.outcome === "failures"}
            onChange={(event) => setParams({ outcome: event.target.checked ? "failures" : null })}
          />
          <span>Failures and compensation only</span>
        </label>
        {filters.orderId && (
          <span className="chip">
            Order <span className="mono">{shortId(filters.orderId)}</span>
            <button
              type="button"
              className="icon-button icon-button--small"
              onClick={() => setParams({ order: null })}
              aria-label="Clear order filter"
            >
              <Icon name="close" size={12} />
            </button>
          </span>
        )}
      </div>

      <Panel
        title="Event stream"
        meta={`${formatCount(rows.length)} shown · ${perMinute(state.feed, now)}/min · ${formatCount(state.eventsReceived)} this session`}
        id="event-stream"
      >
        {frozen && (
          <button type="button" className="notice notice--info notice--button" onClick={() => setFrozen(null)}>
            Paused. {pendingWhilePaused > 0 ? `${formatCount(pendingWhilePaused)} new events — ` : ""}resume
          </button>
        )}
        {rows.length === 0 ? (
          filtered && feed.length > 0 ? (
            <EmptyState
              title="No events match"
              detail="Nothing in the kept history matches these filters."
              action={
                <button
                  className="button button--secondary"
                  type="button"
                  onClick={() => setParams({ q: null, type: null, source: null, outcome: null, order: null })}
                >
                  Clear filters
                </button>
              }
            />
          ) : (
            <EmptyState
              title={connection === "live" ? "Waiting for events" : "No events yet"}
              detail={
                connection === "live"
                  ? "Connected. Place an order to see the saga's events stream in."
                  : "Events appear once the live stream connects."
              }
              action={
                connection === "live" ? (
                  <Link className="button button--secondary" to="/orders">
                    Go to orders
                  </Link>
                ) : undefined
              }
            />
          )
        ) : (
          <div className="table-scroll table-scroll--tall">
            <table className="table table--responsive table--events">
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Event</th>
                  <th scope="col">Route</th>
                  <th scope="col">Order</th>
                  <th scope="col">Outcome</th>
                  <th scope="col" className="num" title="Time since the previous event for the same order">
                    Step
                  </th>
                  <th scope="col">Trace</th>
                  <th scope="col">
                    <span className="visually-hidden">Payload</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => {
                  const { event, seq } = entry;
                  const description = describeEvent(event);
                  const route = eventRoute(event.type);
                  const orderId = orderIdOf(entry);
                  const outcome = eventOutcome(entry);
                  const gap = gaps.get(seq);
                  const trace = event.traceId ? traceUrl(links, event.traceId) : null;
                  const open = expanded === seq;
                  return (
                    <Fragment key={seq}>
                      <tr className={`event-row event-row--${description.tone}`}>
                        <td data-label="Time" className="mono nowrap">
                          {formatPreciseTime(event.receivedAt)}
                        </td>
                        <td data-label="Event">
                          <div className="mono">{event.type}</div>
                          <div className="muted small">{description.title}</div>
                        </td>
                        <td data-label="Route" className="small">
                          <span className="mono">{route.source ?? "unknown"}</span>
                          <span className="muted"> → </span>
                          <span className="mono">
                            {route.consumers.length ? route.consumers.join(", ") : "console only"}
                          </span>
                        </td>
                        <td data-label="Order">
                          {orderId ? (
                            <Link className="mono" to={orderPath(orderId)} title={orderId}>
                              {shortId(orderId)}
                            </Link>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td data-label="Outcome">
                          <Badge tone={OUTCOME_TONES[outcome]}>{OUTCOME_LABELS[outcome]}</Badge>
                        </td>
                        <td data-label="Step" className="num mono muted">
                          {gap === undefined ? "—" : `+${formatDuration(gap)}`}
                        </td>
                        <td data-label="Trace">
                          {event.traceId ? (
                            trace ? (
                              <a className="tool-link mono" href={trace} target="_blank" rel="noreferrer" title={event.traceId}>
                                {event.traceId.slice(0, 8)}
                                <Icon name="external" size={12} />
                              </a>
                            ) : (
                              <span className="mono" title={event.traceId}>
                                {event.traceId.slice(0, 8)}
                              </span>
                            )
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td>
                          <button
                            type="button"
                            className="icon-button icon-button--small"
                            onClick={() => setExpanded(open ? null : seq)}
                            aria-expanded={open}
                            aria-label={open ? "Hide payload" : "Show payload"}
                            title={open ? "Hide payload" : "Show payload"}
                          >
                            <Icon name="chevron" size={14} className={open ? "rotate-90" : undefined} />
                          </button>
                        </td>
                      </tr>
                      {open && (
                        <tr className="payload-row">
                          <td colSpan={8}>
                            <pre className="payload">{JSON.stringify(event.data, null, 2)}</pre>
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
      </Panel>
    </div>
  );
}
