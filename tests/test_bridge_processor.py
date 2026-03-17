"""Tests for processor pipeline attachment."""

from enum import Enum
from typing import AsyncGenerator

import ezmsg.core as ez
from qtpy import QtWidgets

from ezmsg.qt.bridge import EzGuiBridge
from ezmsg.qt.chain import ProcessorChain


class DemoTopic(Enum):
    INPUT = "INPUT"


class DoubleProcessor(ez.Unit):
    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg * 2


def test_bridge_registers_chains(qtbot):
    """EzGuiBridge attaches fully configured pipelines explicitly."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    bridge = EzGuiBridge(app)

    received = []
    chain = (
        ProcessorChain(DemoTopic.INPUT, parent=None)
        .local(DoubleProcessor)
        .connect(received.append)
        .attach(bridge)
    )

    assert chain.bridge is bridge
    assert chain.attached is True
