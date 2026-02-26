"""EzDynamicSubscriber - Switch ezmsg topics at runtime from Qt widgets."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qtpy import QtCore

from .bridge import _register_dynamic
from .bridge import _request_switch


class EzDynamicSubscriber(QtCore.QObject):
    """
    Subscriber that can switch topics at runtime.

    Unlike EzSubscriber which binds to a fixed topic at construction,
    EzDynamicSubscriber allows changing the subscribed topic dynamically
    by calling :meth:`subscribe`.

    Example:
        class MyWidget(QtWidgets.QWidget):
            def __init__(self):
                super().__init__()
                self.data_sub = EzDynamicSubscriber(parent=self)
                self.data_sub.connect(self.on_data)

            def on_data(self, msg):
                self.plot.update(msg)

            def switch_topic(self, topic: str):
                self.data_sub.subscribe(topic)
    """

    received = QtCore.Signal(object)  # pyright: ignore[reportPrivateImportUsage]

    def __init__(self, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._topic: str | None = None

        # Register with the active bridge (or queue for later)
        _register_dynamic(self)

    @property
    def topic(self) -> str | None:
        """The currently subscribed topic, or None if not yet subscribed."""
        return self._topic

    def subscribe(self, topic: str) -> None:
        """
        Switch to a new topic.

        Can be called from the Qt main thread at any time. If the bridge
        is not yet active, the topic is stored and the subscription is
        established when the bridge starts.

        Args:
            topic: The topic string to subscribe to.
        """
        self._topic = topic
        _request_switch(self, topic)

    def connect(self, slot: Callable[[Any], None]) -> None:
        """
        Connect a handler to receive messages.

        Args:
            slot: A callable that will be invoked with each received message.
        """
        self.received.connect(slot)

    @QtCore.Slot(object)  # pyright: ignore[reportPrivateImportUsage]
    def _on_message(self, msg: Any) -> None:
        """Internal slot called from background thread via QMetaObject.invokeMethod."""
        self.received.emit(msg)
