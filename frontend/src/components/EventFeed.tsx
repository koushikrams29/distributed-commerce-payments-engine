import { describeEvent } from "../dashboard/events";
import type { FeedEntry } from "../dashboard/state";
import { formatTime } from "../lib/format";

export function EventFeed({ entries }: { entries: FeedEntry[] }) {
  return (
    <section className="panel panel--feed" aria-labelledby="feed-heading">
      <header className="panel__header">
        <h2 id="feed-heading">Event stream</h2>
        <span className="panel__meta">commerce.events</span>
      </header>
      {entries.length === 0 ? (
        <p className="feed__empty">Waiting for events…</p>
      ) : (
        <ol className="feed" aria-live="polite">
          {entries.map(({ seq, event }) => {
            const description = describeEvent(event);
            return (
              <li key={seq} className={`feed__item feed__item--${description.tone}`}>
                <div className="feed__title">{description.title}</div>
                <div className="feed__meta">
                  <span className="mono">{event.type}</span>
                  <span>{formatTime(event.receivedAt)}</span>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
