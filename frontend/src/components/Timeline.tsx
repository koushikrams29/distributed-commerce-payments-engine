import type { ReactNode } from "react";

import { traceUrl, useToolLinks } from "../app/toolLinks";
import { formatDateTime, formatDuration, formatPreciseTime } from "../lib/format";
import type { Tone } from "../lib/saga";
import { Icon } from "./ui/Icon";

export interface TimelineEntry {
  key: string;
  at: string;
  /** Service that recorded or emitted it. */
  source: string;
  title: string;
  detail?: ReactNode;
  tone: Tone;
  /** Routing key, when the entry is a bus event. */
  eventType?: string;
  traceId?: string | null;
  /** Written but not yet published by the outbox relay. */
  unpublished?: boolean;
  /** Seen on the live stream rather than read from a service's database. */
  live?: boolean;
}

export function Timeline({ entries }: { entries: TimelineEntry[] }) {
  const links = useToolLinks();
  return (
    <ol className="timeline">
      {entries.map((entry, index) => {
        const previous = entries[index - 1];
        const gap = previous ? Date.parse(entry.at) - Date.parse(previous.at) : null;
        const trace = entry.traceId ? traceUrl(links, entry.traceId) : null;
        return (
          <li key={entry.key} className={`timeline__item timeline__item--${entry.tone}`}>
            <div className="timeline__time">
              <time dateTime={entry.at} title={formatDateTime(entry.at)}>
                {formatPreciseTime(entry.at)}
              </time>
              {gap !== null && gap >= 0 && <span className="timeline__gap">+{formatDuration(gap)}</span>}
            </div>
            <div className="timeline__body">
              <div className="timeline__title">
                {entry.title}
                {entry.unpublished && <span className="tag tag--warning">awaiting relay</span>}
                {entry.live && <span className="tag">live stream</span>}
              </div>
              {entry.detail && <div className="timeline__detail">{entry.detail}</div>}
              <div className="timeline__meta">
                <span className="mono">{entry.source}</span>
                {entry.eventType && <span className="mono">{entry.eventType}</span>}
                {entry.traceId &&
                  (trace ? (
                    <a className="tool-link mono" href={trace} target="_blank" rel="noreferrer">
                      <Icon name="trace" size={12} /> {entry.traceId.slice(0, 12)}
                    </a>
                  ) : (
                    <span className="mono" title={entry.traceId}>
                      trace {entry.traceId.slice(0, 12)}
                    </span>
                  ))}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
