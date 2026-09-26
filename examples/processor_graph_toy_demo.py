#!/usr/bin/env python3
"""Qt-flavored reimplementation of ezmsg_toy using ProcessorGraph."""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from enum import Enum

import ezmsg.core as ez
from qtpy import QtCore
from qtpy import QtWidgets

from ezmsg.qt import BoundProcessor
from ezmsg.qt import EzPublisher
from ezmsg.qt import EzSession
from ezmsg.qt import EzSubscriber
from ezmsg.qt import ProcessorGraph
from ezmsg.qt import ProcessorSettingsPanel


class ToyTopic(Enum):
    PING = "PING"
    FOO = "FOO"
    LFO = "LFO"


@dataclass(frozen=True)
class CombinedMessage:
    string: str
    number: float


class CombineSettings(ez.Settings):
    separator: str = " | "


class PrettySettings(ez.Settings):
    prefix: str = "joined: "
    uppercase: bool = False


class PolaritySettings(ez.Settings):
    positive_label: str = "positive"
    negative_label: str = "negative"


class CombineWithLfo(ez.Unit):
    SETTINGS = CombineSettings

    INPUT = ez.InputStream(str)
    INPUT_SETTINGS = ez.InputStream(CombineSettings)
    NUMBER = ez.InputStream(float)
    OUTPUT = ez.OutputStream(CombinedMessage)

    async def initialize(self) -> None:
        self._number = 0.0

    @ez.subscriber(INPUT_SETTINGS)
    async def on_settings(self, msg: CombineSettings) -> None:
        self.apply_settings(msg)

    @ez.subscriber(NUMBER)
    async def on_number(self, msg: float) -> None:
        self._number = float(msg)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def on_message(self, msg: str):
        yield self.OUTPUT, CombinedMessage(string=msg, number=self._number)


class PrettyPrinter(ez.Unit):
    SETTINGS = PrettySettings

    INPUT = ez.InputStream(CombinedMessage)
    INPUT_SETTINGS = ez.InputStream(PrettySettings)
    OUTPUT = ez.OutputStream(str)

    @ez.subscriber(INPUT_SETTINGS)
    async def on_settings(self, msg: PrettySettings) -> None:
        self.apply_settings(msg)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def on_message(self, msg: CombinedMessage):
        joined = f"{msg.string}{self.SETTINGS.prefix}{msg.number:+0.3f}"
        if self.SETTINGS.uppercase:
            joined = joined.upper()
        yield self.OUTPUT, joined


class SummaryPrinter(ez.Unit):
    INPUT = ez.InputStream(CombinedMessage)
    OUTPUT = ez.OutputStream(str)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def on_message(self, msg: CombinedMessage):
        yield self.OUTPUT, f"summary -> {msg.string}, lfo={msg.number:+0.3f}"


class PolarityPrinter(ez.Unit):
    SETTINGS = PolaritySettings

    INPUT = ez.InputStream(CombinedMessage)
    INPUT_SETTINGS = ez.InputStream(PolaritySettings)
    OUTPUT = ez.OutputStream(str)

    @ez.subscriber(INPUT_SETTINGS)
    async def on_settings(self, msg: PolaritySettings) -> None:
        self.apply_settings(msg)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def on_message(self, msg: CombinedMessage):
        label = (
            self.SETTINGS.positive_label
            if msg.number >= 0.0
            else self.SETTINGS.negative_label
        )
        yield self.OUTPUT, f"{label}: {msg.number:+0.3f}"


def add_modifier(path) -> None:
    path.local(
        BoundProcessor(
            CombineWithLfo,
            name="modifier",
            inputs={"NUMBER": ToyTopic.LFO},
        )
    )


def add_pretty_main(formatted_slot, log_slot):
    def recipe(path) -> None:
        path.local(BoundProcessor(PrettyPrinter, name="pretty")).connect(
            formatted_slot
        ).connect(log_slot)

    return recipe


def add_summary_branch(slot):
    def recipe(path) -> None:
        path.local(BoundProcessor(SummaryPrinter, name="summary")).connect(slot)

    return recipe


