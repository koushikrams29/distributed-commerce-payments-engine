import { describeEvent } from "../dashboard/events";
import type { FeedEntry } from "../dashboard/state";
import { eventRoute } from "./topology";

export type Outcome = "ok" | "failed" | "compensation";

export function eventOutcome(entry: FeedEntry): Outcome {
  const tone = describeEvent(entry.event).tone;
  return tone === "danger" ? "failed" : tone === "warning" ? "compensation" : "ok";
}

export function orderIdOf(entry: FeedEntry): string | null {
  const id = entry.event.data.order_id;
  return typeof id === "string" ? id : null;
}

/**
 * For each event, the time since the previous event of the same order: how
 * long the step that produced it took. Keyed by feed sequence number.
 */
export function stepGaps(feed: FeedEntry[]): Map<number, number> {
  const gaps = new Map<number, number>();
  const lastSeen = new Map<string, number>();
  // The feed is newest first; walk it oldest first.
  for (let index = feed.length - 1; index >= 0; index -= 1) {
    const entry = feed[index];
    if (!entry) continue;
    const orderId = orderIdOf(entry);
    if (!orderId) continue;
    const at = Date.parse(entry.event.receivedAt);
    if (Number.isNaN(at)) continue;
    const previous = lastSeen.get(orderId);
    if (previous !== undefined) gaps.set(entry.seq, at - previous);
    lastSeen.set(orderId, at);
  }
  return gaps;
}

export interface ConsoleFilters {
  type: string | null;
  source: string | null;
  outcome: "failures" | null;
  orderId: string | null;
  text: string;
}

export function matchesFilters(entry: FeedEntry, filters: ConsoleFilters): boolean {
  const { event } = entry;
  if (filters.type && event.type !== filters.type) return false;
  if (filters.source && eventRoute(event.type).source !== filters.source) return false;
  if (filters.outcome === "failures" && eventOutcome(entry) === "ok") return false;
  if (filters.orderId && orderIdOf(entry) !== filters.orderId) return false;
  const text = filters.text.trim().toLowerCase();
  if (text) {
    const haystack = [
      event.type,
      describeEvent(event).title,
      event.traceId ?? "",
      JSON.stringify(event.data),
    ]
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(text)) return false;
  }
  return true;
}

/** Events received in the last minute, by the gateway's clock. */
export function perMinute(feed: FeedEntry[], now: number): number {
  let count = 0;
  for (const entry of feed) {
    const at = Date.parse(entry.event.receivedAt);
    if (now - at > 60_000) break; // newest first, so everything after is older
    count += 1;
  }
  return count;
}
