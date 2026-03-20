"""Tests for explicit endpoint ownership."""

from enum import Enum
from typing import cast

import pytest
from qtpy import QtCore
from qtpy import QtWidgets

from ezmsg.qt import EzPublisher
from ezmsg.qt import EzSession
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


def test_endpoints_attach_to_session(qtbot):
    session = EzSession()
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    sub = EzSubscriber(DemoTopic.INPUT, parent=widget, session=session)
    pub = EzPublisher(DemoTopic.INPUT, parent=widget, session=session)

    assert sub.session is session
    assert pub.session is session


def test_subscriber_preserves_initial_topic_before_session_start(qtbot):
    session = EzSession()
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    sub = EzSubscriber(DemoTopic.INPUT, parent=widget, session=session)

    assert sub.topic == DemoTopic.INPUT


def test_subscriber_switch_requires_running_session(qtbot):
    session = EzSession()
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    sub = EzSubscriber(DemoTopic.INPUT, parent=widget, session=session)

    with pytest.raises(RuntimeError):
        sub.set_topic(DemoTopic.OUTPUT)

    with pytest.raises(RuntimeError):
        sub.clear_topic()

    assert sub.topic == DemoTopic.INPUT


def test_subscriber_auto_gate_requires_widget_parent():
    parent = QtCore.QObject()

    with pytest.raises(TypeError, match="QWidget parent"):
        EzSubscriber(DemoTopic.INPUT, parent=parent, auto_gate=True)


def test_subscriber_auto_gate_requires_widget_at_runtime(qtbot):
    session = EzSession()
    EzSubscriber(DemoTopic.INPUT, auto_gate=True, session=session)

    with pytest.raises(RuntimeError, match="EzSession setup failed") as excinfo:
        with session:
            qtbot.wait(10)

    assert isinstance(excinfo.value.__cause__, TypeError)
    assert "QWidget parent" in str(excinfo.value.__cause__)


def test_publisher_switch_requires_running_session(qtbot):
    session = EzSession()
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    pub = EzPublisher(DemoTopic.INPUT, parent=widget, session=session)

    with pytest.raises(RuntimeError):
        pub.set_topic(DemoTopic.OUTPUT)

    with pytest.raises(RuntimeError):
        pub.clear_topic()

    assert pub.topic == DemoTopic.INPUT
