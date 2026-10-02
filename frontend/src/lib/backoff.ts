export const BASE_DELAY_MS = 1_000;
export const MAX_DELAY_MS = 30_000;

/**
 * Exponential backoff with full jitter. After a gateway restart every open
 * dashboard reconnects at once; the random spread stops them arriving in
 * synchronized waves.
 */
export function reconnectDelay(attempt: number, random: () => number = Math.random): number {
  const ceiling = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** attempt);
  return Math.round(random() * ceiling);
}
