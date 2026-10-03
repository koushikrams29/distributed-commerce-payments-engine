from prometheus_client import Counter, Histogram

MESSAGES_PUBLISHED = Counter(
    "messages_published_total",
    "Events published to the commerce.events exchange.",
    ["routing_key"],
)
MESSAGES_CONSUMED = Counter(
    "messages_consumed_total",
    "Messages taken off a queue, by outcome: success, retried, dead_lettered or dropped.",
    ["queue", "routing_key", "outcome"],
)
MESSAGE_HANDLER_DURATION = Histogram(
    "message_handler_duration_seconds",
    "Time spent in an event handler.",
    ["queue", "routing_key"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
