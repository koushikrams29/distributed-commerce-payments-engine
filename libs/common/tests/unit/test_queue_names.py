import pytest

from commerce_common.messaging.rabbitmq import dead_letter_queue_name, retry_queue_name


@pytest.mark.parametrize(
    ("delay", "expected"),
    [
        (2.0, "payment.events.retry.2s"),
        (30, "payment.events.retry.30s"),
        (0.25, "payment.events.retry.250ms"),
        (1.5, "payment.events.retry.1500ms"),
    ],
)
def test_retry_queue_name_encodes_the_delay(delay: float, expected: str) -> None:
    assert retry_queue_name("payment.events", delay) == expected


def test_dead_letter_queue_name() -> None:
    assert dead_letter_queue_name("payment.events") == "payment.events.dlq"
