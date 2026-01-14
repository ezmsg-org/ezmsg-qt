#!/usr/bin/env python3
"""
Processor Chain Demo

Demonstrates the fluent .process() API for chaining processors
with optional process isolation.
"""

import sys
from enum import Enum
from typing import AsyncGenerator

import ezmsg.core as ez
from ezmsg.core.backend import GraphRunner
from qtpy import QtWidgets

from ezmsg.qt import EzGuiBridge, EzSubscriber, EzPublisher


class DemoTopic(Enum):
    NUMBERS = "NUMBERS"


class DoubleProcessor(ez.Unit):
    """Doubles input values."""

    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        print(f"DoubleProcessor: {msg} -> {msg * 2}")
        yield self.OUTPUT, msg * 2


class SquareProcessor(ez.Unit):
    """Squares input values."""

    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        print(f"SquareProcessor: {msg} -> {msg ** 2}")
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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Processor Chain Demo")

        layout = QtWidgets.QVBoxLayout(self)

        # Result display
        self.result_label = QtWidgets.QLabel("Waiting for data...")
        layout.addWidget(self.result_label)

        # Subscribe with processor chain
        # Chain: NUMBERS -> Double (sidecar) -> Square (bridge) -> display
        self.sub = EzSubscriber(DemoTopic.NUMBERS, parent=self)
        chain = self.sub.process(DoubleProcessor, in_process=True)
        chain.process(SquareProcessor, in_process=False)
        chain.connect(self.on_result)

    def on_result(self, value: float):
        self.result_label.setText(f"Result: {value:.2f}")
        print(f"Widget received: {value}")


def main():
    app = QtWidgets.QApplication(sys.argv)

    # Create and start the number generator graph
    generator = NumberGenerator()
    runner = GraphRunner(
        components={"gen": generator},
        connections=[
            (generator.OUTPUT, str(DemoTopic.NUMBERS)),
        ],
    )
    runner.start()

    # Create widget
    widget = DemoWidget()
    widget.show()

    try:
        with EzGuiBridge(app, graph_address=runner.graph_address):
            app.exec()
    finally:
        runner.stop()


if __name__ == "__main__":
    main()
