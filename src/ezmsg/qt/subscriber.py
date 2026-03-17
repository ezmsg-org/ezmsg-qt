"""EzSubscriber - Receive messages from ezmsg topics in Qt widgets."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any
from typing import TYPE_CHECKING

from qtpy import QtCore

if TYPE_CHECKING:
    from .bridge import EzGuiBridge
    from ezmsg.core.subclient import Subscriber


class EzSubscriber(QtCore.QObject):
    """
    Receive messages from an ezmsg topic.

    EzSubscriber provides a Qt-native interface for subscribing to ezmsg topics.
    Messages are delivered via a Qt signal, allowing seamless integration with
    Qt's event loop and signal/slot mechanism.

    For processing chains, use ProcessorChain directly instead.

    Example:
        class MyWidget(QtWidgets.QWidget):
            def __init__(self):
                super().__init__()
                # Simple subscription
                self.velocity_data = EzSubscriber(VelocityTopic.OUTPUT, parent=self)
                self.velocity_data.connect(self.on_velocity)

            def on_velocity(self, msg):
                self.plot.update(msg)
    """

    received = QtCore.Signal(object)  # pyright: ignore[reportPrivateImportUsage]

    def __init__(
        self,
        topic: Enum,
        parent: QtCore.QObject | None = None,
        *,
        bridge: EzGuiBridge | None = None,
        leaky: bool = False,
        max_queue: int | None = None,
        throttle_hz: float | None = None,
    ):
        """
        Create a subscriber for an ezmsg topic.

        Args:
            topic: The topic enum to subscribe to.
            parent: Optional parent QObject for lifecycle management.
            leaky: If True, the underlying ezmsg Subscriber will drop old messages
                if the receiver can't keep up (no backpressure).
            max_queue: Queue depth for leaky mode. If None, ezmsg defaults apply.
            throttle_hz: If set, throttle delivery by reading at most this many
                messages per second from the underlying ezmsg Subscriber.
        """
        super().__init__(parent)
        self._topic = topic
        self._sub: Subscriber | None = None  # Set by EzGuiBridge during setup
        self._bridge: EzGuiBridge | None = None
        self._leaky = bool(leaky)
        self._max_queue = max_queue
        self._throttle_hz = throttle_hz

        if self._max_queue is not None and self._max_queue <= 0:
            raise ValueError("max_queue must be positive")
        if self._throttle_hz is not None and self._throttle_hz <= 0:
            raise ValueError("throttle_hz must be positive")

        if bridge is not None:
            bridge.attach(self)

    @property
    def topic(self) -> Enum:
        """The topic this subscriber is bound to."""
        return self._topic

    @property
    def bridge(self) -> EzGuiBridge | None:
        """The bridge this subscriber is attached to, if any."""
        return self._bridge

    @property
    def leaky(self) -> bool:
        """Whether this subscriber drops old messages instead of backpressure."""
        return self._leaky

    @property
    def max_queue(self) -> int | None:
        """Leaky notification queue depth (ignored if leaky=False)."""
        return self._max_queue

    @property
    def throttle_hz(self) -> float | None:
        """If set, throttle reads from the underlying ezmsg Subscriber."""
        return self._throttle_hz

    def connect(self, slot: Callable[[Any], None]) -> None:
        """
        Connect a handler to receive messages.

        Args:
            slot: A callable that will be invoked with each received message.
        """
        self.received.connect(slot)

    @QtCore.Slot(object)  # pyright: ignore[reportPrivateImportUsage]
    def _on_message(self, msg: Any) -> None:
        """Internal slot called from the Qt signal dispatcher."""
        self.received.emit(msg)

    def _bind_bridge(self, bridge: EzGuiBridge) -> None:
        if self._bridge is not None and self._bridge is not bridge:
            raise RuntimeError("EzSubscriber is already attached to a different bridge")
        self._bridge = bridge
