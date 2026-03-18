"""Integration tests for processor chains."""

from enum import Enum
from typing import AsyncGenerator

import ezmsg.core as ez


class DemoTopic(Enum):
    INPUT = "INPUT"


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


def _run_chain(qtbot, chain_builder, expected: list[float]) -> list[float]:
    from qtpy import QtWidgets

    from ezmsg.qt import EzPublisher
    from ezmsg.qt import EzSession

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    session = EzSession()

    results: list[float] = []
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    pub = EzPublisher(DemoTopic.INPUT, parent=widget, session=session)
    chain_builder(widget, session, results)

    with session:
        qtbot.wait(250)
        for value in [5.0, 10.0]:
            pub.emit(value)
        qtbot.waitUntil(
            lambda: all(result in results for result in expected), timeout=2000
        )

    return results


def test_local_chain_integration(qtbot):
    from ezmsg.qt import ProcessorChain

    results = _run_chain(
        qtbot,
        lambda widget, session, results: ProcessorChain(
            DemoTopic.INPUT, parent=widget, auto_gate=False
        )
        .local(AddOneProcessor)
        .connect(results.append)
        .attach(session),
        [6.0, 11.0],
    )

    assert 6.0 in results
    assert 11.0 in results


def test_parallel_chain_integration(qtbot):
    from ezmsg.qt import ProcessorChain

    results = _run_chain(
        qtbot,
        lambda widget, session, results: ProcessorChain(
            DemoTopic.INPUT, parent=widget, auto_gate=False
        )
        .parallel(DoubleProcessor)
        .connect(results.append)
        .attach(session),
        [10.0, 20.0],
    )

    assert 10.0 in results
    assert 20.0 in results


def test_mixed_chain_integration(qtbot):
    from ezmsg.qt import ProcessorChain

    results = _run_chain(
        qtbot,
        lambda widget, session, results: ProcessorChain(
            DemoTopic.INPUT, parent=widget, auto_gate=False
        )
        .parallel(DoubleProcessor)
        .local(AddOneProcessor)
        .connect(results.append)
        .attach(session),
        [11.0, 21.0],
    )

    assert 11.0 in results
    assert 21.0 in results
