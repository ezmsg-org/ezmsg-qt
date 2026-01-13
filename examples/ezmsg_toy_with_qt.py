"""
ezmsg_toy running alongside a Qt window.

This tests that ezmsg can run in a daemon thread while Qt runs in the main thread.
No bridge yet - just proving they can coexist.
"""

import sys
import threading

from ezmsg_toy import TestSystem, TestSystemSettings

import ezmsg.core as ez
from qtpy import QtCore
from qtpy import QtWidgets


class SimpleWindow(QtWidgets.QWidget):
    """Simple Qt window that just shows ezmsg is running."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ezmsg + Qt Coexistence Test")

        layout = QtWidgets.QVBoxLayout(self)

        self.label = QtWidgets.QLabel("ezmsg is running in background thread...")
        self.label.setStyleSheet("font-size: 16px;")
        layout.addWidget(self.label)

        self.counter_label = QtWidgets.QLabel("Qt ticks: 0")
        layout.addWidget(self.counter_label)

        self.close_btn = QtWidgets.QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        layout.addWidget(self.close_btn)

        # Timer to show Qt is responsive
        self.tick_count = 0
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(1000)

    def on_tick(self):
        self.tick_count += 1
        self.counter_label.setText(f"Qt ticks: {self.tick_count}")
        print(f"[Qt] Tick {self.tick_count}")


def main():
    print("[Main] Creating ezmsg system...")
    system = TestSystem(TestSystemSettings(name="WithQt"))

    print("[Main] Starting ezmsg in background thread...")
    ez_thread = threading.Thread(
        target=lambda: ez.run(
            SYSTEM=system,
            connections=[
                (system.PING.OUTPUT, "GLOBAL_PING_TOPIC"),
            ],
        ),
        daemon=True,
        name="ezmsg",
    )
    ez_thread.start()

    print("[Main] Creating Qt application...")
    app = QtWidgets.QApplication(sys.argv)

    print("[Main] Creating window...")
    window = SimpleWindow()
    window.resize(400, 200)
    window.show()

    print("[Main] Starting Qt event loop...")
    result = app.exec()

    print("[Main] Qt event loop exited")
    return result


if __name__ == "__main__":
    sys.exit(main())
