"""Integration tests for processor graphs."""

from collections.abc import AsyncGenerator
from enum import Enum

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


class HalfProcessor(ez.Unit):
    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg / 2.0


def _run_graph(qtbot, graph_builder, expected: list[float]) -> list[float]:
    from qtpy import QtWidgets

    from ezmsg.qt import EzPublisher
    from ezmsg.qt import EzSession

    _ = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    session = EzSession()

    results: list[float] = []
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    pub = EzPublisher(DemoTopic.INPUT, parent=widget, session=session)
    graph_builder(widget, session, results)

    with session:
        qtbot.wait(250)
        for value in [5.0, 10.0]:
            pub.emit(value)
        qtbot.waitUntil(
            lambda: all(result in results for result in expected), timeout=2000
        )

    return results


def test_local_graph_integration(qtbot):
    from ezmsg.qt import ProcessorGraph

    results = _run_graph(
        qtbot,
        lambda widget, session, results: (
            ProcessorGraph(DemoTopic.INPUT, parent=widget, auto_gate=False)
            .local(AddOneProcessor)
            .connect(results.append)
            .attach(session)
        ),
        [6.0, 11.0],
    )

    assert 6.0 in results
    assert 11.0 in results


def test_parallel_graph_integration(qtbot):
    from ezmsg.qt import ProcessorGraph

    results = _run_graph(
        qtbot,
        lambda widget, session, results: (
            ProcessorGraph(DemoTopic.INPUT, parent=widget, auto_gate=False)
            .parallel(DoubleProcessor)
            .connect(results.append)
            .attach(session)
        ),
        [10.0, 20.0],
    )

    assert 10.0 in results
    assert 20.0 in results


def test_mixed_graph_integration(qtbot):
    from ezmsg.qt import ProcessorGraph

    results = _run_graph(
        qtbot,
        lambda widget, session, results: (
            ProcessorGraph(DemoTopic.INPUT, parent=widget, auto_gate=False)
            .parallel(DoubleProcessor)
            .local(AddOneProcessor)
            .connect(results.append)
            .attach(session)
        ),
        [11.0, 21.0],
    )

    assert 11.0 in results
    assert 21.0 in results


def test_branch_graph_integration(qtbot):
    from qtpy import QtWidgets

    from ezmsg.qt import EzPublisher
    from ezmsg.qt import EzSession
    from ezmsg.qt import ProcessorGraph

    _ = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    session = EzSession()
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)

    main_results: list[float] = []
    branch_results: list[float] = []

    pub = EzPublisher(DemoTopic.INPUT, parent=widget, session=session)
    (
        ProcessorGraph(DemoTopic.INPUT, parent=widget, auto_gate=False)
        .local(DoubleProcessor)
        .connect(main_results.append)
        .branch(lambda path: path.local(HalfProcessor).connect(branch_results.append))
        .attach(session)
    )

    with session:
        qtbot.wait(250)
        pub.emit(8.0)
        qtbot.waitUntil(lambda: main_results == [16.0], timeout=2000)
        qtbot.waitUntil(lambda: branch_results == [8.0], timeout=2000)
