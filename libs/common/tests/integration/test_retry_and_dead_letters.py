import json
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pika
import pytest

from commerce_common.events.types import EVENT_EXCHANGE
from commerce_common.messaging import Consumer, NonRetryableError, publish_event, run_consumer
from commerce_common.messaging.rabbitmq import (
    LAST_ERROR_HEADER,
    ORIGINAL_ROUTING_KEY_HEADER,
    RETRY_COUNT_HEADER,
    dead_letter_queue_name,
)
from commerce_common.messaging.replay import count_dead_letters, replay_dead_letters

pytestmark = pytest.mark.integration

FAST_RETRIES = (0.2, 0.4)


class Recorder:
    """Thread-safe log of handler calls, failing on demand."""

    def __init__(self, fail_times: int = 0, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_times = fail_times
        self.error = error or RuntimeError("database unavailable")
        self._lock = threading.Lock()

    def __call__(self, routing_key: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self.calls.append((routing_key, payload))
            if len(self.calls) <= self.fail_times:
                raise self.error


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


def wait_until(condition: Callable[[], bool], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def wait_for_queue(url: str, queue: str) -> None:
    """The consumer declares its queues asynchronously; publish only once bound."""

    def exists() -> bool:
        connection = pika.BlockingConnection(pika.URLParameters(url))
        try:
            connection.channel().queue_declare(queue=queue, passive=True)
            return True
        except pika.exceptions.ChannelClosedByBroker:
            return False
        finally:
            if connection.is_open:
                connection.close()

    wait_until(exists)


def get_dead_letter(url: str, queue: str) -> tuple[dict[str, Any], bytes]:
    connection = pika.BlockingConnection(pika.URLParameters(url))
    try:
        method, properties, body = connection.channel().basic_get(
            queue=dead_letter_queue_name(queue), auto_ack=True
        )
        assert method is not None, "dead-letter queue is empty"
        return dict(properties.headers or {}), body
    finally:
        connection.close()


def test_a_transient_failure_is_retried_until_it_succeeds(
    rabbitmq_url: str, names: tuple[str, str], start: Callable[..., Consumer]
) -> None:
    queue, routing_key = names
    handler = Recorder(fail_times=2)
    start(queue_name=queue, routing_keys=[routing_key], handler=handler,
          retry_delays_seconds=FAST_RETRIES)
    wait_for_queue(rabbitmq_url, dead_letter_queue_name(queue))

    publish_event(rabbitmq_url, routing_key, {"order_id": "o-1"})

    wait_until(lambda: len(handler.calls) == 3)
    time.sleep(0.5)
    assert len(handler.calls) == 3
    # Retries arrive via the default exchange, yet the handler still sees the
    # original event type — services dispatch on it.
    assert {key for key, _ in handler.calls} == {routing_key}
    assert count_dead_letters(rabbitmq_url, queue) == 0


def test_a_message_that_keeps_failing_is_dead_lettered_not_redelivered_forever(
    rabbitmq_url: str, names: tuple[str, str], start: Callable[..., Consumer]
) -> None:
    queue, routing_key = names
    handler = Recorder(fail_times=1_000)
    start(queue_name=queue, routing_keys=[routing_key], handler=handler,
          retry_delays_seconds=FAST_RETRIES)
    wait_for_queue(rabbitmq_url, dead_letter_queue_name(queue))

    publish_event(rabbitmq_url, routing_key, {"order_id": "o-2"})

    wait_until(lambda: count_dead_letters(rabbitmq_url, queue) == 1)
    time.sleep(1.0)
    assert len(handler.calls) == 1 + len(FAST_RETRIES)

    headers, body = get_dead_letter(rabbitmq_url, queue)
    assert json.loads(body) == {"order_id": "o-2"}
    assert headers[ORIGINAL_ROUTING_KEY_HEADER] == routing_key
    assert headers[RETRY_COUNT_HEADER] == len(FAST_RETRIES)
    assert headers[LAST_ERROR_HEADER] == "RuntimeError: database unavailable"


def test_a_non_retryable_error_skips_the_retries(
    rabbitmq_url: str, names: tuple[str, str], start: Callable[..., Consumer]
) -> None:
    queue, routing_key = names
    handler = Recorder(fail_times=1_000, error=NonRetryableError("missing order_id"))
    start(queue_name=queue, routing_keys=[routing_key], handler=handler,
          retry_delays_seconds=FAST_RETRIES)
    wait_for_queue(rabbitmq_url, dead_letter_queue_name(queue))

    publish_event(rabbitmq_url, routing_key, {})

    wait_until(lambda: count_dead_letters(rabbitmq_url, queue) == 1)
    assert len(handler.calls) == 1
    headers, _ = get_dead_letter(rabbitmq_url, queue)
    assert headers[RETRY_COUNT_HEADER] == 0
    assert headers[LAST_ERROR_HEADER] == "NonRetryableError: missing order_id"


def test_a_malformed_message_is_dead_lettered_without_reaching_the_handler(
    rabbitmq_url: str, names: tuple[str, str], start: Callable[..., Consumer]
) -> None:
    queue, routing_key = names
    handler = Recorder()
    start(queue_name=queue, routing_keys=[routing_key], handler=handler,
          retry_delays_seconds=FAST_RETRIES)
    wait_for_queue(rabbitmq_url, dead_letter_queue_name(queue))

    connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    try:
        connection.channel().basic_publish(
            exchange=EVENT_EXCHANGE, routing_key=routing_key, body=b"{not json"
        )
    finally:
        connection.close()

    wait_until(lambda: count_dead_letters(rabbitmq_url, queue) == 1)
    assert handler.calls == []
    headers, body = get_dead_letter(rabbitmq_url, queue)
    assert body == b"{not json"
    assert headers[LAST_ERROR_HEADER].startswith("NonRetryableError: body is not valid JSON")


def test_replay_returns_dead_letters_to_their_queue_with_fresh_retries(
    rabbitmq_url: str, names: tuple[str, str], start: Callable[..., Consumer]
) -> None:
    queue, routing_key = names
    # Fails through every retry (3 calls), then the "fix is deployed".
    handler = Recorder(fail_times=1 + len(FAST_RETRIES))
    start(queue_name=queue, routing_keys=[routing_key], handler=handler,
          retry_delays_seconds=FAST_RETRIES)
    wait_for_queue(rabbitmq_url, dead_letter_queue_name(queue))
    publish_event(rabbitmq_url, routing_key, {"order_id": "o-3"})
    wait_until(lambda: count_dead_letters(rabbitmq_url, queue) == 1)

    moved = replay_dead_letters(rabbitmq_url, queue)

    assert moved == 1
    wait_until(lambda: len(handler.calls) == 2 + len(FAST_RETRIES))
    assert handler.calls[-1] == (routing_key, {"order_id": "o-3"})
    assert count_dead_letters(rabbitmq_url, queue) == 0


def test_replay_respects_the_limit(
    rabbitmq_url: str, names: tuple[str, str], start: Callable[..., Consumer]
) -> None:
    queue, routing_key = names
    handler = Recorder(fail_times=1_000, error=NonRetryableError("bad"))
    consumer = start(queue_name=queue, routing_keys=[routing_key], handler=handler,
                     retry_delays_seconds=FAST_RETRIES)
    wait_for_queue(rabbitmq_url, dead_letter_queue_name(queue))
    for n in range(3):
        publish_event(rabbitmq_url, routing_key, {"n": n})
    wait_until(lambda: count_dead_letters(rabbitmq_url, queue) == 3)
    consumer.stop()

    assert replay_dead_letters(rabbitmq_url, queue, limit=2) == 2
    assert count_dead_letters(rabbitmq_url, queue) == 1


def test_fanout_consumers_drop_failures_instead_of_looping(
    rabbitmq_url: str, names: tuple[str, str], start: Callable[..., Consumer]
) -> None:
    _, routing_key = names
    handler = Recorder(fail_times=1)
    start(queue_name=None, routing_keys=[routing_key], handler=handler)
    # A private queue has a broker-generated name, so give the consumer a
    # moment to bind before publishing.
    time.sleep(1.0)

    publish_event(rabbitmq_url, routing_key, {"n": 1})
    publish_event(rabbitmq_url, routing_key, {"n": 2})

    wait_until(lambda: len(handler.calls) == 2)
    time.sleep(0.5)
    assert [payload["n"] for _, payload in handler.calls] == [1, 2]


def test_stop_ends_the_consumer_thread(
    names: tuple[str, str], start: Callable[..., Consumer]
) -> None:
    queue, routing_key = names
    consumer = start(queue_name=queue, routing_keys=[routing_key], handler=Recorder())
    time.sleep(0.5)

    consumer.stop(timeout=5)

    assert not consumer.thread.is_alive()
