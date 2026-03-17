"""Integration tests for runtime EzSubscriber topic switching."""

from __future__ import annotations

from enum import Enum
from typing import cast

from qtpy import QtWidgets

from ezmsg.qt import EzGuiBridge
from ezmsg.qt import EzPublisher
from ezmsg.qt import EzSubscriber


class DemoTopic(Enum):
    A = "A"
    B = "B"
    C = "C"


def _app() -> QtWidgets.QApplication:
    return cast(
        QtWidgets.QApplication,
        QtWidgets.QApplication.instance() or QtWidgets.QApplication([]),
    )


def test_set_topic_switches_delivery(qtbot):
    app = _app()
    bridge = EzGuiBridge(app)
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    received: list[str] = []
    sub = EzSubscriber(DemoTopic.A, parent=widget, bridge=bridge)
    sub.connect(received.append)
    pub_a = EzPublisher(DemoTopic.A, parent=widget, bridge=bridge)
    pub_b = EzPublisher(DemoTopic.B, parent=widget, bridge=bridge)

    with bridge:
        pub_a.emit("a0")
        qtbot.waitUntil(lambda: received == ["a0"], timeout=2000)

        sub.set_topic(DemoTopic.B)
        assert sub.topic == DemoTopic.B

        pub_a.emit("a1")
        pub_b.emit("b0")
        qtbot.waitUntil(lambda: received[-1:] == ["b0"], timeout=2000)
        qtbot.wait(200)

    assert received == ["a0", "b0"]


def test_clear_topic_stops_delivery(qtbot):
    app = _app()
    bridge = EzGuiBridge(app)
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    received: list[str] = []
    sub = EzSubscriber(DemoTopic.A, parent=widget, bridge=bridge)
    sub.connect(received.append)
    pub_a = EzPublisher(DemoTopic.A, parent=widget, bridge=bridge)

    with bridge:
        pub_a.emit("a0")
        qtbot.waitUntil(lambda: received == ["a0"], timeout=2000)

        sub.clear_topic()
        assert sub.topic is None

        pub_a.emit("a1")
        qtbot.wait(200)

    assert received == ["a0"]


def test_switch_suppresses_queued_stale_messages(qtbot):
    app = _app()
    bridge = EzGuiBridge(app)
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    received: list[str] = []
    sub = EzSubscriber(DemoTopic.A, parent=widget, bridge=bridge)
    sub.connect(received.append)
    pub_a = EzPublisher(DemoTopic.A, parent=widget, bridge=bridge)
    pub_b = EzPublisher(DemoTopic.B, parent=widget, bridge=bridge)

    with bridge:
        pub_a.emit("stale")
        sub.set_topic(DemoTopic.B)
        pub_b.emit("fresh")

        qtbot.waitUntil(lambda: received[-1:] == ["fresh"], timeout=2000)
        qtbot.wait(200)

    assert "fresh" in received
    assert "stale" not in received


def test_switch_does_not_leak_subscriber_clients(qtbot):
    app = _app()
    bridge = EzGuiBridge(app)
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    sub = EzSubscriber(DemoTopic.A, parent=widget, bridge=bridge)

    with bridge:
        initial_clients = len(bridge._context._clients)

        sub.set_topic(DemoTopic.B)
        sub.set_topic(DemoTopic.C)

        assert len(bridge._context._clients) == initial_clients


def test_attach_after_start_supports_switching(qtbot):
    app = _app()
    bridge = EzGuiBridge(app)
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    received: list[str] = []

    with bridge:
        sub = EzSubscriber(None, parent=widget, bridge=bridge)
        sub.connect(received.append)
        pub_c = EzPublisher(DemoTopic.C, parent=widget, bridge=bridge)

        sub.set_topic(DemoTopic.C)
        assert sub.topic == DemoTopic.C

        pub_c.emit("c0")
        qtbot.waitUntil(lambda: received == ["c0"], timeout=2000)
