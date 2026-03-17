"""Integration tests for processor chains."""

import pytest
from enum import Enum
from typing import AsyncGenerator

import ezmsg.core as ez


class DemoTopic(Enum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"


class DoubleProcessor(ez.Unit):
    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg * 2


class AddOneProcessor(ez.Unit):
    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg + 1


@pytest.mark.skip(reason="Requires running GraphServer - manual test")
def test_full_chain_integration(qtbot):
    """Full integration test with sidecar processing."""
    from qtpy import QtWidgets
    from ezmsg.qt import EzGuiBridge, EzPublisher, ProcessorChain

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    bridge = EzGuiBridge(app)

    results = []

    # Create widgets
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    pub = EzPublisher(DemoTopic.INPUT, parent=widget, bridge=bridge)

    # Chain: double (isolated sidecar process) -> add one (shared sidecar process)
    ProcessorChain(DemoTopic.INPUT, parent=widget).parallel(DoubleProcessor).local(
        AddOneProcessor
    ).connect(results.append).attach(bridge)

    widget.show()

    with bridge:
        # Publish test values
        pub.emit(5.0)  # Expected: (5 * 2) + 1 = 11
        pub.emit(10.0)  # Expected: (10 * 2) + 1 = 21

        # Process events
        qtbot.wait(1000)

    assert 11.0 in results
    assert 21.0 in results