class ToyWidget(QtWidgets.QWidget):
    def __init__(self, session: EzSession):
        super().__init__()
        self._session = session
        self._phase = 0.0

        self.setWindowTitle("ProcessorGraph Toy Demo")
        self.resize(1100, 720)

        self._ping_pub = EzPublisher(ToyTopic.PING, parent=self, session=session)
        self._foo_pub = EzPublisher(ToyTopic.FOO, parent=self, session=session)
        self._lfo_pub = EzPublisher(ToyTopic.LFO, parent=self, session=session)
        self._foo_sub = EzSubscriber(ToyTopic.FOO, parent=self, session=session)

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(12)
        root.addLayout(left, stretch=2)

        intro = QtWidgets.QLabel(
            "This adapts the spirit of ezmsg_toy into Qt. A single ProcessorGraph "
            "consumes PING messages, merges in an LFO side input, applies reusable "
            "recipes with `apply(...)`, fans out with `branch(...)`, and updates "
            "multiple UI sinks with additive `connect(...)`."
        )
        intro.setWordWrap(True)
        left.addWidget(intro)

        status = QtWidgets.QGroupBox("Live Streams")
        status_layout = QtWidgets.QFormLayout(status)
        self._ping_label = QtWidgets.QLabel("Waiting...")
        self._foo_label = QtWidgets.QLabel("Waiting...")
        self._lfo_label = QtWidgets.QLabel("Waiting...")
        self._pretty_label = QtWidgets.QLabel("Waiting...")
        self._summary_label = QtWidgets.QLabel("Waiting...")
        self._polarity_label = QtWidgets.QLabel("Waiting...")
        status_layout.addRow("PING source", self._ping_label)
        status_layout.addRow("FOO source", self._foo_label)
        status_layout.addRow("Current LFO", self._lfo_label)
        status_layout.addRow("Main path", self._pretty_label)
        status_layout.addRow("Function branch", self._summary_label)
        status_layout.addRow("Lambda branch", self._polarity_label)
        left.addWidget(status)

        log_group = QtWidgets.QGroupBox("Pretty Output Log")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        self._log = QtWidgets.QListWidget()
        log_layout.addWidget(self._log)
        left.addWidget(log_group, stretch=1)

        self._graph = (
            ProcessorGraph(ToyTopic.PING, parent=self, auto_gate=True)
            .connect(self._on_ping)
            .apply(add_modifier)
            .branch(add_summary_branch(self._on_summary))
            .branch(
                lambda path: path.local(
                    BoundProcessor(PolarityPrinter, name="polarity")
                ).connect(self._on_polarity)
            )
            .apply(add_pretty_main(self._on_pretty, self._append_log))
            .attach(session)
        )

        self._settings_panel = ProcessorSettingsPanel.from_graph(
            self._graph, parent=self
        )
        settings_group = QtWidgets.QGroupBox("Processor Settings")
        settings_layout = QtWidgets.QVBoxLayout(settings_group)
        settings_layout.addWidget(self._settings_panel)
        root.addWidget(settings_group, stretch=1)

        self._foo_sub.connect(self._on_foo)

        self._ping_timer = QtCore.QTimer(self)
        self._ping_timer.setInterval(1000)
        self._ping_timer.timeout.connect(lambda: self._ping_pub.emit("PING"))

        self._foo_timer = QtCore.QTimer(self)
        self._foo_timer.setInterval(1400)
        self._foo_timer.timeout.connect(lambda: self._foo_pub.emit("FOO"))

        self._lfo_timer = QtCore.QTimer(self)
        self._lfo_timer.setInterval(120)
        self._lfo_timer.timeout.connect(self._publish_lfo)

    def start(self) -> None:
        self._ping_timer.start()
        self._foo_timer.start()
        self._lfo_timer.start()

    def stop(self) -> None:
        self._ping_timer.stop()
        self._foo_timer.stop()
        self._lfo_timer.stop()

    def _publish_lfo(self) -> None:
        self._phase += 0.18
        value = math.sin(self._phase)
        self._lfo_label.setText(f"{value:+0.3f}")
        self._lfo_pub.emit(value)

    def _on_ping(self, value: str) -> None:
        self._ping_label.setText(value)

    def _on_foo(self, value: str) -> None:
        self._foo_label.setText(value)

    def _on_pretty(self, value: str) -> None:
        self._pretty_label.setText(value)

    def _on_summary(self, value: str) -> None:
        self._summary_label.setText(value)

    def _on_polarity(self, value: str) -> None:
        self._polarity_label.setText(value)

    def _append_log(self, value: str) -> None:
        self._log.insertItem(0, value)
        while self._log.count() > 18:
            self._log.takeItem(self._log.count() - 1)


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("processor_graph_toy_demo")

    auto_close_ms = os.getenv("EZMSG_QT_DEMO_AUTOCLOSE_MS")
    if auto_close_ms is not None:
        QtCore.QTimer.singleShot(int(auto_close_ms), app.quit)

    session = EzSession()
    widget = ToyWidget(session)
    widget.show()

    try:
        with session:
            widget.start()
            app.exec()
    finally:
        widget.stop()


if __name__ == "__main__":
    main()
