"""Thread-safe, process-local event fan-out for Phase 3 streams."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from queue import Empty, Full, Queue
from threading import Lock
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class Event:
    id: str
    kind: str
    occurred_at: datetime
    payload: object


class EventSubscription:
    def __init__(self, broker: EventBroker, queue: Queue[Event]) -> None:
        self._broker = broker
        self._queue = queue

    def get(self, timeout: float) -> Event | None:
        try:
            return self._queue.get(timeout=timeout)
        except Empty:
            return None

    def close(self) -> None:
        self._broker.unsubscribe(self._queue)


class EventBroker:
    """Fan out ephemeral events; durable history remains in repositories."""

    def __init__(self, *, subscriber_queue_size: int = 1_000) -> None:
        self._queue_size = subscriber_queue_size
        self._subscribers: set[Queue[Event]] = set()
        self._lock = Lock()

    def subscribe(self) -> EventSubscription:
        queue: Queue[Event] = Queue(maxsize=self._queue_size)
        with self._lock:
            self._subscribers.add(queue)
        return EventSubscription(self, queue)

    def unsubscribe(self, queue: Queue[Event]) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def publish(self, kind: str, payload: object, occurred_at: datetime) -> Event:
        event = Event(str(uuid4()), kind, occurred_at, payload)
        with self._lock:
            subscribers = tuple(self._subscribers)
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except Full:
                # A live stream is best-effort; clients recover durable chat via history.
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (Empty, Full):
                    pass
        return event
