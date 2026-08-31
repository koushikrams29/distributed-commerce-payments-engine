"""Routing keys for the commerce.events topic exchange."""

EVENT_EXCHANGE = "commerce.events"


class EventType:
    ORDER_CREATED = "order.created"
    INVENTORY_RESERVED = "inventory.reserved"
    INVENTORY_FAILED = "inventory.failed"
    CHARGE_REQUESTED = "charge.requested"
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"
    ORDER_CANCELLED = "order.cancelled"
