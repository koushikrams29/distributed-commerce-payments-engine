import type { ReactNode } from "react";

import type { Resource } from "../../app/useResource";
import { formatTime } from "../../lib/format";
import { Icon } from "./Icon";

export function SkeletonRows({ rows = 5, columns = 1 }: { rows?: number; columns?: number }) {
  return (
    <div className="skeleton" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, row) => (
        <div className="skeleton__row" key={row}>
          {Array.from({ length: columns }, (_, column) => (
            <span
              className="skeleton__bar"
              key={column}
              style={{ width: `${column === 0 ? 70 : 40 + ((row * 17 + column * 23) % 45)}%` }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  detail,
  action,
  compact = false,
}: {
  title: string;
  detail?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "empty empty--compact" : "empty"}>
      <p className="empty__title">{title}</p>
      {detail && <p className="empty__detail">{detail}</p>}
      {action && <div className="empty__action">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title = "Couldn't load this",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="empty empty--error" role="alert">
      <p className="empty__title">{title}</p>
      <p className="empty__detail">{message}</p>
      {onRetry && (
        <div className="empty__action">
          <button className="button button--secondary" type="button" onClick={onRetry}>
            <Icon name="refresh" /> Try again
          </button>
        </div>
      )}
    </div>
  );
}

/** A failed refresh while older data stays on screen. */
export function StaleNotice({
  error,
  updatedAt,
  onRetry,
}: {
  error: string;
  updatedAt: number | null;
  onRetry: () => void;
}) {
  return (
    <div className="notice notice--warning" role="status">
      <span>
        Refresh failed: {error}.
        {updatedAt && ` Showing data from ${formatTime(new Date(updatedAt).toISOString())}.`}
      </span>
      <button className="link-button" type="button" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}

interface LoadableProps<T> {
  resource: Resource<T>;
  skeleton?: ReactNode;
  errorTitle?: string;
  /** Rendered instead of `children` when this returns true for the data. */
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  children: (data: T) => ReactNode;
}

/** The loading, error, stale, empty and ready states of one resource, consistently. */
export function Loadable<T>({
  resource,
  skeleton = <SkeletonRows />,
  errorTitle,
  isEmpty,
  empty,
  children,
}: LoadableProps<T>) {
  const { data, error, loading, updatedAt, reload } = resource;
  if (data === undefined) {
    if (loading) return <>{skeleton}</>;
    return <ErrorState title={errorTitle} message={error ?? "Unknown error"} onRetry={reload} />;
  }
  return (
    <>
      {error && <StaleNotice error={error} updatedAt={updatedAt} onRetry={reload} />}
      {isEmpty?.(data) ? empty : children(data)}
    </>
  );
}
