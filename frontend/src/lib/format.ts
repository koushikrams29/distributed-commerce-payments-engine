const currency = new Intl.NumberFormat(undefined, {
  style: "currency",
  currency: "USD",
});

const count = new Intl.NumberFormat(undefined);

const time = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

const preciseTime = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  fractionalSecondDigits: 3,
});

const dateTime = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

const dateOnly = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatMoney(amount: number): string {
  return currency.format(amount);
}

export function formatCount(value: number): string {
  return count.format(value);
}

export function formatTime(iso: string | null): string {
  const date = parse(iso);
  return date ? time.format(date) : "—";
}

/** Clock time with milliseconds, for ordering events that land close together. */
export function formatPreciseTime(iso: string | null): string {
  const date = parse(iso);
  return date ? preciseTime.format(date) : "—";
}

export function formatDateTime(iso: string | null): string {
  const date = parse(iso);
  return date ? dateTime.format(date) : "—";
}

/** "3 s", "4 min", "2 h"; past times only (a small clock skew reads as "now"). */
export function formatRelative(iso: string | null, now: number = Date.now()): string {
  const date = parse(iso);
  if (!date) return "—";
  const seconds = Math.round((now - date.getTime()) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return dateOnly.format(date);
}

/** A span of time in the largest units that keep it readable. */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  if (seconds < 10) return `${seconds.toFixed(1)} s`;
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    const rest = Math.round(seconds - minutes * 60);
    return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    const rest = minutes - hours * 60;
    return rest ? `${hours} h ${rest} min` : `${hours} h`;
  }
  return `${Math.floor(hours / 24)} d`;
}

export function durationBetween(from: string | null, to: string | null): number | null {
  const start = parse(from);
  const end = parse(to);
  return start && end ? end.getTime() - start.getTime() : null;
}

export function formatRate(perSecond: number): string {
  if (perSecond === 0) return "0/s";
  return perSecond < 0.1 ? "<0.1/s" : `${perSecond.toFixed(1)}/s`;
}

export function formatPercent(ratio: number | null): string {
  return ratio === null ? "—" : `${(ratio * 100).toFixed(ratio > 0 && ratio < 0.1 ? 1 : 0)}%`;
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

export function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
