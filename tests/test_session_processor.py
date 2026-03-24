"""Tests for processor graph attachment."""

from collections.abc import AsyncGenerator
from enum import Enum

import ezmsg.core as ez
from qtpy import QtWidgets

from ezmsg.qt.chain import ProcessorGraph
from ezmsg.qt.session import EzSession


class DemoTopic(Enum):
    INPUT = "INPUT"


class DoubleProcessor(ez.Unit):
    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg * 2


def test_session_registers_graphs(qtbot):
    """EzSession attaches fully configured graphs explicitly."""
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    session = EzSession()

    received = []
    graph = (
        ProcessorGraph(DemoTopic.INPUT, parent=None)
        .local(DoubleProcessor)
        .connect(received.append)
        .attach(session)
    )

    assert graph.session is session
    assert graph.attached is True
