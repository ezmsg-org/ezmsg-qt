"""Tests for EzDynamicSubscriber."""

import pytest


@pytest.fixture(autouse=True)
def _reset_bridge_globals():
    """Reset module-level globals between tests."""
    from ezmsg.qt import bridge

    old_active = bridge._active_bridge
    old_pending = bridge._pending_dynamic.copy()
    yield
    bridge._active_bridge = old_active
    bridge._pending_dynamic[:] = old_pending


def test_creation_before_bridge(qtbot):
    """EzDynamicSubscriber can be created before the bridge starts."""
    from ezmsg.qt import bridge
    from ezmsg.qt.dynamic import EzDynamicSubscriber

    bridge._active_bridge = None
    bridge._pending_dynamic.clear()

    dyn = EzDynamicSubscriber()

    assert dyn.topic is None
    assert dyn in bridge._pending_dynamic


def test_subscribe_stores_topic(qtbot):
    """subscribe() stores the topic even without an active bridge."""
    from ezmsg.qt import bridge
    from ezmsg.qt.dynamic import EzDynamicSubscriber

    bridge._active_bridge = None
    bridge._pending_dynamic.clear()

    dyn = EzDynamicSubscriber()

    dyn.subscribe("some/topic")
    assert dyn.topic == "some/topic"

    dyn.subscribe("other/topic")
    assert dyn.topic == "other/topic"


def test_on_message_emits_received(qtbot):
    """_on_message slot emits the received signal."""
    from ezmsg.qt import bridge
    from ezmsg.qt.dynamic import EzDynamicSubscriber

    bridge._active_bridge = None
    bridge._pending_dynamic.clear()

    dyn = EzDynamicSubscriber()

    received = []
    dyn.connect(received.append)

    dyn._on_message("hello")
    assert received == ["hello"]


def test_connect_slot(qtbot):
    """connect() wires up the received signal to the given slot."""
    from ezmsg.qt import bridge
    from ezmsg.qt.dynamic import EzDynamicSubscriber

    bridge._active_bridge = None
    bridge._pending_dynamic.clear()

    dyn = EzDynamicSubscriber()

    results = []
    dyn.connect(results.append)

    # Simulate message delivery
    dyn.received.emit(42)
    assert results == [42]

    dyn.received.emit("data")
    assert results == [42, "data"]


@pytest.mark.skip(reason="Requires running GraphServer - manual test")
def test_subscribe_delivers_messages(qtbot):
    """subscribe(topic) delivers messages from the specified topic."""
    from qtpy import QtWidgets

    from ezmsg.qt import EzDynamicSubscriber, EzGuiBridge

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    results = []
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    dyn = EzDynamicSubscriber(parent=widget)
    dyn.connect(results.append)

    with EzGuiBridge(app):
        dyn.subscribe("test/topic")
        qtbot.wait(1000)

    # Would need a publisher to actually deliver messages


@pytest.mark.skip(reason="Requires running GraphServer - manual test")
def test_subscribe_switches_topic(qtbot):
    """Calling subscribe(new_topic) switches delivery to the new topic."""
    from qtpy import QtWidgets

    from ezmsg.qt import EzDynamicSubscriber, EzGuiBridge

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    results = []
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    dyn = EzDynamicSubscriber(parent=widget)
    dyn.connect(results.append)

    with EzGuiBridge(app):
        dyn.subscribe("topic/a")
        qtbot.wait(500)

        dyn.subscribe("topic/b")
        qtbot.wait(500)

    # Would need publishers on both topics to verify switch


@pytest.mark.skip(reason="Requires running GraphServer - manual test")
def test_rapid_switches_no_errors(qtbot):
    """Multiple rapid subscribe() calls don't cause errors."""
    from qtpy import QtWidgets

    from ezmsg.qt import EzDynamicSubscriber, EzGuiBridge

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    dyn = EzDynamicSubscriber(parent=widget)

    with EzGuiBridge(app):
        for i in range(10):
            dyn.subscribe(f"topic/{i}")
        qtbot.wait(1000)
