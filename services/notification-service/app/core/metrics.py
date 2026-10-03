from prometheus_client import Counter

NOTIFICATIONS_SENT = Counter(
    "notifications_sent_total",
    "Order confirmations sent, by channel. Replays of an already-sent confirmation are not counted.",
    ["channel"],
)
