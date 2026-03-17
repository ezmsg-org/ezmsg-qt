"""
ezmsg_toy connected to Qt via EzGuiBridge + GraphRunner.

This test proves:
1. GraphRunner runs ezmsg_toy in a background thread
2. EzGuiBridge connects a Qt widget to the "GLOBAL_PING_TOPIC"
3. Messages flow from ezmsg -> Qt via the bridge (subscribe)
4. Messages flow from Qt -> ezmsg via the bridge (publish)
"""

import asyncio
import math
import sys
import os
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from enum import Enum

import ezmsg.core as ez
from ezmsg.core.backend import GraphRunner
from qtpy import QtCore
from qtpy import QtWidgets

from ezmsg.qt import EzGuiBridge
from ezmsg.qt import EzPublisher
from ezmsg.qt import EzSubscriber


# Topics for communication
class BridgeTopic(Enum):
    FROM_EZMSG = "FROM_EZMSG"  # ezmsg_toy publishes here
    FROM_QT = "FROM_QT"  # Qt publishes here
    ECHO = "ECHO"  # QtMessageReceiver echoes here


@dataclass
class CombinedMessage:
    string: str
    number: float


class LFOSettings(ez.Settings):
    freq: float = 0.2  # Hz, sinus frequency
    update_rate: float = 2.0  # Hz, update rate


class LFO(ez.Unit):
    SETTINGS = LFOSettings

    OUTPUT = ez.OutputStream(float)

    async def initialize(self) -> None:
        self.start_time = time.time()

    @ez.publisher(OUTPUT)
    async def generate(self) -> AsyncGenerator:
        while True:
            t = time.time() - self.start_time
            yield self.OUTPUT, math.sin(2.0 * math.pi * self.SETTINGS.freq * t)
            await asyncio.sleep(1.0 / self.SETTINGS.update_rate)


class MessageGeneratorSettings(ez.Settings):
    message: str


class MessageGenerator(ez.Unit):
    SETTINGS = MessageGeneratorSettings

    OUTPUT = ez.OutputStream(str)

    @ez.publisher(OUTPUT)
    async def spawn_message(self) -> AsyncGenerator:
        while True:
            await asyncio.sleep(1.0)
            ez.logger.info(f"Spawning {self.SETTINGS.message}")
            yield self.OUTPUT, self.SETTINGS.message


class DebugOutputSettings(ez.Settings):
    name: str | None = "Default"


class DebugOutput(ez.Unit):
    SETTINGS = DebugOutputSettings

    INPUT = ez.InputStream(str)

    @ez.subscriber(INPUT)
    async def on_message(self, message: str) -> None:
        ez.logger.info(f"Output[{self.SETTINGS.name}]: {message}")


class MessageModifierState(ez.State):
    number: float


class MessageModifier(ez.Unit):
    """Store number input, and append it to message."""

    STATE = MessageModifierState

    MESSAGE = ez.InputStream(str)
    NUMBER = ez.InputStream(float)

    JOINED = ez.OutputStream(str)
    REPUB = ez.OutputStream(CombinedMessage)

    async def initialize(self) -> None:
        self.STATE.number = 0.0

    @ez.subscriber(NUMBER)
    async def on_number(self, number: float) -> None:
        self.STATE.number = number

    @ez.subscriber(MESSAGE)
    @ez.publisher(JOINED)
    @ez.publisher(REPUB)
    async def on_message(self, message: str) -> AsyncGenerator:
        yield self.REPUB, CombinedMessage(string=message, number=self.STATE.number)

        if self.STATE.number is not None:
            message = f"{message}|{self.STATE.number}"

        yield self.JOINED, message

    @ez.main
    def blocking_main(self) -> None:
        for i in range(10):
            ez.logger.info(i)
            time.sleep(1.0)


class ModifierCollection(ez.Collection):
    """Subscribe to messages and append the most recent LFO output."""

    INPUT = ez.InputStream(str)
    OUTPUT = ez.OutputStream(str)

    SIN = LFO()
    MODIFIER = MessageModifier()

    REPUB_OUT = DebugOutput(DebugOutputSettings(name="REPUB"))

    def configure(self) -> None:
        self.SIN.apply_settings(LFOSettings(freq=0.1))

    def network(self) -> ez.NetworkDefinition:
        return (
            (self.SIN.OUTPUT, self.MODIFIER.NUMBER),
            (self.INPUT, self.MODIFIER.MESSAGE),
            (self.MODIFIER.JOINED, self.OUTPUT),
            (self.MODIFIER.REPUB, self.REPUB_OUT.INPUT),
        )


class TestSystemSettings(ez.Settings):
    name: str


class TestSystem(ez.Collection):
    SETTINGS = TestSystemSettings

    PING = MessageGenerator()
    FOO = MessageGenerator()

    MODIFIER_COLLECTION = ModifierCollection()

    PINGSUB1 = DebugOutput()
    PINGSUB2 = DebugOutput()
    FOOSUB = DebugOutput()

    def configure(self) -> None:
        self.PING.apply_settings(MessageGeneratorSettings(message="PING"))
        self.FOO.apply_settings(MessageGeneratorSettings(message="FOO"))
        self.PINGSUB1.apply_settings(DebugOutputSettings(name=f"{self.SETTINGS.name}1"))
        self.PINGSUB2.apply_settings(DebugOutputSettings(name=f"{self.SETTINGS.name}2"))

    def network(self) -> ez.NetworkDefinition:
        return (
            (self.PING.OUTPUT, self.PINGSUB1.INPUT),
            (self.PING.OUTPUT, self.MODIFIER_COLLECTION.INPUT),
            (self.MODIFIER_COLLECTION.OUTPUT, self.PINGSUB2.INPUT),
            (self.FOO.OUTPUT, self.FOOSUB.INPUT),
            (self.PING.OUTPUT, self.FOOSUB.INPUT),
        )

    def process_components(self):
        return (self.PING, self.FOOSUB, self.MODIFIER_COLLECTION, self.PINGSUB1)


