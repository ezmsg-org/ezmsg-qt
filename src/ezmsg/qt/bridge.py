"""EzGuiBridge - Manages async infrastructure for Qt/ezmsg integration."""

from __future__ import annotations

import asyncio
import logging
import signal
import socket
import threading
from typing import TYPE_CHECKING

from ezmsg.core.backend import GraphRunner
from ezmsg.core.graphcontext import GraphContext
from ezmsg.core.netprotocol import AddressType
from qtpy import QtCore
from qtpy import QtWidgets

if TYPE_CHECKING:
    from .chain import ProcessorChain
    from .publisher import EzPublisher
    from .subscriber import EzSubscriber

logger = logging.getLogger(__name__)

# Global state for self-registration
_active_bridge: EzGuiBridge | None = None
_pending_endpoints: list[EzSubscriber | EzPublisher] = []
_pending_chains: list[ProcessorChain] = []


def _register_chain(chain: ProcessorChain) -> None:
    """Register a processor chain with the active bridge or queue for later."""
    if _active_bridge is not None:
        _active_bridge._register_chain(chain)
    else:
        _pending_chains.append(chain)


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
        self._context_entered = False
        self._context = GraphContext(graph_address)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: list[EzSubscriber] = []
        self._publishers: list[EzPublisher] = []
        self._tasks: set[asyncio.Task[None]] = set()
        self._shutdown = threading.Event()
        self._setup_complete = threading.Event()
        self._running = False
        self._prev_sigint_handler = None
        self._sigint_notifier: QtCore.QSocketNotifier | None = None
        self._wakeup_sock_r: socket.socket | None = None
        self._wakeup_sock_w: socket.socket | None = None
        self._wakeup_prev_fd: int | None = None
        self._chains: list[ProcessorChain] = []
        self._chain_counter: int = 0
        self._sidecar: GraphRunner | None = None

    def __enter__(self) -> EzGuiBridge:
        """Start async infrastructure and connect channels."""
        global _active_bridge
        _active_bridge = self
        self._running = True
        self._install_sigint_handler()

        # Process any pending endpoints created before bridge started
        for endpoint in _pending_endpoints:
            self._register(endpoint)
        _pending_endpoints.clear()

        # Process any pending chains created before bridge started
        for chain in _pending_chains:
            self._register_chain(chain)
        _pending_chains.clear()

        # Start background asyncio thread
        self._thread = threading.Thread(
            target=self._run_async_loop, daemon=True, name="EzGuiBridge"
        )
        self._thread.start()

        # Wait for async setup to complete
        if not self._setup_complete.wait(timeout=30.0):
            raise RuntimeError("EzGuiBridge setup timed out")

        return self

    def __exit__(self, exc_type, exc, exc_tb) -> bool | None:
        """Cleanup channels and stop async thread."""
        global _active_bridge
        self._running = False
        if exc_type is KeyboardInterrupt:
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.quit()

        # Signal asyncio loop to stop
        self._shutdown.set()

        # Wait for background thread
        if self._thread is not None:
            self._thread.join(timeout=10.0)

        _active_bridge = None
        self._restore_sigint_handler()
        if exc_type is KeyboardInterrupt:
            return False

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

    def _register_chain(self, chain: ProcessorChain) -> None:
        """Register a processor chain for setup."""
        from .chain import ProcessorChain

        chain._chain_id = f"chain_{self._chain_counter}"
        self._chain_counter += 1
        self._chains.append(chain)

        # If already running, set up immediately
        if self._running and self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._setup_chain(chain), self._loop)

    async def _setup_chains(self) -> None:
        """Set up all processor chains including sidecar."""
        from .sidecar import build_sidecar_components

        if not self._chains:
            return

        # Assign chain IDs if not already set
        for chain in self._chains:
            if chain._chain_id is None:
                chain._chain_id = f"chain_{self._chain_counter}"
                self._chain_counter += 1

        # Build sidecar components for in_process stages
        components, connections = build_sidecar_components(self._chains)

        if components:
            # Start sidecar GraphRunner
            self._sidecar = GraphRunner(
                components=components,
                connections=connections,
                graph_address=self._context.graph_address,
            )
            self._sidecar.start()
            logger.info(f"Started sidecar with {len(components)} components")

        # Set up each chain (bridge-thread stages + output subscription)
        for chain in self._chains:
            await self._setup_chain(chain)

    async def _setup_chain(self, chain: ProcessorChain) -> None:
        """Set up a processor chain."""
        if not chain.stages or chain.handler is None:
            return

        has_in_process = any(s.in_process for s in chain.stages)
        bridge_stages = [s for s in chain.stages if not s.in_process]

        if has_in_process:
            # Subscribe to sidecar output topic
            output_topic = f"_qt.{chain._chain_id}.out"

            if bridge_stages:
                # Need to run bridge stages after sidecar output
                processors = []
                for stage in bridge_stages:
                    unit = stage.unit_class()
                    if stage.settings:
                        unit.apply_settings(stage.settings)
                    await unit.initialize()
                    processors.append(unit)

                sub = await self._context.subscriber(output_topic)
                task = asyncio.create_task(
                    self._chain_processor_loop(chain, sub, processors),
                    name=f"chain-{chain._chain_id}-bridge",
                )
            else:
                # No bridge stages - just subscribe to sidecar output
                sub = await self._context.subscriber(output_topic)
                task = asyncio.create_task(
                    self._chain_output_loop(chain, sub),
                    name=f"chain-{chain._chain_id}-output",
                )

            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        elif bridge_stages:
            # All stages in bridge thread
            processors = []
            for stage in bridge_stages:
                unit = stage.unit_class()
                if stage.settings:
                    unit.apply_settings(stage.settings)
                await unit.initialize()
                processors.append(unit)

            source_topic = str(chain.source_topic)
            sub = await self._context.subscriber(source_topic)

            task = asyncio.create_task(
                self._chain_processor_loop(chain, sub, processors),
                name=f"chain-{chain._chain_id}",
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _chain_processor_loop(
        self,
        chain: ProcessorChain,
        sub,
        processors: list,
    ) -> None:
        """Run messages through bridge-thread processor chain."""
        logger.debug(f"Chain processor loop started for {chain._chain_id}")
        try:
            while self._running:
                msg = await sub.recv()

                # Run through each processor
                result = msg
                for processor in processors:
                    # Call the processor's subscriber method
                    async for output_stream, output_msg in self._run_processor(
                        processor, result
                    ):
                        result = output_msg
                        break  # Take first output

                # Deliver to Qt handler
                if chain.handler is not None:
                    QtCore.QMetaObject.invokeMethod(
                        self.app,
                        lambda r=result, h=chain.handler: h(r),
                        QtCore.Qt.ConnectionType.QueuedConnection,
                    )

        except asyncio.CancelledError:
            logger.debug(f"Chain loop cancelled for {chain._chain_id}")
        except Exception:
            logger.exception(f"Error in chain loop for {chain._chain_id}")

    async def _chain_output_loop(self, chain: ProcessorChain, sub) -> None:
        """Receive sidecar output and deliver to Qt handler."""
        logger.debug(f"Chain output loop started for {chain._chain_id}")
        try:
            while self._running:
                msg = await sub.recv()

                if chain.handler is not None:
                    QtCore.QMetaObject.invokeMethod(
                        self.app,
                        lambda r=msg, h=chain.handler: h(r),
                        QtCore.Qt.ConnectionType.QueuedConnection,
                    )
        except asyncio.CancelledError:
            logger.debug(f"Chain output loop cancelled for {chain._chain_id}")
        except Exception:
            logger.exception(f"Error in chain output loop for {chain._chain_id}")

    async def _run_processor(self, processor, msg):
        """Run a single processor on a message."""
        # Find the subscriber method that has a publisher decorator
        for name in dir(processor):
            method = getattr(processor, name)
            if hasattr(method, "_ez_subscribers") and hasattr(method, "_ez_publishers"):
                async for item in method(msg):
                    yield item
                return

    def _install_sigint_handler(self) -> None:
        try:
            self._prev_sigint_handler = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, self._handle_sigint)
            self._install_signal_wakeup()
        except (ValueError, RuntimeError) as exc:
            logger.debug(f"Unable to install SIGINT handler: {exc}")

    def _restore_sigint_handler(self) -> None:
        self._restore_signal_wakeup()
        if self._prev_sigint_handler is None:
            return
        try:
            signal.signal(signal.SIGINT, self._prev_sigint_handler)
        except (ValueError, RuntimeError) as exc:
            logger.debug(f"Unable to restore SIGINT handler: {exc}")
        finally:
            self._prev_sigint_handler = None

    def _handle_sigint(self, sig, frame) -> None:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.quit()

    def _install_signal_wakeup(self) -> None:
        if self._sigint_notifier is not None:
            return
        try:
            sock_r, sock_w = socket.socketpair()
            sock_r.setblocking(False)
            sock_w.setblocking(False)
            self._wakeup_prev_fd = signal.set_wakeup_fd(sock_w.fileno())
            self._wakeup_sock_r = sock_r
            self._wakeup_sock_w = sock_w
            self._sigint_notifier = QtCore.QSocketNotifier(
                sock_r.fileno(),  # pyright: ignore[reportArgumentType]
                QtCore.QSocketNotifier.Type.Read,
                self.app,
            )
            self._sigint_notifier.activated.connect(self._on_signal_wakeup)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug(f"Unable to install signal wakeup fd: {exc}")
            self._restore_signal_wakeup()

    def _restore_signal_wakeup(self) -> None:
        if self._sigint_notifier is not None:
            self._sigint_notifier.setEnabled(False)
            self._sigint_notifier.deleteLater()
            self._sigint_notifier = None
        if self._wakeup_prev_fd is not None:
            try:
                signal.set_wakeup_fd(self._wakeup_prev_fd)
            except (OSError, RuntimeError, ValueError) as exc:
                logger.debug(f"Unable to restore wakeup fd: {exc}")
            finally:
                self._wakeup_prev_fd = None
        if self._wakeup_sock_r is not None:
            self._wakeup_sock_r.close()
            self._wakeup_sock_r = None
        if self._wakeup_sock_w is not None:
            self._wakeup_sock_w.close()
            self._wakeup_sock_w = None

    def _on_signal_wakeup(self, _fd: int) -> None:
        if self._wakeup_sock_r is None:
            return
        got_sigint = False
        try:
            while True:
                data = self._wakeup_sock_r.recv(128)
                if not data:
                    break
                if signal.SIGINT in data:
                    got_sigint = True
        except BlockingIOError:
            pass
        if got_sigint:
            self._handle_sigint(signal.SIGINT, None)

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
            await self._context.__aenter__()
            self._context_entered = True

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
        """Create all pub/sub clients and processor chains."""
        for subscriber in self._subscribers:
            await self._setup_subscriber(subscriber)

        for publisher in self._publishers:
            await self._setup_publisher(publisher)

        # Set up processor chains (includes sidecar setup)
        await self._setup_chains()

    async def _setup_subscriber(self, ez_sub: EzSubscriber) -> None:
        """Setup a single subscriber."""
        topic_str = str(ez_sub.topic)
        logger.debug(f"Creating subscriber for {topic_str}")
        sub = await self._context.subscriber(topic_str)
        ez_sub._sub = sub

        # Start receive loop
        task = asyncio.create_task(
            self._subscriber_loop(ez_sub, sub), name=f"sub-{topic_str}"
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _setup_publisher(self, ez_pub: EzPublisher) -> None:
        """Setup a single publisher."""
        topic_str = str(ez_pub.topic)
        logger.debug(f"Creating publisher for {topic_str}")
        pub = await self._context.publisher(topic_str)
        ez_pub._pub = pub

        # Start publish loop
        task = asyncio.create_task(
            self._publisher_loop(ez_pub, pub), name=f"pub-{topic_str}"
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _subscriber_loop(self, ez_sub: EzSubscriber, sub) -> None:
        """Receive messages and emit Qt signals."""
        logger.debug(f"Subscriber loop started for {ez_sub.topic}")
        try:
            while self._running:
                logger.debug(f"Waiting for message on {ez_sub.topic}...")
                msg = await sub.recv()
                logger.debug(f"Received message on {ez_sub.topic}: {msg}")

                # Thread-safe emit to Qt main thread
                QtCore.QMetaObject.invokeMethod(
                    ez_sub,
                    "_on_message",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(object, msg),
                )
        except asyncio.CancelledError:
            logger.debug(f"Subscriber loop cancelled for {ez_sub.topic}")
        except GeneratorExit:
            logger.debug(f"Subscriber loop exiting for {ez_sub.topic}")
        except RuntimeError as exc:
            if (
                not self._running
                or self._shutdown.is_set()
                or self._loop is None
                or self._loop.is_closed()
                or "Event loop is closed" in str(exc)
            ):
                logger.debug(f"Subscriber loop stopping for {ez_sub.topic}: {exc}")
            else:
                logger.exception(f"Error in subscriber loop for {ez_sub.topic}")
        except Exception:
            logger.exception(f"Error in subscriber loop for {ez_sub.topic}")

    async def _publisher_loop(self, ez_pub: EzPublisher, pub) -> None:
        """Check queue and broadcast messages."""
        import queue as queue_module

        logger.debug(f"Publisher loop started for {ez_pub.topic}")
        try:
            while self._running:
                try:
                    # Non-blocking check with small timeout
                    msg = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: ez_pub._queue.get(timeout=0.1)
                    )
                    logger.debug(f"Broadcasting message on {ez_pub.topic}: {msg}")
                    await pub.broadcast(msg)
                except queue_module.Empty:
                    # Queue.get timeout - continue loop
                    pass
        except asyncio.CancelledError:
            logger.debug(f"Publisher loop cancelled for {ez_pub.topic}")
        except GeneratorExit:
            logger.debug(f"Publisher loop exiting for {ez_pub.topic}")
        except RuntimeError as exc:
            if (
                not self._running
                or self._shutdown.is_set()
                or self._loop is None
                or self._loop.is_closed()
                or "Event loop is closed" in str(exc)
            ):
                logger.debug(f"Publisher loop stopping for {ez_pub.topic}: {exc}")
            else:
                logger.exception(f"Error in publisher loop for {ez_pub.topic}")
        except Exception:
            logger.exception(f"Error in publisher loop for {ez_pub.topic}")

    async def _async_cleanup(self) -> None:
        """Cleanup all clients and sidecar."""
        logger.debug("Cleaning up EzGuiBridge")

        # Stop sidecar first
        if self._sidecar is not None:
            self._sidecar.stop()
            self._sidecar = None

        if self._tasks:
            for task in list(self._tasks):
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        if self._context_entered:
            await self._context.__aexit__(None, None, None)
            self._context_entered = False
