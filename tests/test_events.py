"""Tests for EventBus PubSub system."""

from ytdlp_workstation.core.events import EventBus, EventType, AppEvent


def test_event_bus_subscribe_and_publish():
    bus = EventBus()
    received_events = []

    def on_job_started(event: AppEvent):
        received_events.append(event)

    bus.subscribe(EventType.JOB_STARTED, on_job_started)
    bus.publish(EventType.JOB_STARTED, {"job_id": "job_123", "url": "https://test.com"})

    assert len(received_events) == 1
    assert received_events[0].event_type == EventType.JOB_STARTED
    assert received_events[0].data["job_id"] == "job_123"


def test_event_bus_unsubscribe():
    bus = EventBus()
    received = []

    def handler(event: AppEvent):
        received.append(event)

    bus.subscribe(EventType.JOB_FINISHED, handler)
    bus.publish(EventType.JOB_FINISHED, {"status": "ok"})
    assert len(received) == 1

    bus.unsubscribe(EventType.JOB_FINISHED, handler)
    bus.publish(EventType.JOB_FINISHED, {"status": "second"})
    # Should not receive event after unsubscribe
    assert len(received) == 1


def test_event_bus_listener_exception_isolation():
    bus = EventBus()
    successful_calls = []

    def buggy_listener(event: AppEvent):
        raise ValueError("Listener failed")

    def good_listener(event: AppEvent):
        successful_calls.append(event)

    bus.subscribe(EventType.JOB_FAILED, buggy_listener)
    bus.subscribe(EventType.JOB_FAILED, good_listener)

    # Buggy listener should not prevent good listener from executing
    bus.publish(EventType.JOB_FAILED, {"error": "test"})
    assert len(successful_calls) == 1
