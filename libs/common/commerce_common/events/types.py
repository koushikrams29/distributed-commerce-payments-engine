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
    ORDER_PAID = "order.paid"
    INVENTORY_COMMITTED = "inventory.committed"
    ORDER_FULFILLED = "order.fulfilled"
    REFUND_REQUESTED = "refund.requested"
    PAYMENT_REFUNDED = "payment.refunded"
    ORDER_STATUS_CHANGED = "order.status_changed"
