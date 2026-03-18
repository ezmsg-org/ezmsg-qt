"""Integration tests for runtime EzPublisher topic switching."""

from __future__ import annotations

from enum import Enum
from typing import cast

from qtpy import QtWidgets

from ezmsg.qt import EzPublisher
from ezmsg.qt import EzSession
from ezmsg.qt import EzSubscriber


class DemoTopic(Enum):
    A = "A"
    B = "B"


def _app() -> QtWidgets.QApplication:
    return cast(
        QtWidgets.QApplication,
        QtWidgets.QApplication.instance() or QtWidgets.QApplication([]),
    )


def test_publisher_switches_delivery(qtbot):
    _app()
    session = EzSession()
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    received_a: list[str] = []
    received_b: list[str] = []
    pub = EzPublisher(DemoTopic.A, parent=widget, session=session)
    sub_a = EzSubscriber(DemoTopic.A, parent=widget, session=session)
    sub_b = EzSubscriber(DemoTopic.B, parent=widget, session=session)
    sub_a.connect(received_a.append)
    sub_b.connect(received_b.append)

    with session:
        pub.emit("a0")
        qtbot.waitUntil(lambda: received_a == ["a0"], timeout=2000)

        pub.set_topic(DemoTopic.B)
        assert pub.topic == DemoTopic.B

        pub.emit("b0")
        qtbot.waitUntil(lambda: received_b == ["b0"], timeout=2000)
        qtbot.wait(200)

    assert received_a == ["a0"]
    assert received_b == ["b0"]


def test_publisher_clear_topic_blocks_emit(qtbot):
    _app()
    session = EzSession()
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    pub = EzPublisher(DemoTopic.A, parent=widget, session=session)

    with session:
        pub.clear_topic()
        assert pub.topic is None

        try:
            pub.emit("nope")
        except RuntimeError:
            pass
        else:
            raise AssertionError("Expected emit() to fail with no active topic")


def test_publisher_switch_signals_emit_in_order(qtbot):
    _app()
    session = EzSession()
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    pub = EzPublisher(DemoTopic.A, parent=widget, session=session)
    events: list[tuple[str, object | None]] = []
    pub.switch_started.connect(lambda topic: events.append(("started", topic)))
    pub.topic_changed.connect(lambda topic: events.append(("changed", topic)))
    pub.topic_cleared.connect(lambda: events.append(("cleared", None)))

    with session:
        pub.set_topic(DemoTopic.B)
        pub.clear_topic()

    assert events == [
        ("started", DemoTopic.B),
        ("changed", DemoTopic.B),
        ("started", None),
        ("cleared", None),
    ]
