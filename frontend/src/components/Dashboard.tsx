import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { affectsStock } from "../dashboard/events";
import {
  dashboardReducer,
  initialDashboardState,
  selectMetrics,
  sortByActivity,
} from "../dashboard/state";
import { useDashboardSocket } from "../dashboard/useDashboardSocket";
import type { SessionApi } from "../dashboard/useSession";
import { fetchProducts, fetchRecentOrders } from "../lib/api";
import type { Session } from "../lib/auth";
import { shortId } from "../lib/format";
import type { DashboardEvent, Product } from "../types";
import { ConnectionPill } from "./ConnectionPill";
import { EventFeed } from "./EventFeed";
import { MetricCards } from "./MetricCards";
import { OrdersTable } from "./OrdersTable";
import { ProductsPanel } from "./ProductsPanel";

const STOCK_REFRESH_DEBOUNCE_MS = 750;

interface Props {
  session: Session;
  api: SessionApi;
}

export function Dashboard({ session, api }: Props) {
  const { withToken, refresh, signOut } = api;
  const [state, dispatch] = useReducer(dashboardReducer, initialDashboardState);
  const [products, setProducts] = useState<Product[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const stockTimer = useRef<ReturnType<typeof setTimeout>>();

  const loadSnapshot = useCallback(async () => {
    try {
      const [orders, latestProducts] = await Promise.all([
        withToken((token) => fetchRecentOrders(token)),
        withToken(fetchProducts),
      ]);
      dispatch({ type: "snapshot", orders });
      setProducts(latestProducts);
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not load the dashboard");
    }
  }, [withToken]);

  const loadProducts = useCallback(async () => {
    try {
      setProducts(await withToken(fetchProducts));
    } catch {
      // Keep showing the last known stock; the next event or resync retries.
    }
  }, [withToken]);

  const handleEvent = useCallback(
    (event: DashboardEvent) => {
      dispatch({ type: "event", event });
      if (affectsStock(event)) {
        // A single order emits several stock events in quick succession;
        // coalesce them into one refetch.
        clearTimeout(stockTimer.current);
        stockTimer.current = setTimeout(loadProducts, STOCK_REFRESH_DEBOUNCE_MS);
      }
    },
    [loadProducts],
  );

  const handleUnauthorized = useCallback(() => {
    // Success changes the access token, which reconnects the socket; failure
    // signs out and returns to the login screen.
    void refresh();
  }, [refresh]);

  useEffect(() => () => clearTimeout(stockTimer.current), []);

  const connection = useDashboardSocket({
    accessToken: session.accessToken,
    onEvent: handleEvent,
    onReady: loadSnapshot,
    onUnauthorized: handleUnauthorized,
  });

  const orders = useMemo(() => sortByActivity(Object.values(state.orders)), [state.orders]);
  const metrics = useMemo(() => selectMetrics(state), [state]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true" />
          <span>Commerce Ops</span>
          <span className="brand__sub">Live order pipeline</span>
        </div>
        <div className="topbar__right">
          <ConnectionPill state={connection} />
          <span className="topbar__user mono" title={session.userId}>
            admin · {shortId(session.userId)}
          </span>
          <button className="button button--ghost" type="button" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>

      {connection === "forbidden" && (
        <div className="banner banner--danger" role="alert">
          The gateway refused the live stream for this account.
        </div>
      )}
      {loadError && (
        <div className="banner banner--warning" role="alert">
          {loadError}
        </div>
      )}

      <main className="content">
        <MetricCards metrics={metrics} />
        <div className="layout">
          <OrdersTable orders={orders} loading={!state.snapshotLoaded} />
          <div className="sidebar">
            <EventFeed entries={state.feed} />
            <ProductsPanel products={products} />
          </div>
        </div>
      </main>
    </div>
  );
}
