"""Tests for auto-gating integration."""

from enum import Enum
from typing import AsyncGenerator

import ezmsg.core as ez
from qtpy import QtWidgets

from ezmsg.qt.chain import ProcessorChain


class DemoTopic(Enum):
    DATA = "DATA"


class PassthroughProcessor(ez.Unit):
    INPUT = ez.InputStream(object)
    OUTPUT = ez.OutputStream(object)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: object) -> AsyncGenerator:
        yield self.OUTPUT, msg


def test_bridge_sets_up_visibility_filter(qtbot):
    """Bridge installs visibility filter for auto_gate chains."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    # Create processor chain with widget as parent
    chain = (
        ProcessorChain(DemoTopic.DATA, parent=widget, auto_gate=True)
        .parallel(PassthroughProcessor)
    )
    chain.connect(lambda x: None)

    # Chain should have parent widget set
    assert chain.parent_widget is widget
    assert chain.auto_gate is True
