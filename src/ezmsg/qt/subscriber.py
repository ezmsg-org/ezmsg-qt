"""EzSubscriber - Receive messages from ezmsg topics in Qt widgets."""

from collections.abc import Callable
from enum import Enum
from typing import Any

from qtpy import QtCore

from .bridge import _register_endpoint


class EzSubscriber(QtCore.QObject):
    """
    Receive messages from an ezmsg topic.

    EzSubscriber provides a Qt-native interface for subscribing to ezmsg topics.
    Messages are delivered via a Qt signal, allowing seamless integration with
    Qt's event loop and signal/slot mechanism.

    Example:
        class MyWidget(QtWidgets.QWidget):
            def __init__(self):
                super().__init__()
                self.velocity_data = EzSubscriber(VelocityTopic.OUTPUT, parent=self)
                self.velocity_data.connect(self.on_velocity)

            def on_velocity(self, msg):
                self.plot.update(msg)
    """

    received = QtCore.Signal(object)

    def __init__(self, topic: Enum, parent: QtCore.QObject | None = None):
        """
        Create a subscriber for an ezmsg topic.

        Args:
            topic: The topic enum to subscribe to.
            parent: Optional parent QObject for lifecycle management.
        """
        super().__init__(parent)
        self._topic = topic
        self._sub = None  # Set by EzGuiBridge during setup

        # Register with the active bridge (or queue for later)
        _register_endpoint(self)

    @property
    def topic(self) -> Enum:
        """The topic this subscriber is bound to."""
        return self._topic

    def connect(self, slot: Callable[[Any], None]) -> None:
        """
        Connect a handler to receive messages.

        Args:
            slot: A callable that will be invoked with each received message.
        """
        self.received.connect(slot)

    @QtCore.Slot(object)
    def _on_message(self, msg: Any) -> None:
        """Internal slot called from background thread via QMetaObject.invokeMethod."""
        self.received.emit(msg)
