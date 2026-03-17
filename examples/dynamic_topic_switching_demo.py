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

from ezmsg.qt import EzGuiBridge
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
            (self.ALPHA_SOURCE.OUTPUT, DemoTopic.ALPHA),
            (self.BETA_SOURCE.OUTPUT, DemoTopic.BETA),
        )


class DynamicTopicWidget(QtWidgets.QWidget):
    def __init__(self, bridge: EzGuiBridge):
        super().__init__()
        self.setWindowTitle("Dynamic Topic Switching Demo")

        layout = QtWidgets.QVBoxLayout(self)

        instructions = QtWidgets.QLabel(
            "Choose a topic. The same EzSubscriber retargets without reconnecting the slot."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self.topic_combo = QtWidgets.QComboBox()
        self.topic_combo.addItem("Alpha", DemoTopic.ALPHA)
        self.topic_combo.addItem("Beta", DemoTopic.BETA)
        layout.addWidget(self.topic_combo)

        self.current_topic = QtWidgets.QLabel("Active topic: ALPHA")
        layout.addWidget(self.current_topic)

        self.message_label = QtWidgets.QLabel("Waiting for data...")
        self.message_label.setStyleSheet(
            "font-size: 20px; padding: 12px; background: #eef4ff; border-radius: 6px;"
        )
        layout.addWidget(self.message_label)

        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        layout.addWidget(self.log)

        self.sub = EzSubscriber(DemoTopic.ALPHA, parent=self, bridge=bridge)
        self.sub.connect(self.on_message)
        self.topic_combo.currentIndexChanged.connect(self.on_topic_changed)

        self._log("Subscribed to ALPHA")

    def on_topic_changed(self, index: int) -> None:
        topic = self.topic_combo.itemData(index)
        if topic is None:
            return
        self.sub.set_topic(topic)
        self.current_topic.setText(f"Active topic: {self.sub.topic.name}")
        self._log(f"Switched to {self.sub.topic.name}")

    def on_message(self, msg: str) -> None:
        self.message_label.setText(msg)
        self._log(f"Received: {msg}")

    def _log(self, text: str) -> None:
        self.log.append(text)


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)

    runner = GraphRunner(components={"demo": TopicDemoGraph()})
    runner.start()

    bridge = EzGuiBridge(app, graph_address=runner.graph_address)
    widget = DynamicTopicWidget(bridge)
    widget.resize(520, 320)
    widget.show()

    auto_close_ms = os.getenv("EZMSG_QT_DEMO_AUTOCLOSE_MS")

    try:
        with bridge:
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
