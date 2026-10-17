"""
Event Bus PubSub Architecture.
Allows decoupled, thread-safe event publishing and subscription across the
queue engine, background scheduler, CLI display, REST API, and webhooks.
"""

import time
import threading
from enum import Enum
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass, field


class EventType(str, Enum):
    JOB_ENQUEUED = "job_enqueued"
    JOB_STARTED = "job_started"
    JOB_PROGRESS = "job_progress"
    JOB_FINISHED = "job_finished"
    JOB_FAILED = "job_failed"
    JOB_CANCELLED = "job_cancelled"
    JOB_PAUSED = "job_paused"
    JOB_RESUMED = "job_resumed"
    SUBSCRIPTION_CHECKED = "subscription_checked"
    SUBSCRIPTION_FOUND_NEW = "subscription_found_new"
    SYSTEM_LOG = "system_log"


@dataclass
class AppEvent:
    event_type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """Thread-safe publish-subscribe event dispatcher."""

    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable[[AppEvent], None]]] = {
            t: [] for t in EventType
        }
        self._lock = threading.Lock()

    def subscribe(self, event_type: EventType, callback: Callable[[AppEvent], None]) -> None:
        """Register a listener for an event type."""
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            if callback not in self._subscribers[event_type]:
                self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: EventType, callback: Callable[[AppEvent], None]) -> None:
        """Unregister a listener."""
        with self._lock:
            if event_type in self._subscribers and callback in self._subscribers[event_type]:
                self._subscribers[event_type].remove(callback)

    def publish(self, event_type: EventType, data: Optional[Dict[str, Any]] = None) -> None:
        """Broadcast an event to all registered listeners safely."""
        event = AppEvent(event_type=event_type, data=data or {})
        with self._lock:
            listeners = list(self._subscribers.get(event_type, []))

        for listener in listeners:
            try:
                listener(event)
            except Exception:
                pass


# Global singleton event bus
BUS = EventBus()
