"""Tests for auto-gating integration."""

from collections.abc import AsyncGenerator
from enum import Enum

import ezmsg.core as ez
from qtpy import QtWidgets

from ezmsg.qt.chain import ProcessorGraph
from ezmsg.qt.session import EzSession


class DemoTopic(Enum):
    DATA = "DATA"


class PassthroughProcessor(ez.Unit):
    INPUT = ez.InputStream(object)
    OUTPUT = ez.OutputStream(object)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: object) -> AsyncGenerator:
        yield self.OUTPUT, msg


def test_session_sets_up_visibility_filter(qtbot):
    """Session installs visibility filter for auto_gate graphs."""
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    session = EzSession()

    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    graph = (
        ProcessorGraph(DemoTopic.DATA, parent=widget, auto_gate=True)
        .parallel(PassthroughProcessor)
        .connect(lambda x: None)
        .attach(session)
    )

    assert graph.parent_widget is widget
    assert graph.auto_gate is True
    assert graph.session is session
