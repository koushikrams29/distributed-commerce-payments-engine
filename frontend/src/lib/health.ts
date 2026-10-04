import type { ConnectionState } from "../dashboard/useDashboardSocket";
import type { OrderSummary, QueueOverview, SystemHealth } from "../types";
import { formatDuration } from "./format";

export type Verdict = "healthy" | "attention" | "degraded" | "unknown";

export interface Issue {
  severity: "danger" | "warning";
  text: string;
  /** Where to go to act on it. */
  to: string;
}

export interface Assessment {
  verdict: Verdict;
  headline: string;
  issues: Issue[];
}

/** Outbox rows older than this mean the relay is stuck, not just busy. */
export const OUTBOX_LAG_MS = 30_000;
/** Ready messages beyond this mean consumers are falling behind. */
export const QUEUE_BACKLOG = 100;

export interface AssessmentInput {
  health?: SystemHealth;
  healthError?: string | null;
  queues?: QueueOverview;
  queuesError?: string | null;
  orders?: OrderSummary;
  connection: ConnectionState;
  now: number;
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/** Answers "is the commerce system healthy right now?" from everything the console can see. */
export function assessSystem(input: AssessmentInput): Assessment {
  const issues: Issue[] = [];

  if (input.healthError && !input.health) {
    issues.push({ severity: "danger", text: `Service health unavailable: ${input.healthError}`, to: "/services" });
  }
  for (const component of input.health?.components ?? []) {
    if (component.status === "up") continue;
    issues.push({
      severity: component.status === "down" ? "danger" : "warning",
      text: `${component.name} is ${component.status}${component.detail ? ` — ${component.detail}` : ""}`,
      to: "/services",
    });
  }

  if (input.queuesError && !input.queues) {
    issues.push({ severity: "warning", text: `Queue depths unavailable: ${input.queuesError}`, to: "/services" });
  }
  for (const queue of input.queues?.queues ?? []) {
    if (queue.consumers === 0) {
      issues.push({
        severity: "danger",
        text: `No consumer on ${queue.name}; its events are not being processed`,
        to: "/services",
      });
    }
    if (queue.deadLettered > 0) {
      issues.push({
        severity: "warning",
        text: `${plural(queue.deadLettered, "dead letter")} on ${queue.name}`,
        to: `/failures?queue=${encodeURIComponent(queue.name)}`,
      });
    }
    if (queue.ready > QUEUE_BACKLOG) {
      issues.push({
        severity: "warning",
        text: `${queue.ready} messages waiting on ${queue.name}`,
        to: "/services",
      });
    }
  }

  const orders = input.orders;
  if (orders) {
    const oldest = orders.outbox.oldestUnpublishedAt;
    const lag = oldest ? input.now - Date.parse(oldest) : 0;
    if (orders.outbox.unpublished > 0 && lag > OUTBOX_LAG_MS) {
      issues.push({
        severity: "danger",
        text: `Outbox relay is behind: ${plural(orders.outbox.unpublished, "event")} unpublished, oldest ${formatDuration(lag)}`,
        to: "/failures",
      });
    }
    for (const overdue of orders.overdue) {
      if (overdue.count === 0) continue;
      issues.push({
        severity: "warning",
        text: `${plural(overdue.count, `${overdue.status} order`)} past the ${overdue.afterMinutes} min timeout`,
        to: `/orders?status=${overdue.status}`,
      });
    }
    if (!orders.reconcilerEnabled) {
      issues.push({
        severity: "warning",
        text: "The reconciler is disabled; stuck orders won't be cancelled or retried",
        to: "/failures",
      });
    }
  }

  if (input.connection === "offline" || input.connection === "forbidden") {
    issues.push({
      severity: "warning",
      text: input.connection === "offline" ? "Live event stream is offline" : "Live event stream refused",
      to: "/events",
    });
  }

  issues.sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "danger" ? -1 : 1));
  const dangers = issues.filter((issue) => issue.severity === "danger").length;

  if (!input.health && !input.healthError) {
    return { verdict: "unknown", headline: "Checking services…", issues };
  }
  if (dangers > 0) {
    return { verdict: "degraded", headline: `Degraded — ${plural(dangers, "problem")} need action`, issues };
  }
  if (issues.length > 0) {
    return { verdict: "attention", headline: `Operational — ${plural(issues.length, "item")} to review`, issues };
  }
  return { verdict: "healthy", headline: "All systems operational", issues };
}
