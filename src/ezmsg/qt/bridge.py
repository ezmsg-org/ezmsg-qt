"""EzGuiBridge - Manages async infrastructure for Qt/ezmsg integration."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

from qtpy import QtCore
from qtpy import QtWidgets

from ezmsg.core.graphcontext import GraphContext
from ezmsg.core.netprotocol import AddressType

if TYPE_CHECKING:
    from .publisher import EzPublisher
    from .subscriber import EzSubscriber

logger = logging.getLogger(__name__)

# Global state for self-registration
_active_bridge: EzGuiBridge | None = None
_pending_endpoints: list[EzSubscriber | EzPublisher] = []


def _register_endpoint(endpoint: EzSubscriber | EzPublisher) -> None:
    """Register an endpoint with the active bridge or queue for later."""
    if _active_bridge is not None:
        _active_bridge._register(endpoint)
    else:
        _pending_endpoints.append(endpoint)


class EzGuiBridge:
    """
    Bridge Qt widgets to ezmsg channels.

    EzGuiBridge manages the asyncio infrastructure needed to connect Qt widgets
    to ezmsg's pub/sub system. It runs a background thread with an asyncio
    event loop, handling all async operations while presenting a sync API
    to Qt code.

    Usage:
        app = QtWidgets.QApplication([])
        window = MyWidget()  # Creates EzSubscriber/EzPublisher instances
        window.show()

        with EzGuiBridge(app):
            app.exec()
    """

    def __init__(
        self,
        app: QtWidgets.QApplication,
        graph_address: AddressType | None = None,
    ):
        """
        Create a bridge for Qt/ezmsg integration.

        Args:
            app: The Qt application instance.
            graph_address: Optional address of the GraphServer.
        """
        self.app = app
        self._context = GraphContext(graph_address)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: list[EzSubscriber] = []
        self._publishers: list[EzPublisher] = []
        self._shutdown = threading.Event()
        self._setup_complete = threading.Event()
        self._running = False

    def __enter__(self) -> EzGuiBridge:
        """Start async infrastructure and connect channels."""
        global _active_bridge
        _active_bridge = self
        self._running = True

        # Process any pending endpoints created before bridge started
        for endpoint in _pending_endpoints:
            self._register(endpoint)
        _pending_endpoints.clear()

        # Start background asyncio thread
        self._thread = threading.Thread(
            target=self._run_async_loop, daemon=True, name="EzGuiBridge"
        )
        self._thread.start()

        # Wait for async setup to complete
        if not self._setup_complete.wait(timeout=30.0):
            raise RuntimeError("EzGuiBridge setup timed out")

        return self

    def __exit__(self, *exc) -> None:
        """Cleanup channels and stop async thread."""
        global _active_bridge
        self._running = False

        # Signal asyncio loop to stop
        self._shutdown.set()

        # Wait for background thread
        if self._thread is not None:
            self._thread.join(timeout=10.0)

        _active_bridge = None

    def _register(self, endpoint: EzSubscriber | EzPublisher) -> None:
        """Register an endpoint for connection."""
        from .publisher import EzPublisher
        from .subscriber import EzSubscriber

        if isinstance(endpoint, EzSubscriber):
            self._subscribers.append(endpoint)
            # If already running, connect immediately
            if self._running and self._loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self._setup_subscriber(endpoint), self._loop
                )
        elif isinstance(endpoint, EzPublisher):
            self._publishers.append(endpoint)
            # If already running, connect immediately
            if self._running and self._loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self._setup_publisher(endpoint), self._loop
                )

    def _run_async_loop(self) -> None:
        """Background thread entry point."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._async_main())
        except Exception:
            logger.exception("Error in EzGuiBridge async loop")
        finally:
            self._loop.close()

    async def _async_main(self) -> None:
        """Main async entry point."""
        try:
            # Setup all subscribers and publishers
            await self._async_setup()
            self._setup_complete.set()

            # Run until shutdown requested
            while not self._shutdown.is_set():
                await asyncio.sleep(0.1)

        finally:
            # Cleanup
            await self._async_cleanup()

    async def _async_setup(self) -> None:
        """Create all pub/sub clients."""
        for subscriber in self._subscribers:
            await self._setup_subscriber(subscriber)

        for publisher in self._publishers:
            await self._setup_publisher(publisher)

    async def _setup_subscriber(self, ez_sub: EzSubscriber) -> None:
        """Setup a single subscriber."""
        topic_str = str(ez_sub.topic)
        logger.debug(f"Creating subscriber for {topic_str}")
        sub = await self._context.subscriber(topic_str)
        ez_sub._sub = sub

        # Start receive loop
        asyncio.create_task(
            self._subscriber_loop(ez_sub, sub), name=f"sub-{topic_str}"
        )

    async def _setup_publisher(self, ez_pub: EzPublisher) -> None:
        """Setup a single publisher."""
        topic_str = str(ez_pub.topic)
        logger.debug(f"Creating publisher for {topic_str}")
        pub = await self._context.publisher(topic_str)
        ez_pub._pub = pub

        # Start publish loop
        asyncio.create_task(
            self._publisher_loop(ez_pub, pub), name=f"pub-{topic_str}"
        )

    async def _subscriber_loop(self, ez_sub: EzSubscriber, sub) -> None:
        """Receive messages and emit Qt signals."""
        try:
            while self._running:
                msg = await sub.recv()

                # Thread-safe emit to Qt main thread
                QtCore.QMetaObject.invokeMethod(
                    ez_sub,
                    "_on_message",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(object, msg),
                )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(f"Error in subscriber loop for {ez_sub.topic}")

    async def _publisher_loop(self, ez_pub: EzPublisher, pub) -> None:
        """Check queue and broadcast messages."""
        try:
            while self._running:
                try:
                    # Non-blocking check with small timeout
                    msg = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: ez_pub._queue.get(timeout=0.1)
                    )
                    await pub.broadcast(msg)
                except Exception:
                    # Queue.get timeout - continue loop
                    pass
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(f"Error in publisher loop for {ez_pub.topic}")

    async def _async_cleanup(self) -> None:
        """Cleanup all clients."""
        logger.debug("Cleaning up EzGuiBridge")
        await self._context.revert()
