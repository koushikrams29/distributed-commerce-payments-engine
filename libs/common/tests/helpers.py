import threading
import time
from collections.abc import Callable
from typing import Any

import pika


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


def wait_until(condition: Callable[[], bool], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def wait_for_queue(url: str, queue: str) -> None:
    """The consumer declares its queues asynchronously; publish only once they exist."""

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
