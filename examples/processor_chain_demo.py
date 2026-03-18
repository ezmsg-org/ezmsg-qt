#!/usr/bin/env python3
"""
Processor Chain Demo

Demonstrates compiled processor pipelines with shared and isolated
sidecar execution stages.
"""

import sys
from enum import Enum
import os
from typing import AsyncGenerator

import ezmsg.core as ez
from ezmsg.core.backend import GraphRunner
from qtpy import QtCore
from qtpy import QtWidgets

from ezmsg.qt import EzSession, ProcessorChain


class DemoTopic(Enum):
    NUMBERS = "NUMBERS"


class DoubleProcessor(ez.Unit):
    """Doubles input values."""

    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg * 2


class SquareProcessor(ez.Unit):
    """Squares input values."""

    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg**2


class NumberGenerator(ez.Unit):
    """Generates sequential numbers."""

    OUTPUT = ez.OutputStream(float)

    @ez.publisher(OUTPUT)
    async def generate(self) -> AsyncGenerator:
        import asyncio

        count = 1.0
        while True:
            yield self.OUTPUT, count
            count += 1
            await asyncio.sleep(1.0)


class DemoWidget(QtWidgets.QWidget):
    def __init__(self, session: EzSession):
        super().__init__()
        self.setWindowTitle("Processor Chain Demo")

        layout = QtWidgets.QVBoxLayout(self)

        # Result display
        self.result_label = QtWidgets.QLabel("Waiting for data...")
        layout.addWidget(self.result_label)

        self.chain = (
            ProcessorChain(DemoTopic.NUMBERS, parent=self)
            .parallel(DoubleProcessor)
            .local(SquareProcessor)
            .connect(self.on_result)
            .attach(session)
        )

    def on_result(self, value: float):
        self.result_label.setText(f"Result: {value:.2f}")


def main():
    app = QtWidgets.QApplication(sys.argv)

    # Create and start the number generator graph
    generator = NumberGenerator()
    runner = GraphRunner(
        components={"gen": generator},
        connections=[
            (generator.OUTPUT, DemoTopic.NUMBERS.name),
        ],
    )
    runner.start()

    session = EzSession(graph_address=runner.graph_address)

    # Create widget
    widget = DemoWidget(session)
    widget.show()

    try:
        with session:
            auto_close_ms = os.getenv("EZMSG_QT_DEMO_AUTOCLOSE_MS")
            if auto_close_ms is not None:
                QtCore.QTimer.singleShot(int(auto_close_ms), app.quit)
            app.exec()
    finally:
        runner.stop()


if __name__ == "__main__":
    main()
