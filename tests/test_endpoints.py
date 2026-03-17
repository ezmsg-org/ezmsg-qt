"""Tests for explicit endpoint ownership."""

from enum import Enum

from qtpy import QtWidgets

from ezmsg.qt import EzGuiBridge
from ezmsg.qt import EzPublisher
from ezmsg.qt import EzSubscriber
from ezmsg.qt.sidecar import normalize_topic


class DemoTopic(Enum):
    INPUT = "INPUT"


def test_normalize_topic_uses_enum_name():
    assert normalize_topic(DemoTopic.INPUT) == "INPUT"
    assert normalize_topic("custom") == "custom"


def test_endpoints_attach_to_bridge(qtbot):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    bridge = EzGuiBridge(app)
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    sub = EzSubscriber(DemoTopic.INPUT, parent=widget, bridge=bridge)
    pub = EzPublisher(DemoTopic.INPUT, parent=widget, bridge=bridge)

    assert sub.bridge is bridge
    assert pub.bridge is bridge
