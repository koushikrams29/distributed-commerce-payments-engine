import { useCallback, useRef, useState } from "react";

import { ApiError, refreshTokens } from "../lib/api";
import { isAdmin, loadSession, saveSession, sessionFromTokens, type Session } from "../lib/auth";
import type { TokenPair } from "../types";

export class NotAdminError extends Error {
  constructor() {
    super("This dashboard is for administrators only");
    this.name = "NotAdminError";
  }
}

export interface SessionApi {
  session: Session | null;
  signIn: (pair: TokenPair) => void;
  signOut: () => void;
  /** Swaps the refresh token for a new pair; signs out if that is impossible. */
  refresh: () => Promise<Session | null>;
  /** Runs an authorized call, refreshing once and retrying on a 401. */
  withToken: <T>(call: (accessToken: string) => Promise<T>) => Promise<T>;
}

export function useSession(): SessionApi {
  const [session, setSession] = useState<Session | null>(() => {
    const stored = loadSession();
    return stored && isAdmin(stored) ? stored : null;
  });
  const sessionRef = useRef(session);
  // Refresh tokens are single-use (rotated on every refresh). Two concurrent
  // refreshes would spend the same token twice and the second would fail, so
  // every caller shares one in-flight request.
  const inFlight = useRef<Promise<Session | null> | null>(null);

  const update = useCallback((next: Session | null) => {
    sessionRef.current = next;
    saveSession(next);
    setSession(next);
  }, []);

  const signIn = useCallback(
    (pair: TokenPair) => {
      const next = sessionFromTokens(pair);
      if (!next) throw new Error("The gateway returned an unreadable token");
      if (!isAdmin(next)) throw new NotAdminError();
      update(next);
    },
    [update],
  );

  const signOut = useCallback(() => update(null), [update]);

  const refresh = useCallback((): Promise<Session | null> => {
    if (inFlight.current) return inFlight.current;
    const current = sessionRef.current;
    if (!current) return Promise.resolve(null);

    inFlight.current = refreshTokens(current.refreshToken)
      .then((pair) => {
        const next = sessionFromTokens(pair);
        update(next && isAdmin(next) ? next : null);
        return sessionRef.current;
      })
      .catch(() => {
        update(null);
        return null;
      })
      .finally(() => {
        inFlight.current = null;
      });
    return inFlight.current;
  }, [update]);

  const withToken = useCallback(
    async <T,>(call: (accessToken: string) => Promise<T>): Promise<T> => {
      const current = sessionRef.current;
      if (!current) throw new ApiError(401, "Signed out");
      try {
        return await call(current.accessToken);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;
        const renewed = await refresh();
        if (!renewed) throw error;
        return call(renewed.accessToken);
      }
    },
    [refresh],
  );

  return { session, signIn, signOut, refresh, withToken };
}
