"""Tests for visibility-based auto-gating."""

from qtpy import QtWidgets

from ezmsg.qt.visibility import VisibilityFilter


def test_visibility_filter_creation(qtbot):
    """VisibilityFilter can be created."""
    callback = lambda visible: None
    vf = VisibilityFilter(callback)
    assert vf is not None


def test_visibility_filter_detects_show(qtbot):
    """VisibilityFilter calls callback when widget shown."""
    visible_states = []

    def on_visibility(visible: bool):
        visible_states.append(visible)

    widget = QtWidgets.QWidget()
    vf = VisibilityFilter(on_visibility)
    widget.installEventFilter(vf)

    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)

    assert True in visible_states


def test_visibility_filter_detects_hide(qtbot):
    """VisibilityFilter calls callback when widget hidden."""
    visible_states = []

    def on_visibility(visible: bool):
        visible_states.append(visible)

    widget = QtWidgets.QWidget()
    vf = VisibilityFilter(on_visibility)
    widget.installEventFilter(vf)

    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    widget.hide()

    assert False in visible_states
