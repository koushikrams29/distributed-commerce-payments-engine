import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { ConnectionPill } from "../components/ConnectionPill";
import { Icon, type IconName } from "../components/ui/Icon";
import { ToolLink } from "../components/ui/ToolLink";
import { shortId } from "../lib/format";
import { Link, navigate, orderPath, useLocation, useRoute, type Route } from "../lib/router";
import { isUuid } from "../types";
import { useLiveData } from "./LiveData";
import { useSessionContext } from "./session";
import { useToolLinks } from "./toolLinks";

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  matches: Route["name"][];
}

const NAV: { heading: string; items: NavItem[] }[] = [
  {
    heading: "Monitor",
    items: [
      { to: "/", label: "Overview", icon: "overview", matches: ["overview"] },
      { to: "/events", label: "Live events", icon: "events", matches: ["events"] },
    ],
  },
  {
    heading: "Commerce",
    items: [
      { to: "/orders", label: "Orders", icon: "orders", matches: ["orders", "order"] },
      { to: "/payments", label: "Payments", icon: "payments", matches: ["payments"] },
      { to: "/inventory", label: "Inventory", icon: "inventory", matches: ["inventory"] },
    ],
  },
  {
    heading: "Operations",
    items: [
      { to: "/failures", label: "Failures", icon: "failures", matches: ["failures"] },
      { to: "/services", label: "Services", icon: "services", matches: ["services"] },
    ],
  },
];

const TITLES: Record<Route["name"], string> = {
  overview: "Overview",
  orders: "Orders",
  order: "Order",
  events: "Live events",
  payments: "Payments",
  inventory: "Inventory",
  failures: "Failures",
  services: "Services",
  "not-found": "Not found",
};

function OrderLookup() {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const id = value.trim().toLowerCase();
    if (isUuid(id)) {
      setError(null);
      setValue("");
      navigate(orderPath(id));
    } else if (/^[0-9a-f-]{4,35}$/.test(id)) {
      // A partial ID can only be matched against orders already listed.
      setError(null);
      navigate(`/orders?q=${encodeURIComponent(id)}`);
    } else {
      setError("Enter an order ID (full UUID or its first characters)");
    }
  };

  return (
    <form className="lookup" role="search" onSubmit={submit}>
      <label className="visually-hidden" htmlFor="order-lookup">
        Find order by ID
      </label>
      <Icon name="search" className="lookup__icon" />
      <input
        id="order-lookup"
        className="lookup__input mono"
        placeholder="Order ID"
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          setError(null);
        }}
        autoComplete="off"
        spellCheck={false}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? "order-lookup-error" : undefined}
      />
      {error && (
        <span id="order-lookup-error" className="lookup__error" role="alert">
          {error}
        </span>
      )}
    </form>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { session, api } = useSessionContext();
  const { connection, snapshotError } = useLiveData();
  const route = useRoute();
  const { pathname } = useLocation();
  const links = useToolLinks();
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => setDrawerOpen(false), [pathname]);

  useEffect(() => {
    document.title = `${TITLES[route.name]} · Commerce Ops`;
  }, [route.name]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  return (
    <div className={drawerOpen ? "shell shell--drawer-open" : "shell"}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar" aria-label="Main navigation">
        <div className="sidebar__brand">
          <span className="brand__mark" aria-hidden="true" />
          <span className="sidebar__label">Commerce Ops</span>
          <button
            type="button"
            className="icon-button sidebar__close"
            onClick={() => setDrawerOpen(false)}
            aria-label="Close navigation"
          >
            <Icon name="close" />
          </button>
        </div>
        <nav className="nav">
          {NAV.map((group) => (
            <div className="nav__group" key={group.heading}>
              <div className="nav__heading sidebar__label">{group.heading}</div>
              {group.items.map((item) => {
                const active = item.matches.includes(route.name);
                return (
                  <Link
                    key={item.to}
                    to={item.to}
                    className={active ? "nav__item nav__item--active" : "nav__item"}
                    aria-current={active ? "page" : undefined}
                    title={item.label}
                  >
                    <Icon name={item.icon} size={18} />
                    <span className="sidebar__label">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="sidebar__footer sidebar__label">
          <ToolLink href={links.jaegerUrl}>Jaeger</ToolLink>
          <ToolLink href={links.grafanaUrl}>Grafana</ToolLink>
          <ToolLink href={links.rabbitmqUrl}>RabbitMQ</ToolLink>
        </div>
      </aside>
      <div className="shell__backdrop" onClick={() => setDrawerOpen(false)} aria-hidden="true" />

      <div className="shell__main">
        <header className="topbar">
          <button
            type="button"
            className="icon-button topbar__menu"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open navigation"
            aria-expanded={drawerOpen}
          >
            <Icon name="menu" size={18} />
          </button>
          <div className="topbar__title">{TITLES[route.name]}</div>
          <OrderLookup />
          <div className="topbar__right">
            <ConnectionPill state={connection} />
            <span className="topbar__user mono" title={`Signed in as admin ${session.userId}`}>
              admin · {shortId(session.userId)}
            </span>
            <button
              className="icon-button"
              type="button"
              onClick={api.signOut}
              aria-label="Sign out"
              title="Sign out"
            >
              <Icon name="signout" />
            </button>
          </div>
        </header>

        {connection === "forbidden" && (
          <div className="banner banner--danger" role="alert">
            The gateway refused the live stream for this account. Pages still load, but nothing
            updates live.
          </div>
        )}
        {connection === "offline" && (
          <div className="banner banner--warning" role="status">
            Live updates paused: the gateway can't be reached. The console keeps retrying and
            resyncs when it's back.
          </div>
        )}
        {snapshotError && connection === "live" && (
          <div className="banner banner--warning" role="status">
            Couldn't load recent orders for the live view: {snapshotError}
          </div>
        )}

        <main id="main" className="content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
