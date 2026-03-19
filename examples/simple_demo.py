"""
Simple demo of ezmsg-qt integration.

This example demonstrates:
1. A simple ezmsg processing unit that doubles numbers
2. A Qt widget that publishes numbers and receives results
3. The EzSession connecting them together
"""

import os
import sys
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from enum import auto
from enum import Enum

import ezmsg.core as ez
from ezmsg.core.backend import GraphRunner
from qtpy import QtCore
from qtpy import QtWidgets

from ezmsg.qt import EzPublisher
from ezmsg.qt import EzSession
from ezmsg.qt import EzSubscriber


# --- Topics ---
class DemoTopic(Enum):
    """Topics for the demo - defined alongside the processing unit."""

    INPUT = auto()
    OUTPUT = auto()


# --- Messages ---
@dataclass
class NumberMessage:
    value: float


# --- Processing Unit ---
class DoublerSettings(ez.Settings):
    pass


class Doubler(ez.Unit):
    """Simple processing unit that doubles incoming numbers."""

    SETTINGS = DoublerSettings

    INPUT = ez.InputStream(NumberMessage)
    OUTPUT = ez.OutputStream(NumberMessage)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def on_input(self, msg: NumberMessage) -> AsyncGenerator:
        result = NumberMessage(value=msg.value * 2)
        yield self.OUTPUT, result


# --- Qt Widget ---
class DemoWidget(QtWidgets.QWidget):
    """Widget that sends numbers and displays doubled results."""

    def __init__(self, session: EzSession, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ezmsg-qt Demo")

        # Create UI
        layout = QtWidgets.QVBoxLayout(self)

        # Input section
        input_layout = QtWidgets.QHBoxLayout()
        self.spin = QtWidgets.QSpinBox()
        self.spin.setRange(0, 100)
        self.spin.setValue(5)
        self.send_btn = QtWidgets.QPushButton("Send")
        input_layout.addWidget(QtWidgets.QLabel("Value:"))
        input_layout.addWidget(self.spin)
        input_layout.addWidget(self.send_btn)
        layout.addLayout(input_layout)

        # Output section
        self.result_label = QtWidgets.QLabel("Result: (waiting...)")
        self.result_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(self.result_label)

        # Log section
        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        layout.addWidget(self.log)

        # Create ezmsg connections
        self.number_pub = EzPublisher(DemoTopic.INPUT, parent=self, session=session)
        self.result_sub = EzSubscriber(DemoTopic.OUTPUT, parent=self, session=session)

        # Connect signals
        self.send_btn.clicked.connect(self.on_send)
        self.result_sub.connect(self.on_result)

        self._log("Widget initialized")

    def on_send(self):
        value = self.spin.value()
        msg = NumberMessage(value=value)
        self._log(f"Sending: {value}")
        self.number_pub.emit(msg)

    def on_result(self, msg: NumberMessage):
        self._log(f"Received: {msg.value}")
        self.result_label.setText(f"Result: {msg.value}")

    def _log(self, text: str):
        self.log.append(text)


# --- ezmsg System ---
class DemoSystemSettings(ez.Settings):
    pass


class DemoSystem(ez.Collection):
    """The ezmsg processing graph."""

    SETTINGS = DemoSystemSettings
    DOUBLER = Doubler()

    def configure(self) -> None:
        self.DOUBLER.apply_settings(DoublerSettings())

    def network(self) -> ez.NetworkDefinition:
        return (  # pyright: ignore[reportReturnType]
            (DemoTopic.INPUT, self.DOUBLER.INPUT),
            (self.DOUBLER.OUTPUT, DemoTopic.OUTPUT),
        )


# --- Main ---
def main():
    app = QtWidgets.QApplication(sys.argv)

    runner = GraphRunner(components={"DEMO": DemoSystem()})
    runner.start()
    session = EzSession(graph_address=runner.graph_address)

    widget = DemoWidget(session)
    widget.resize(400, 300)
    widget.show()

    time.sleep(1.0)

    with session:
        auto_close_ms = os.getenv("EZMSG_QT_DEMO_AUTOCLOSE_MS")
        if auto_close_ms is not None:
            QtCore.QTimer.singleShot(int(auto_close_ms), app.quit)

        # Auto-send a test message after a short delay
        def auto_test():
            widget.spin.setValue(42)
            widget.on_send()

        QtCore.QTimer.singleShot(2000, auto_test)  # Send after 2 seconds
        app.exec()

    if runner.running:
        runner.stop()


if __name__ == "__main__":
    main()
