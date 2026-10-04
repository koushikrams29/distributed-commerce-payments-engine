import {
  useCallback,
  useMemo,
  useSyncExternalStore,
  type AnchorHTMLAttributes,
  type MouseEvent,
} from "react";

export type Route =
  | { name: "overview" }
  | { name: "orders" }
  | { name: "order"; orderId: string }
  | { name: "events" }
  | { name: "payments" }
  | { name: "inventory" }
  | { name: "failures" }
  | { name: "services" }
  | { name: "not-found" };

const STATIC_ROUTES: Record<string, Route> = {
  "/": { name: "overview" },
  "/orders": { name: "orders" },
  "/events": { name: "events" },
  "/payments": { name: "payments" },
  "/inventory": { name: "inventory" },
  "/failures": { name: "failures" },
  "/services": { name: "services" },
};

export function matchRoute(pathname: string): Route {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  const fixed = STATIC_ROUTES[path];
  if (fixed) return fixed;
  const order = /^\/orders\/([^/]+)$/.exec(path);
  if (order?.[1]) return { name: "order", orderId: decodeURIComponent(order[1]) };
  return { name: "not-found" };
}

export function orderPath(orderId: string): string {
  return `/orders/${encodeURIComponent(orderId)}`;
}

const NAVIGATE_EVENT = "app:navigate";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  window.addEventListener(NAVIGATE_EVENT, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(NAVIGATE_EVENT, onChange);
  };
}

function snapshot(): string {
  return `${window.location.pathname}${window.location.search}`;
}

export function navigate(to: string, options: { replace?: boolean } = {}): void {
  if (to === snapshot()) return;
  if (options.replace) {
    window.history.replaceState(null, "", to);
  } else {
    window.history.pushState(null, "", to);
    window.scrollTo(0, 0);
  }
  window.dispatchEvent(new Event(NAVIGATE_EVENT));
}

export interface Location {
  pathname: string;
  search: string;
}

export function useLocation(): Location {
  const current = useSyncExternalStore(subscribe, snapshot);
  return useMemo(() => {
    const index = current.indexOf("?");
    return index === -1
      ? { pathname: current, search: "" }
      : { pathname: current.slice(0, index), search: current.slice(index) };
  }, [current]);
}

export function useRoute(): Route {
  const { pathname } = useLocation();
  return useMemo(() => matchRoute(pathname), [pathname]);
}

export type SearchUpdate = Record<string, string | null | undefined>;

/** Filters live in the URL, so a filtered view can be shared or reloaded. */
export function useSearchParams(): [URLSearchParams, (update: SearchUpdate) => void] {
  const { pathname, search } = useLocation();
  const params = useMemo(() => new URLSearchParams(search), [search]);
  const update = useCallback(
    (changes: SearchUpdate) => {
      const next = new URLSearchParams(window.location.search);
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === undefined || value === "") next.delete(key);
        else next.set(key, value);
      }
      const text = next.toString();
      navigate(text ? `${pathname}?${text}` : pathname, { replace: true });
    },
    [pathname],
  );
  return [params, update];
}

interface LinkProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  to: string;
}

export function Link({ to, onClick, children, ...rest }: LinkProps) {
  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    // Let the browser handle new-tab clicks and anything already handled.
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      rest.target === "_blank"
    ) {
      return;
    }
    event.preventDefault();
    navigate(to);
  };
  return (
    <a href={to} onClick={handleClick} {...rest}>
      {children}
    </a>
  );
}
