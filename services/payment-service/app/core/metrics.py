from prometheus_client import Counter

PAYMENT_ATTEMPTS = Counter(
    "payment_attempts_total",
    "Charges sent to the payment gateway, by result. Idempotent replays are not attempts.",
    ["result"],
)
PAYMENT_REPLAYS = Counter(
    "payment_idempotent_replays_total",
    "Charge requests answered from an earlier attempt with the same idempotency key.",
)
PAYMENT_CAPTURED_AMOUNT = Counter(
    "payment_captured_amount_total",
    "Sum of successfully charged amounts (single currency).",
)
PAYMENT_REFUNDS = Counter(
    "payment_refunds_total",
    "Successful charges refunded back to the customer.",
)
