from prometheus_client import Counter, Gauge, Histogram

# Labelled `upstream`, not `service`: Prometheus attaches its own `service`
# target label to every scraped series and would rename a clashing one.
UPSTREAM_REQUESTS = Counter(
    "gateway_upstream_requests_total",
    "Requests proxied to a downstream service. outcome is the status code, "
    "or 'timeout' / 'unavailable' when no response arrived.",
    ["upstream", "outcome"],
)
UPSTREAM_DURATION = Histogram(
    "gateway_upstream_request_duration_seconds",
    "Time waiting on a downstream service, including failed attempts.",
    ["upstream"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
RATE_LIMIT_DECISIONS = Counter(
    "gateway_rate_limit_decisions_total",
    "Token bucket decisions. fail_open means Redis was unreachable and the request was allowed.",
    ["limiter", "decision"],
)
DASHBOARD_CONNECTIONS = Gauge(
    "gateway_dashboard_connections",
    "Authenticated dashboard WebSockets currently subscribed to live events.",
)
DASHBOARD_CLIENTS_DROPPED = Counter(
    "gateway_dashboard_clients_dropped_total",
    "Dashboard sockets closed because the client fell too far behind.",
)
