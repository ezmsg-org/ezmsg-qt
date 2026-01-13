"""EzPublisher - Send messages to ezmsg topics from Qt widgets."""

import queue
from enum import Enum
from typing import Any

from qtpy import QtCore


class EzPublisher(QtCore.QObject):
    """
    Publish messages to an ezmsg topic.

    EzPublisher provides a Qt-native interface for publishing to ezmsg topics.
    Messages are queued and sent asynchronously, allowing non-blocking operation
    from the Qt main thread.

    Example:
        class MyWidget(QtWidgets.QWidget):
            def __init__(self):
                super().__init__()
                self.settings_pub = EzPublisher(VelocityTopic.INPUT_SETTINGS, parent=self)
                self.slider.valueChanged.connect(self.send_settings)

            def send_settings(self, value):
                self.settings_pub.emit(VelocitySettings(gain=value))
    """

    def __init__(self, topic: Enum, parent: QtCore.QObject | None = None):
        """
        Create a publisher for an ezmsg topic.

        Args:
            topic: The topic enum to publish to.
            parent: Optional parent QObject for lifecycle management.
        """
        super().__init__(parent)
        self._topic = topic
        self._pub = None  # Set by EzGuiBridge during setup
        self._queue: queue.Queue[Any] = queue.Queue()

        # Register with the active bridge (or queue for later)
        from .bridge import _register_endpoint

        _register_endpoint(self)

    @property
    def topic(self) -> Enum:
        """The topic this publisher is bound to."""
        return self._topic

    def emit(self, message: Any) -> None:
        """
        Send a message to the topic.

        The message is queued and sent asynchronously by the background thread.

        Args:
            message: The message to publish.
        """
        self._queue.put(message)
