#!/usr/bin/env python3
"""
Processor Chain Showcase

Demonstrates all features of the processor chains API:
- Fluent .parallel() / .local() API for grouping processors
- .parallel() for running in sidecar (parallel processing)
- .local() for running in the shared sidecar process
- Auto-gating: processing stops when widget is hidden (e.g., tab not visible)
- Mixed chains with both parallel and local groups

"""

import sys
from collections.abc import AsyncGenerator
from enum import Enum
import os

import ezmsg.core as ez
from ezmsg.core.backend import GraphRunner
from qtpy import QtCore
from qtpy import QtWidgets

from ezmsg.qt import EzSession
from ezmsg.qt import EzSubscriber
from ezmsg.qt import ProcessorChain


class DataTopic(Enum):
    SENSOR_DATA = "SENSOR_DATA"


# ============================================================================
# Processors - These can be reused in different chain configurations
# ============================================================================


class LowPassFilter(ez.Unit):
    """Simple exponential moving average filter."""

    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    def __init__(self):
        super().__init__()
        self._ema = 0.0
        self._alpha = 0.3

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        self._ema = self._alpha * msg + (1 - self._alpha) * self._ema
        yield self.OUTPUT, self._ema


class ScaleProcessor(ez.Unit):
    """Scales values by a factor."""

    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg * 100  # Scale to percentage


class ThresholdDetector(ez.Unit):
    """Detects when value crosses a threshold."""

    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(str)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        if msg > 75:
            status = "HIGH"
        elif msg > 25:
            status = "NORMAL"
        else:
            status = "LOW"
        yield self.OUTPUT, f"{msg:.1f}% - {status}"


# ============================================================================
# Data Generator (simulates sensor input)
# ============================================================================


class SensorSimulator(ez.Unit):
    """Generates simulated sensor data with noise."""

    OUTPUT = ez.OutputStream(float)

    @ez.publisher(OUTPUT)
    async def generate(self) -> AsyncGenerator:
        import asyncio
        import math
        import random

        t = 0.0
        while True:
            # Sine wave with noise
            value = 0.5 + 0.4 * math.sin(t * 0.5) + random.uniform(-0.1, 0.1)
            value = max(0.0, min(1.0, value))  # Clamp to [0, 1]
            yield self.OUTPUT, value
            t += 0.1
            await asyncio.sleep(0.05)  # 20 Hz


# ============================================================================
# UI Components
# ============================================================================


class ProcessedDataWidget(QtWidgets.QWidget):
    """Widget showing processed sensor data with auto-gating."""

    def __init__(self, session: EzSession, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)

        # Title
        title = QtWidgets.QLabel("<b>Processed Sensor Data</b>")
        layout.addWidget(title)

        # Description
        desc = QtWidgets.QLabel(
            "Chain: Raw → LowPass (parallel) → Scale (parallel) → Threshold (local)\n"
            "Processing STOPS when this tab is hidden (auto-gating)"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Result display
        self.result_label = QtWidgets.QLabel("Waiting for data...")
        self.result_label.setStyleSheet(
            "font-size: 24px; padding: 20px; "
            "background-color: #f0f0f0; border-radius: 5px;"
        )
        layout.addWidget(self.result_label)

        # Counter
        self.count_label = QtWidgets.QLabel("Messages received: 0")
        layout.addWidget(self.count_label)
        self.message_count = 0

        layout.addStretch()

        # Set up processor chain with auto-gating
        # When this widget is hidden (tab switched), processing stops
        self.chain = (
            ProcessorChain(DataTopic.SENSOR_DATA, parent=self)
            .parallel(LowPassFilter, ScaleProcessor)  # Sidecar (grouped)
            .local(ThresholdDetector)
            .connect(self.on_data)
            .attach(session)
        )

    def on_data(self, status: str):
        self.result_label.setText(status)
        self.message_count += 1
        self.count_label.setText(f"Messages received: {self.message_count}")

        # Color based on status
        if "HIGH" in status:
            self.result_label.setStyleSheet(
                "font-size: 24px; padding: 20px; "
                "background-color: #ffcccc; border-radius: 5px;"
            )
        elif "LOW" in status:
            self.result_label.setStyleSheet(
                "font-size: 24px; padding: 20px; "
                "background-color: #ccccff; border-radius: 5px;"
            )
        else:
            self.result_label.setStyleSheet(
                "font-size: 24px; padding: 20px; "
                "background-color: #ccffcc; border-radius: 5px;"
            )


class RawDataWidget(QtWidgets.QWidget):
    """Widget showing raw sensor data (no processing)."""

    def __init__(self, session: EzSession, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)

        title = QtWidgets.QLabel("<b>Raw Sensor Data</b>")
        layout.addWidget(title)

        desc = QtWidgets.QLabel("Direct subscription - no processor chain")
        layout.addWidget(desc)

        self.result_label = QtWidgets.QLabel("Waiting for data...")
        self.result_label.setStyleSheet(
            "font-size: 24px; padding: 20px; "
            "background-color: #f0f0f0; border-radius: 5px;"
        )
        layout.addWidget(self.result_label)

        self.count_label = QtWidgets.QLabel("Messages received: 0")
        layout.addWidget(self.count_label)
        self.message_count = 0

        layout.addStretch()

        # Direct subscription without processor chain
        self.sub = EzSubscriber(DataTopic.SENSOR_DATA, parent=self, session=session)
        self.sub.connect(self.on_data)

    def on_data(self, value: float):
        self.result_label.setText(f"Raw: {value:.4f}")
        self.message_count += 1
        self.count_label.setText(f"Messages received: {self.message_count}")


class MainWindow(QtWidgets.QMainWindow):
    """Main window with tabbed interface to demonstrate auto-gating."""

    def __init__(self, session: EzSession):
        super().__init__()
        self.setWindowTitle("Processor Chains Showcase")
        self.setMinimumSize(500, 400)

        # Create tab widget
        tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(tabs)

        # Add tabs
        tabs.addTab(ProcessedDataWidget(session), "Processed (Auto-Gated)")
        tabs.addTab(RawDataWidget(session), "Raw Data")

        # Instructions
        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.showMessage(
                "Switch tabs to see auto-gating in action - "
                "processed data stops updating when tab is hidden"
            )


def main():
    app = QtWidgets.QApplication(sys.argv)

    # Create and start the sensor simulator
    simulator = SensorSimulator()
    runner = GraphRunner(
        components={"sensor": simulator},
        connections=[
            (simulator.OUTPUT, DataTopic.SENSOR_DATA.name),
        ],
    )
    runner.start()

    session = EzSession(graph_address=runner.graph_address)

    # Create main window
    window = MainWindow(session)
    window.show()

    try:
        with session:
            auto_close_ms = os.getenv("EZMSG_QT_DEMO_AUTOCLOSE_MS")
            if auto_close_ms is not None:
                QtCore.QTimer.singleShot(int(auto_close_ms), app.quit)
            print("[Main] Bridge active, starting Qt event loop...", flush=True)
            app.exec()
            print("[Main] Qt event loop exited, calling app.quit()...", flush=True)
            app.quit()
        print("[Main] Bridge context exited", flush=True)
    finally:
        print("[Main] Finally block...", flush=True)
        if runner.running:
            print("[Main] Stopping runner...", flush=True)
            runner.stop()
            print("[Main] Runner stopped", flush=True)
        else:
            print("[Main] Runner already stopped", flush=True)
    print("[Main] main() complete", flush=True)


if __name__ == "__main__":
    main()
