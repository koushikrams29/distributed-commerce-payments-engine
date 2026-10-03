from prometheus_client import Counter

RESERVATION_REQUESTS = Counter(
    "inventory_reservation_requests_total",
    "Per-order reservation requests, by result. replayed means the order already had reservations.",
    ["result"],
)
RESERVATIONS_SETTLED = Counter(
    "inventory_reservations_settled_total",
    "Held reservation rows made permanent (committed) or returned to stock (released).",
    ["outcome"],
)
