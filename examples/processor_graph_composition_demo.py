#!/usr/bin/env python3
"""Demonstrate ProcessorGraph composition with reusable recipes and branches."""

from __future__ import annotations

import math
import os
import sys
from collections import deque
from collections.abc import AsyncGenerator
from enum import Enum

import ezmsg.core as ez
from qtpy import QtCore
from qtpy import QtWidgets

from ezmsg.qt import BoundProcessor
from ezmsg.qt import EzPublisher
from ezmsg.qt import EzSession
from ezmsg.qt import ProcessorGraph
from ezmsg.qt import ProcessorSettingsPanel


class DemoTopic(Enum):
    SAMPLES = "SAMPLES"


class GainSettings(ez.Settings):
    factor: float = 1.5
    bias: float = 0.0


class RollingAverageSettings(ez.Settings):
    window: int = 5


class AlertSettings(ez.Settings):
    threshold: float = 18.0


class GainProcessor(ez.Unit):
    SETTINGS = GainSettings

    INPUT = ez.InputStream(float)
    INPUT_SETTINGS = ez.InputStream(GainSettings)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT_SETTINGS)
    async def on_settings(self, msg: GainSettings) -> None:
        self.apply_settings(msg)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, (msg * self.SETTINGS.factor) + self.SETTINGS.bias


class RollingAverageProcessor(ez.Unit):
    SETTINGS = RollingAverageSettings

    INPUT = ez.InputStream(float)
    INPUT_SETTINGS = ez.InputStream(RollingAverageSettings)
    OUTPUT = ez.OutputStream(float)

    def _ensure_samples(self) -> None:
        if not hasattr(self, "_samples"):
            self._samples = deque(maxlen=max(1, self.SETTINGS.window))

    @ez.subscriber(INPUT_SETTINGS)
    async def on_settings(self, msg: RollingAverageSettings) -> None:
        self._ensure_samples()
        previous = list(self._samples)
        self.apply_settings(msg)
        self._samples = deque(
            previous[-max(1, msg.window) :], maxlen=max(1, msg.window)
        )

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        self._ensure_samples()
        self._samples.append(float(msg))
        yield self.OUTPUT, sum(self._samples) / len(self._samples)


class AlertProcessor(ez.Unit):
    SETTINGS = AlertSettings

    INPUT = ez.InputStream(float)
    INPUT_SETTINGS = ez.InputStream(AlertSettings)
    OUTPUT = ez.OutputStream(str)

    @ez.subscriber(INPUT_SETTINGS)
    async def on_settings(self, msg: AlertSettings) -> None:
        self.apply_settings(msg)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        state = "ALERT" if msg >= self.SETTINGS.threshold else "OK"
        yield (
            self.OUTPUT,
            f"{state}: {msg:0.2f} (threshold {self.SETTINGS.threshold:0.2f})",
        )


class FormatProcessor(ez.Unit):
    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(str)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, f"Formatted output: {msg:0.2f}"


def add_gain_stage(path) -> None:
    path.local(BoundProcessor(GainProcessor, name="gain"))


def add_formatting_stage(path) -> None:
    path.local(BoundProcessor(FormatProcessor, name="formatter"))


def add_average_branch(slot):
    def recipe(path) -> None:
        path.local(
            BoundProcessor(RollingAverageProcessor, name="rolling_average")
        ).connect(slot)

    return recipe


class DemoWidget(QtWidgets.QWidget):
    def __init__(self, session: EzSession):
        super().__init__()
        self._session = session
        self._phase = 0.0

        self.setWindowTitle("ProcessorGraph Composition Demo")
        self.resize(1100, 700)

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(12)
        root.addLayout(left, stretch=2)

        intro = QtWidgets.QLabel(
            "This demo uses one ProcessorGraph with reusable `apply(...)` recipes, "
            "a lambda-based `branch(...)`, and multiple additive `connect(...)` sinks."
        )
        intro.setWordWrap(True)
        left.addWidget(intro)

        metrics = QtWidgets.QGroupBox("Live Outputs")
        metrics_layout = QtWidgets.QFormLayout(metrics)
        self._raw_value = QtWidgets.QLabel("Waiting...")
        self._gain_value = QtWidgets.QLabel("Waiting...")
        self._average_value = QtWidgets.QLabel("Waiting...")
        self._formatted_value = QtWidgets.QLabel("Waiting...")
        self._alert_value = QtWidgets.QLabel("Waiting...")
        metrics_layout.addRow("Source", self._raw_value)
        metrics_layout.addRow("Gain stage", self._gain_value)
        metrics_layout.addRow("Average branch", self._average_value)
        metrics_layout.addRow("Formatted main path", self._formatted_value)
        metrics_layout.addRow("Alert branch", self._alert_value)
        left.addWidget(metrics)

        log_group = QtWidgets.QGroupBox("Formatted Output Log")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        self._log = QtWidgets.QListWidget()
        log_layout.addWidget(self._log)
        left.addWidget(log_group, stretch=1)

        self._sample_pub = EzPublisher(DemoTopic.SAMPLES, parent=self, session=session)

        self._graph = (
            ProcessorGraph(DemoTopic.SAMPLES, parent=self, auto_gate=True)
            .connect(self._on_raw_value)
            .apply(add_gain_stage)
            .connect(self._on_gain_value)
            .branch(add_average_branch(self._on_average_value))
            .branch(
                lambda path: path.local(
                    BoundProcessor(AlertProcessor, name="alert")
                ).connect(self._on_alert_value)
            )
            .apply(add_formatting_stage)
            .connect(self._on_formatted_value)
            .connect(self._append_log)
            .attach(session)
        )

        self._settings_panel = ProcessorSettingsPanel.from_graph(
            self._graph,
            parent=self,
        )
        settings_group = QtWidgets.QGroupBox("Runtime Settings")
        settings_layout = QtWidgets.QVBoxLayout(settings_group)
        settings_layout.addWidget(self._settings_panel)
        root.addWidget(settings_group, stretch=1)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._publish_next_sample)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _publish_next_sample(self) -> None:
        self._phase += 0.35
        sample = (
            10.0 + (8.0 * math.sin(self._phase)) + (2.0 * math.cos(self._phase * 2.0))
        )
        self._sample_pub.emit(float(sample))

    def _on_raw_value(self, value: float) -> None:
        self._raw_value.setText(f"{value:0.2f}")

    def _on_gain_value(self, value: float) -> None:
        self._gain_value.setText(f"{value:0.2f}")

    def _on_average_value(self, value: float) -> None:
        self._average_value.setText(f"{value:0.2f}")

    def _on_formatted_value(self, value: str) -> None:
        self._formatted_value.setText(value)

    def _on_alert_value(self, value: str) -> None:
        self._alert_value.setText(value)

    def _append_log(self, value: str) -> None:
        self._log.insertItem(0, value)
        while self._log.count() > 20:
            self._log.takeItem(self._log.count() - 1)


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("processor_graph_composition_demo")

    auto_close_ms = os.getenv("EZMSG_QT_DEMO_AUTOCLOSE_MS")
    if auto_close_ms is not None:
        QtCore.QTimer.singleShot(int(auto_close_ms), app.quit)

    session = EzSession()
    widget = DemoWidget(session)
    widget.show()

    try:
        with session:
            widget.start()
            app.exec()
    finally:
        widget.stop()


if __name__ == "__main__":
    main()
