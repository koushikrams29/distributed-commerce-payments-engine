import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

Message = dict[str, Any]

# Put on a subscriber's queue when it fell too far behind and was dropped.
OVERFLOW: Message = {"type": "_overflow"}


@dataclass(eq=False)
class Subscription:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[Message] = field(default_factory=asyncio.Queue)


class DashboardHub:
    """Fans events out to every connected dashboard socket.

    `publish` is safe to call from any thread (the RabbitMQ consumer runs on
    its own). Each subscriber has a bounded queue: one slow browser is
    disconnected rather than buffering without limit or stalling the others.
    """

    def __init__(self, max_queue_size: int = 256) -> None:
        self._max_queue_size = max_queue_size
        self._lock = threading.Lock()
        self._subscriptions: set[Subscription] = set()

    def subscribe(self) -> Subscription:
        """Call from the event loop that will read the subscription."""
        subscription = Subscription(
            loop=asyncio.get_running_loop(),
            queue=asyncio.Queue(maxsize=self._max_queue_size),
        )
        with self._lock:
            self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            self._subscriptions.discard(subscription)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscriptions)

    def publish(self, message: Message) -> None:
        with self._lock:
            subscriptions = list(self._subscriptions)
        for subscription in subscriptions:
            try:
                subscription.loop.call_soon_threadsafe(
                    self._deliver, subscription, message
                )
            except RuntimeError:
                # The subscriber's event loop has already shut down.
                self.unsubscribe(subscription)

    def _deliver(self, subscription: Subscription, message: Message) -> None:
        try:
            subscription.queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("dashboard client too slow; disconnecting it")
            self.unsubscribe(subscription)
            while not subscription.queue.empty():
                subscription.queue.get_nowait()
            subscription.queue.put_nowait(OVERFLOW)
