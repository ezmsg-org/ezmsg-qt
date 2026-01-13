"""
ezmsg_toy connected to Qt via EzGuiBridge.

This test proves:
1. ezmsg_toy runs in a background thread
2. EzGuiBridge connects a Qt widget to the "GLOBAL_PING_TOPIC"
3. Messages flow from ezmsg -> Qt via the bridge (subscribe)
4. Messages flow from Qt -> ezmsg via the bridge (publish)
"""

import ctypes
import sys
import threading
import time
from collections.abc import AsyncGenerator
from enum import Enum

from ezmsg_toy import TestSystem, TestSystemSettings

import ezmsg.core as ez
from ezmsg.core.graphserver import GraphServer


def raise_in_thread(thread: threading.Thread, exception: type[BaseException]) -> None:
    """Raise an exception in another thread."""
    if thread.ident is None:
        return
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(thread.ident),
        ctypes.py_object(exception),
    )
    if res > 1:
        # Reset if more than one thread affected
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread.ident), None)


from qtpy import QtCore
from qtpy import QtWidgets

from ezmsg.qt import EzGuiBridge
from ezmsg.qt import EzPublisher
from ezmsg.qt import EzSubscriber


# Topics for communication
class BridgeTopic(Enum):
    FROM_EZMSG = "GLOBAL_PING_TOPIC"  # ezmsg_toy publishes here
    FROM_QT = "QT_MESSAGE_TOPIC"  # Qt publishes here
    ECHO = "QT_ECHO_TOPIC"  # QtMessageReceiver echoes here

    def __str__(self):
        return self.value


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

    def __init__(self, parent=None):
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
        self.ping_sub = EzSubscriber(BridgeTopic.FROM_EZMSG, parent=self)
        self.ping_sub.connect(self.on_message_received)

        # Subscribe to echo responses from QtMessageReceiver
        self.echo_sub = EzSubscriber(BridgeTopic.ECHO, parent=self)
        self.echo_sub.connect(self.on_echo_received)

        # Publish messages to ezmsg
        self.message_pub = EzPublisher(BridgeTopic.FROM_QT, parent=self)

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
        print(f"[BridgedWindow] {text}")


def main():
    print("[Main] Starting...")

    # Start GraphServer explicitly so ezmsg and bridge share it
    print("[Main] Starting GraphServer...")
    graph_server = GraphServer()
    graph_server.start()
    graph_address = graph_server.address
    print(f"[Main] GraphServer at {graph_address}")

    # Create Qt app
    print("[Main] Creating QApplication...")
    app = QtWidgets.QApplication(sys.argv)

    # Create widget (registers EzSubscriber/EzPublisher with pending list)
    print("[Main] Creating BridgedWindow...")
    window = BridgedWindow()
    window.resize(500, 450)
    window.show()

    # Create the message receiver unit
    qt_receiver = QtMessageReceiver()

    def run_app():
        with EzGuiBridge(app, graph_address=graph_address):
            print("[Main] Bridge active, entering Qt event loop...")
            app.exec()
            print("[Main] Qt event loop exited")
            app.quit()
            raise ez.NormalTermination

    # Start ezmsg in background thread with same graph address
    print("[Main] Starting ezmsg in background thread...")
    system = TestSystem(TestSystemSettings(name="Bridged"))
    ez.run(
        SYSTEM=system,
        QT_RECEIVER=qt_receiver,
        graph_address=graph_address,
        connections=[
            # ezmsg_toy publishes PING to this topic (Qt subscribes)
            (system.PING.OUTPUT, "GLOBAL_PING_TOPIC"),
            # Qt publishes to this topic, QtMessageReceiver subscribes
            ("QT_MESSAGE_TOPIC", qt_receiver.INPUT),
            # QtMessageReceiver echoes back (Qt can see it too)
            (qt_receiver.OUTPUT, "QT_ECHO_TOPIC"),
        ],
        process_components=[system, qt_receiver],
        main_func=run_app,
    )


if __name__ == "__main__":
    sys.exit(main())
