"""EzPublisher - Send messages to ezmsg topics from Qt widgets."""

from __future__ import annotations

import asyncio
from collections import deque
import threading
from enum import Enum
from typing import Any
from typing import TYPE_CHECKING
from typing import Literal

from qtpy import QtCore

if TYPE_CHECKING:
    from .bridge import EzGuiBridge
    from ezmsg.core.pubclient import Publisher


QueuePolicy = Literal[
    "unbounded",
    "block",
    "drop_oldest",
    "drop_latest",
    "coalesce_latest",
]


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
                self.settings_pub = EzPublisher(
                    VelocityTopic.INPUT_SETTINGS, parent=self
                )
                self.slider.valueChanged.connect(self.send_settings)

            def send_settings(self, value):
                self.settings_pub.emit(VelocitySettings(gain=value))
    """

    def __init__(
        self,
        topic: Enum,
        parent: QtCore.QObject | None = None,
        *,
        bridge: EzGuiBridge | None = None,
        queue_policy: QueuePolicy = "unbounded",
        max_pending: int | None = None,
    ):
        """
        Create a publisher for an ezmsg topic.

        Args:
            topic: The topic enum to publish to.
            parent: Optional parent QObject for lifecycle management.
        """
        super().__init__(parent)
        if queue_policy == "unbounded" and max_pending is not None:
            raise ValueError("max_pending is only valid for bounded queue policies")
        if queue_policy in {"block", "drop_oldest", "drop_latest", "coalesce_latest"}:
            max_pending = 1 if max_pending is None else max_pending

        self._topic = topic
        self._pub: Publisher | None = None  # Set by EzGuiBridge during setup
        self._bridge: EzGuiBridge | None = None
        self._queue_policy = queue_policy
        self._max_pending = max_pending
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_queue: asyncio.Queue[Any] | None = None
        self._pending: deque[Any] = deque()
        self._pending_lock = threading.Lock()

        if bridge is not None:
            bridge.attach(self)

    @property
    def topic(self) -> Enum:
        """The topic this publisher is bound to."""
        return self._topic

    @property
    def bridge(self) -> EzGuiBridge | None:
        """The bridge this publisher is attached to, if any."""
        return self._bridge

    def emit(self, message: Any) -> None:
        """
        Send a message to the topic.

        The message is queued and sent asynchronously by the background thread.

        Args:
            message: The message to publish.
        """
        if self._loop is not None and self._async_queue is not None:
            if self._queue_policy == "block":
                asyncio.run_coroutine_threadsafe(
                    self._async_queue.put(message), self._loop
                ).result()
                return

            self._loop.call_soon_threadsafe(self._enqueue_async, message)
            return

        with self._pending_lock:
            self._enqueue_pending_locked(message)

    def _bind_bridge(self, bridge: EzGuiBridge) -> None:
        if self._bridge is not None and self._bridge is not bridge:
            raise RuntimeError("EzPublisher is already attached to a different bridge")
        self._bridge = bridge

    def _bind_runtime(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        maxsize = 0 if self._max_pending is None else self._max_pending
        self._async_queue = asyncio.Queue(maxsize=maxsize)

        with self._pending_lock:
            pending = list(self._pending)
            self._pending.clear()

        for message in pending:
            self._enqueue_async(message)

    async def _get_message(self) -> Any:
        if self._async_queue is None:
            raise RuntimeError("Publisher runtime queue is not initialized")
        return await self._async_queue.get()

    def _enqueue_pending_locked(self, message: Any) -> None:
        if self._queue_policy == "coalesce_latest":
            self._pending.clear()
            self._pending.append(message)
            return

        if self._max_pending is not None and len(self._pending) >= self._max_pending:
            if self._queue_policy == "drop_latest":
                return
            if self._queue_policy == "drop_oldest":
                self._pending.popleft()

        self._pending.append(message)

    def _enqueue_async(self, message: Any) -> None:
        if self._async_queue is None:
            return

        if self._queue_policy == "coalesce_latest":
            while True:
                try:
                    self._async_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            self._async_queue.put_nowait(message)
            return

        if self._async_queue.maxsize > 0 and self._async_queue.full():
            if self._queue_policy == "drop_latest":
                return
            if self._queue_policy == "drop_oldest":
                try:
                    self._async_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

        self._async_queue.put_nowait(message)
