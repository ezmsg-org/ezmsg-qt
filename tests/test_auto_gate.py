"""Tests for auto-gating integration."""

from enum import Enum
from typing import AsyncGenerator

import ezmsg.core as ez
from qtpy import QtWidgets

from ezmsg.qt.session import EzSession
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


def test_session_sets_up_visibility_filter(qtbot):
    """Session installs visibility filter for auto_gate chains."""
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    session = EzSession()

    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    # Create processor chain with widget as parent
    chain = (
        ProcessorChain(DemoTopic.DATA, parent=widget, auto_gate=True)
        .parallel(PassthroughProcessor)
        .connect(lambda x: None)
        .attach(session)
    )

    # Chain should have parent widget set
    assert chain.parent_widget is widget
    assert chain.auto_gate is True
    assert chain.session is session
