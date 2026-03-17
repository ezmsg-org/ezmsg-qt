"""Tests for explicit endpoint ownership."""

from enum import Enum
from typing import cast

import pytest
from qtpy import QtWidgets

from ezmsg.qt import EzGuiBridge
from ezmsg.qt import EzPublisher
from ezmsg.qt import EzSubscriber
from ezmsg.qt.sidecar import normalize_topic


class DemoTopic(Enum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"


def _app() -> QtWidgets.QApplication:
    return cast(
        QtWidgets.QApplication,
        QtWidgets.QApplication.instance() or QtWidgets.QApplication([]),
    )


def test_normalize_topic_uses_enum_name():
    assert normalize_topic(DemoTopic.INPUT) == "INPUT"
    assert normalize_topic("custom") == "custom"


def test_endpoints_attach_to_bridge(qtbot):
    app = _app()
    bridge = EzGuiBridge(app)
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    sub = EzSubscriber(DemoTopic.INPUT, parent=widget, bridge=bridge)
    pub = EzPublisher(DemoTopic.INPUT, parent=widget, bridge=bridge)

    assert sub.bridge is bridge
    assert pub.bridge is bridge


def test_subscriber_preserves_initial_topic_before_bridge_start(qtbot):
    app = _app()
    bridge = EzGuiBridge(app)
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    sub = EzSubscriber(DemoTopic.INPUT, parent=widget, bridge=bridge)

    assert sub.topic == DemoTopic.INPUT


def test_subscriber_switch_requires_running_bridge(qtbot):
    app = _app()
    bridge = EzGuiBridge(app)
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    sub = EzSubscriber(DemoTopic.INPUT, parent=widget, bridge=bridge)

    with pytest.raises(RuntimeError):
        sub.set_topic(DemoTopic.OUTPUT)

    with pytest.raises(RuntimeError):
        sub.clear_topic()

    assert sub.topic == DemoTopic.INPUT
