#!/usr/bin/env python3
"""Demonstrate runtime EzSubscriber topic switching."""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncGenerator
from enum import Enum

import ezmsg.core as ez
from ezmsg.core.backend import GraphRunner
from qtpy import QtCore
from qtpy import QtWidgets

from ezmsg.qt import EzSession
from ezmsg.qt import EzSubscriber


class DemoTopic(Enum):
    ALPHA = "ALPHA"
    BETA = "BETA"


class TopicPublisherSettings(ez.Settings):
    prefix: str
    period_s: float


class TopicPublisher(ez.Unit):
    SETTINGS = TopicPublisherSettings

    OUTPUT = ez.OutputStream(str)

    @ez.publisher(OUTPUT)
    async def publish(self) -> AsyncGenerator:
        import asyncio

        count = 0
        while True:
            yield self.OUTPUT, f"{self.SETTINGS.prefix}-{count}"
            count += 1
            await asyncio.sleep(self.SETTINGS.period_s)


class TopicDemoGraph(ez.Collection):
    ALPHA_SOURCE = TopicPublisher()
    BETA_SOURCE = TopicPublisher()

    def configure(self) -> None:
        self.ALPHA_SOURCE.apply_settings(
            TopicPublisherSettings(prefix="alpha", period_s=0.25)
        )
        self.BETA_SOURCE.apply_settings(
            TopicPublisherSettings(prefix="beta", period_s=0.4)
        )

    def network(self) -> ez.NetworkDefinition:
        return (
            (self.ALPHA_SOURCE.OUTPUT, DemoTopic.ALPHA.name),
            (self.BETA_SOURCE.OUTPUT, DemoTopic.BETA.name),
        )


class DynamicTopicWidget(QtWidgets.QWidget):
    def __init__(self, session: EzSession):
        super().__init__()
        self.setWindowTitle("Dynamic Topic Switching Demo")
        self.setMinimumSize(520, 420)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        instructions = QtWidgets.QLabel(
            "Choose a topic. The same EzSubscriber retargets without reconnecting the slot."
        )
        instructions.setWordWrap(True)
        instructions.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        layout.addWidget(instructions)

        control_row = QtWidgets.QHBoxLayout()

        self.topic_combo = QtWidgets.QComboBox()
        self.topic_combo.addItem("Alpha", DemoTopic.ALPHA)
        self.topic_combo.addItem("Beta", DemoTopic.BETA)
        self.topic_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        control_row.addWidget(self.topic_combo)

        self.pause_button = QtWidgets.QPushButton("Pause")
        self.pause_button.clicked.connect(self.on_pause)
        control_row.addWidget(self.pause_button)

        layout.addLayout(control_row)

        self.current_topic = QtWidgets.QLabel("Active topic: ALPHA")
        self.current_topic.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        layout.addWidget(self.current_topic)

        self.message_label = QtWidgets.QLabel("Waiting for data...")
        self.message_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.message_label.setMinimumHeight(120)
        self.message_label.setStyleSheet(
            "font-size: 20px; padding: 12px; color: #1f2933; "
            "background: #eef4ff; border: 1px solid #c6d4ea; border-radius: 6px;"
        )
        layout.addWidget(self.message_label)

        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(140)
        layout.addWidget(self.log)
        layout.setStretchFactor(self.log, 1)

        self.sub = EzSubscriber(DemoTopic.ALPHA, parent=self, session=session)
        self.sub.connect(self.on_message)
        self.topic_combo.currentIndexChanged.connect(self.on_topic_changed)

        self._log("Subscribed to ALPHA")

    def on_topic_changed(self, index: int) -> None:
        topic = self.topic_combo.itemData(index)
        if topic is None:
            return
        self.sub.set_topic(topic)
        topic_name = topic.name if isinstance(topic, DemoTopic) else str(topic)
        self.current_topic.setText(f"Active topic: {topic_name}")
        self.pause_button.setText("Pause")
        self._log(f"Switched to {topic_name}")

    def on_pause(self) -> None:
        if self.sub.topic is None:
            topic = self.topic_combo.currentData()
            if topic is None:
                return
            self.sub.set_topic(topic)
            topic_name = topic.name if isinstance(topic, DemoTopic) else str(topic)
            self.current_topic.setText(f"Active topic: {topic_name}")
            self.pause_button.setText("Pause")
            self._log(f"Resumed {topic_name}")
            return

        self.sub.clear_topic()
        self.current_topic.setText("Active topic: paused")
        self.pause_button.setText("Resume")
        self._log("Paused updates")

    def on_message(self, msg: str) -> None:
        self.message_label.setText(msg)
        self._log(f"Received: {msg}")

    def _log(self, text: str) -> None:
        self.log.append(text)


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)

    runner = GraphRunner(components={"demo": TopicDemoGraph()})
    runner.start()

    session = EzSession(graph_address=runner.graph_address)
    widget = DynamicTopicWidget(session)
    widget.resize(520, 320)
    widget.show()

    auto_close_ms = os.getenv("EZMSG_QT_DEMO_AUTOCLOSE_MS")

    try:
        with session:
            if auto_close_ms is not None:
                QtCore.QTimer.singleShot(
                    500, lambda: widget.topic_combo.setCurrentIndex(1)
                )
                QtCore.QTimer.singleShot(
                    1000, lambda: widget.topic_combo.setCurrentIndex(0)
                )
                QtCore.QTimer.singleShot(int(auto_close_ms), app.quit)
            app.exec()
    finally:
        if runner.running:
            runner.stop()


if __name__ == "__main__":
    main()
