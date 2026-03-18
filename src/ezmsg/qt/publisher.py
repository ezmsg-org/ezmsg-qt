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

from .sidecar import normalize_topic

if TYPE_CHECKING:
    from .session import EzSession
    from ezmsg.core.pubclient import Publisher


QueuePolicy = Literal[
    "unbounded",
    "block",
    "drop_oldest",
    "drop_latest",
    "coalesce_latest",
]

TopicLike = Enum | str | None


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
                    VelocityTopic.INPUT_SETTINGS, parent=self, session=session
                )
                self.slider.valueChanged.connect(self.send_settings)

            def send_settings(self, value):
                self.settings_pub.emit(VelocitySettings(gain=value))
    """

    switch_started = QtCore.Signal(object)  # pyright: ignore[reportPrivateImportUsage]
    topic_changed = QtCore.Signal(object)  # pyright: ignore[reportPrivateImportUsage]
    topic_cleared = QtCore.Signal()  # pyright: ignore[reportPrivateImportUsage]
    switch_failed = QtCore.Signal(object, str)  # pyright: ignore[reportPrivateImportUsage]

    def __init__(
        self,
        topic: TopicLike = None,
        parent: QtCore.QObject | None = None,
        *,
        session: EzSession | None = None,
        queue_policy: QueuePolicy = "unbounded",
        max_pending: int | None = None,
    ):
        """
        Create a publisher for an ezmsg topic.

        Args:
            topic: The initial topic to publish to, or None to start unpublished.
            parent: Optional parent QObject for lifecycle management.
        """
        super().__init__(parent)
        if queue_policy == "unbounded" and max_pending is not None:
            raise ValueError("max_pending is only valid for bounded queue policies")
        if queue_policy in {"block", "drop_oldest", "drop_latest", "coalesce_latest"}:
            max_pending = 1 if max_pending is None else max_pending

        self._topic = self._validate_topic(topic)
        self._desired_topic = self._topic
        self._pub: Publisher | None = None  # Set by EzSession during setup
        self._session: EzSession | None = None
        self._queue_policy = queue_policy
        self._max_pending = max_pending
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_queue: asyncio.Queue[Any] | None = None
        self._pending: deque[Any] = deque()
        self._pending_lock = threading.Lock()

        if session is not None:
            session.attach(self)

    @property
    def topic(self) -> TopicLike:
        """The topic this publisher is bound to."""
        return self._topic

    @property
    def session(self) -> EzSession | None:
        """The session this publisher is attached to, if any."""
        return self._session

    def emit(self, message: Any) -> None:
        """
        Send a message to the topic.

        The message is queued and sent asynchronously by the background thread.

        Args:
            message: The message to publish.
        """
        if self._desired_topic is None and self._topic is None:
            raise RuntimeError("EzPublisher has no active topic")

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

    def set_topic(self, topic: Enum | str) -> None:
        """Switch to a new topic on a running session."""
        validated = self._validate_topic(topic)
        session = self._require_running_session()

        previous_desired = self._desired_topic
        self._desired_topic = validated
        self.switch_started.emit(validated)
        try:
            session._set_publisher_topic(self, validated)
            self.topic_changed.emit(self._topic)
        except Exception as exc:
            self._desired_topic = previous_desired
            self.switch_failed.emit(validated, str(exc))
            raise

    def clear_topic(self) -> None:
        """Unpublish from the current topic on a running session."""
        session = self._require_running_session()

        previous_desired = self._desired_topic
        self._desired_topic = None
        self.switch_started.emit(None)
        try:
            session._set_publisher_topic(self, None)
            self.topic_cleared.emit()
        except Exception as exc:
            self._desired_topic = previous_desired
            self.switch_failed.emit(None, str(exc))
            raise

    def _bind_session(self, session: EzSession) -> None:
        if self._session is not None and self._session is not session:
            raise RuntimeError("EzPublisher is already attached to a different session")
        self._session = session

    def _bind_runtime(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        if self._async_queue is None:
            maxsize = 0 if self._max_pending is None else self._max_pending
            self._async_queue = asyncio.Queue(maxsize=maxsize)

    async def _get_message(self) -> Any:
        if self._async_queue is None:
            raise RuntimeError("Publisher runtime queue is not initialized")
        return await self._async_queue.get()

    def _require_running_session(self) -> EzSession:
        if self._session is None:
            raise RuntimeError(
                "EzPublisher must be attached to a session before switching"
            )
        if not self._session.running:
            raise RuntimeError(
                "EzPublisher topic switching requires a running EzSession"
            )
        return self._session

    @staticmethod
    def _validate_topic(topic: TopicLike) -> TopicLike:
        if topic is None:
            return None
        normalize_topic(topic)
        return topic

    def _enqueue_pending_locked(self, message: Any) -> None:
        if self._queue_policy == "coalesce_latest":
            self._pending.clear()
            self._pending.append(message)
            return

        if self._max_pending is not None and len(self._pending) >= self._max_pending:
            if self._queue_policy == "block":
                raise RuntimeError(
                    "EzPublisher cannot block before the session runtime starts"
                )
            if self._queue_policy == "drop_latest":
                return
            if self._queue_policy == "drop_oldest":
                self._pending.popleft()

        self._pending.append(message)

    async def _flush_pending(self) -> None:
        if self._async_queue is None:
            return

        with self._pending_lock:
            pending = list(self._pending)
            self._pending.clear()

        for message in pending:
            if self._queue_policy == "block":
                await self._async_queue.put(message)
            else:
                self._enqueue_async(message)

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