# Simple ezmsg unit that receives messages from Qt
class QtMessageReceiver(ez.Unit):
    """Receives messages published from Qt and logs them."""

    INPUT = ez.InputStream(str)
    OUTPUT = ez.OutputStream(str)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def on_message(self, msg: str) -> AsyncGenerator:
        ez.logger.info(f"[QtMessageReceiver] Got from Qt: {msg}")
        # Echo back with confirmation
        response = f"ezmsg received: {msg}"
        yield self.OUTPUT, response


class BridgedWindow(QtWidgets.QWidget):
    """Qt window that sends and receives messages via the bridge."""

    def __init__(self, bridge: EzGuiBridge, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ezmsg_toy + EzGuiBridge Test")

        layout = QtWidgets.QVBoxLayout(self)

        # --- Publish section ---
        publish_group = QtWidgets.QGroupBox("Publish to ezmsg")
        publish_layout = QtWidgets.QHBoxLayout(publish_group)

        self.message_input = QtWidgets.QLineEdit()
        self.message_input.setPlaceholderText("Enter message to send...")
        self.message_input.returnPressed.connect(self.on_send)
        publish_layout.addWidget(self.message_input)

        self.send_btn = QtWidgets.QPushButton("Send")
        self.send_btn.clicked.connect(self.on_send)
        publish_layout.addWidget(self.send_btn)

        layout.addWidget(publish_group)

        # --- Subscribe section ---
        subscribe_group = QtWidgets.QGroupBox("Received from ezmsg")
        subscribe_layout = QtWidgets.QVBoxLayout(subscribe_group)

        self.message_count = 0
        self.count_label = QtWidgets.QLabel("Messages received: 0")
        self.count_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        subscribe_layout.addWidget(self.count_label)

        self.last_msg_label = QtWidgets.QLabel("Last message: (none)")
        subscribe_layout.addWidget(self.last_msg_label)

        layout.addWidget(subscribe_group)

        # --- Log area ---
        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(200)
        layout.addWidget(self.log)

        self.close_btn = QtWidgets.QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        layout.addWidget(self.close_btn)

        # --- ezmsg connections ---
        # Subscribe to messages from ezmsg_toy
        self.ping_sub = EzSubscriber(BridgeTopic.FROM_EZMSG, parent=self, bridge=bridge)
        self.ping_sub.connect(self.on_message_received)

        # Subscribe to echo responses from QtMessageReceiver
        self.echo_sub = EzSubscriber(BridgeTopic.ECHO, parent=self, bridge=bridge)
        self.echo_sub.connect(self.on_echo_received)

        # Publish messages to ezmsg
        self.message_pub = EzPublisher(BridgeTopic.FROM_QT, parent=self, bridge=bridge)

        self._log("Widget initialized")

    def on_send(self):
        """Send message to ezmsg via the bridge."""
        text = self.message_input.text().strip()
        if text:
            self._log(f"Publishing: {text}")
            self.message_pub.emit(text)
            self.message_input.clear()

    def on_message_received(self, msg):
        """Handle incoming messages from ezmsg_toy."""
        self.message_count += 1
        self.count_label.setText(f"Messages received: {self.message_count}")
        self.last_msg_label.setText(f"Last: {msg}")
        self._log(f"[ezmsg->Qt] {msg}")

    def on_echo_received(self, msg):
        """Handle echo responses from QtMessageReceiver."""
        self._log(f"[echo] {msg}")

    def _log(self, text: str):
        self.log.append(text)


def main():
    print("[Main] Starting...")

    # Create Qt app
    print("[Main] Creating QApplication...")
    app = QtWidgets.QApplication(sys.argv)

    # Create the message receiver unit
    qt_receiver = QtMessageReceiver()

    print("[Main] Starting GraphRunner...")
    system = TestSystem(TestSystemSettings(name="Bridged"))
    runner = GraphRunner(
        components={
            "SYSTEM": system,
            "QT_RECEIVER": qt_receiver,
        },
        connections=[
            # ezmsg_toy publishes PING to this topic (Qt subscribes)
            (system.PING.OUTPUT, BridgeTopic.FROM_EZMSG.name),
            # Qt publishes to this topic, QtMessageReceiver subscribes
            (BridgeTopic.FROM_QT.name, qt_receiver.INPUT),
            # QtMessageReceiver echoes back (Qt can see it too)
            (qt_receiver.OUTPUT, BridgeTopic.ECHO.name),
        ],
        process_components=[system, qt_receiver],
    )

    runner.start()
    bridge = EzGuiBridge(app, graph_address=runner.graph_address)

    # Create widget and attach Qt endpoints explicitly
    print("[Main] Creating BridgedWindow...")
    window = BridgedWindow(bridge)
    window.resize(500, 450)
    window.show()

    try:
        with bridge:
            auto_close_ms = os.getenv("EZMSG_QT_DEMO_AUTOCLOSE_MS")
            if auto_close_ms is not None:
                QtCore.QTimer.singleShot(int(auto_close_ms), app.quit)
            print("[Main] Bridge active, entering Qt event loop...")
            app.exec()
            print("[Main] Qt event loop exited")
            app.quit()
    finally:
        if runner.running:
            runner.stop()


if __name__ == "__main__":
    sys.exit(main())
