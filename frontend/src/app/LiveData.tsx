import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  dashboardReducer,
  initialDashboardState,
  type DashboardState,
} from "../dashboard/state";
import { useDashboardSocket, type ConnectionState } from "../dashboard/useDashboardSocket";
import { fetchRecentOrders } from "../lib/api";
import type { DashboardEvent } from "../types";
import { useSessionContext } from "./session";

type Listener = (event: DashboardEvent) => void;

interface LiveDataValue {
  state: DashboardState;
  connection: ConnectionState;
  /** Error from the last snapshot load, if it failed. */
  snapshotError: string | null;
  subscribe: (listener: Listener) => () => void;
}

const LiveDataContext = createContext<LiveDataValue | null>(null);

/** One socket for the whole console; pages read the shared feed and order map. */
export function LiveDataProvider({ children }: { children: ReactNode }) {
  const { session, api } = useSessionContext();
  const { withToken, refresh } = api;
  const [state, dispatch] = useReducer(dashboardReducer, initialDashboardState);
  const listeners = useRef(new Set<Listener>());
  const [snapshotError, setSnapshotError] = useState<string | null>(null);

  const loadSnapshot = useCallback(async () => {
    try {
      const orders = await withToken((token) => fetchRecentOrders(token));
      dispatch({ type: "snapshot", orders });
      setSnapshotError(null);
    } catch (error) {
      setSnapshotError(error instanceof Error ? error.message : "Could not load orders");
    }
  }, [withToken]);

  const handleEvent = useCallback((event: DashboardEvent) => {
    dispatch({ type: "event", event });
    for (const listener of listeners.current) listener(event);
  }, []);

  const handleUnauthorized = useCallback(() => {
    // Success changes the access token, which reconnects the socket; failure
    // signs out and returns to the login screen.
    void refresh();
  }, [refresh]);

  const connection = useDashboardSocket({
    accessToken: session.accessToken,
    onEvent: handleEvent,
    onReady: loadSnapshot,
    onUnauthorized: handleUnauthorized,
  });

  const subscribe = useCallback((listener: Listener) => {
    listeners.current.add(listener);
    return () => {
      listeners.current.delete(listener);
    };
  }, []);

  const value = useMemo(
    () => ({ state, connection, snapshotError, subscribe }),
    [state, connection, snapshotError, subscribe],
  );
  return <LiveDataContext.Provider value={value}>{children}</LiveDataContext.Provider>;
}

export function useLiveData(): LiveDataValue {
  const value = useContext(LiveDataContext);
  if (!value) throw new Error("useLiveData must be used inside <LiveDataProvider>");
  return value;
}

/**
 * Calls `onMatch` (debounced) after live events that pass `filter`, so a page
 * can refetch when something it shows has changed. Bursts of events, like the
 * five a single order emits, collapse into one call.
 */
export function useLiveRefresh(
  filter: (event: DashboardEvent) => boolean,
  onMatch: () => void,
  debounceMs = 1500,
): void {
  const { subscribe } = useLiveData();
  const latest = useRef({ filter, onMatch });
  latest.current = { filter, onMatch };

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = subscribe((event) => {
      if (!latest.current.filter(event)) return;
      clearTimeout(timer);
      timer = setTimeout(() => latest.current.onMatch(), debounceMs);
    });
    return () => {
      clearTimeout(timer);
      unsubscribe();
    };
  }, [subscribe, debounceMs]);
}
