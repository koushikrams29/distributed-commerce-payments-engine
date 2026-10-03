import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from commerce_common.messaging import Consumer, run_consumer


@pytest.fixture
def names() -> tuple[str, str]:
    """A unique queue and routing key per test, so tests never see each other's messages."""
    suffix = uuid.uuid4().hex[:8]
    return f"test.{suffix}", f"test.event.{suffix}"


@pytest.fixture
def start(rabbitmq_url: str) -> Iterator[Callable[..., Consumer]]:
    consumers: list[Consumer] = []

    def _start(**kwargs: Any) -> Consumer:
        consumer = run_consumer(url=rabbitmq_url, reconnect_delay_seconds=0.5, **kwargs)
        consumers.append(consumer)
        return consumer

    yield _start
    for consumer in consumers:
        consumer.stop()
