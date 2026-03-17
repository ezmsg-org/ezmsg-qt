"""EzGuiBridge - explicit runtime ownership for Qt/ezmsg integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import signal
import socket
import threading
from typing import TYPE_CHECKING
from typing import Any
import weakref

from ezmsg.core.backend import GraphRunner
from ezmsg.core.graphcontext import GraphContext
from ezmsg.core.netprotocol import AddressType
from qtpy import QtCore
from qtpy import QtWidgets

from .gate import GateMessage
from .sidecar import CompiledPipeline
from .sidecar import build_sidecar_components
from .sidecar import normalize_topic

if TYPE_CHECKING:
    from .chain import ProcessorChain
    from .publisher import EzPublisher
    from .subscriber import EzSubscriber

logger = logging.getLogger(__name__)


@dataclass
class _SubscriberRuntime:
    client: Any
    task: asyncio.Task[None]


@dataclass
class _PublisherRuntime:
    client: Any
    task: asyncio.Task[None]


@dataclass
class _PipelineRuntime:
    compiled: CompiledPipeline
    client: Any
    task: asyncio.Task[None]
    gate_publisher: Any | None = None


class _QtSignalDispatcher(QtCore.QObject):
    """Dispatch work onto the Qt main thread."""

    call_signal = QtCore.Signal(object, object)  # pyright: ignore[reportPrivateImportUsage]

    def __init__(self, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self.call_signal.connect(self._on_call)

    def _on_call(self, func, args) -> None:
        func(*args)

    def schedule(self, func, *args) -> None:
        self.call_signal.emit(func, args)


class EzGuiBridge:
    """Bridge Qt widgets to ezmsg channels with explicit ownership."""

    def __init__(
        self,
        app: QtWidgets.QApplication,
        graph_address: AddressType | None = None,
    ):
        self.app = app
        self._context = GraphContext(graph_address)
        self._context_entered = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown = threading.Event()
        self._setup_complete = threading.Event()
        self._setup_error: BaseException | None = None
        self._running = False
        self._dispatcher = _QtSignalDispatcher(app)
        self._tasks: set[asyncio.Task[None]] = set()

        self._subscribers: dict[int, EzSubscriber] = {}
        self._publishers: dict[int, EzPublisher] = {}
        self._pipelines: dict[int, ProcessorChain] = {}

        self._subscriber_runtime: dict[int, _SubscriberRuntime] = {}
        self._publisher_runtime: dict[int, _PublisherRuntime] = {}
        self._pipeline_runtime: dict[int, _PipelineRuntime] = {}

        self._compiled_pipelines: list[CompiledPipeline] = []
        self._sidecar: GraphRunner | None = None
        self._chain_counter = 0

        self._prev_sigint_handler = None
        self._sigint_notifier: QtCore.QSocketNotifier | None = None
        self._wakeup_sock_r: socket.socket | None = None
        self._wakeup_sock_w: socket.socket | None = None
        self._wakeup_prev_fd: int | None = None

    def attach(self, attachable):
        """Attach a subscriber, publisher, or processor pipeline to this bridge."""
        from .chain import ProcessorChain
        from .publisher import EzPublisher
        from .subscriber import EzSubscriber

        if isinstance(attachable, EzSubscriber):
            self._attach_subscriber(attachable)
        elif isinstance(attachable, EzPublisher):
            self._attach_publisher(attachable)
        elif isinstance(attachable, ProcessorChain):
            self._attach_pipeline(attachable)
        else:
            raise TypeError(f"Unsupported attachable type: {type(attachable)!r}")

        return attachable

    def detach(self, attachable) -> None:
        """Detach a subscriber or publisher from this bridge."""
        from .publisher import EzPublisher
        from .subscriber import EzSubscriber

        if isinstance(attachable, EzSubscriber):
            self._detach_subscriber(id(attachable))
            return
        if isinstance(attachable, EzPublisher):
            self._detach_publisher(id(attachable))
            return

        raise TypeError("Only EzSubscriber and EzPublisher can be detached at runtime")

    def _attach_subscriber(self, subscriber: EzSubscriber) -> None:
        key = id(subscriber)
        if key in self._subscribers:
            return

        subscriber._bind_bridge(self)
        self._subscribers[key] = subscriber
        self._bind_destroyed(subscriber, self._detach_subscriber, key)

        if self._running and self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._setup_subscriber(subscriber), self._loop
            ).result()

    def _attach_publisher(self, publisher: EzPublisher) -> None:
        key = id(publisher)
        if key in self._publishers:
            return

        publisher._bind_bridge(self)
        self._publishers[key] = publisher
        self._bind_destroyed(publisher, self._detach_publisher, key)

        if self._running and self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._setup_publisher(publisher), self._loop
            ).result()

    def _attach_pipeline(self, chain: ProcessorChain) -> None:
        key = id(chain)
        if key in self._pipelines:
            return
        if self._running:
            raise RuntimeError(
                "Processor pipelines must be attached before bridge start"
            )

        chain._validate()
        chain._bind_bridge(self)
        if chain._chain_id is None:
            chain._chain_id = f"chain_{self._chain_counter}"
            self._chain_counter += 1
        self._pipelines[key] = chain

    def _bind_destroyed(self, obj: QtCore.QObject, callback, key: int) -> None:
        obj.destroyed.connect(lambda *_args, _key=key: callback(_key))

    def _detach_subscriber(self, key: int) -> None:
        subscriber = self._subscribers.pop(key, None)
        if subscriber is None:
            return
        runtime = self._subscriber_runtime.pop(key, None)
        if runtime is None or self._loop is None or self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._close_subscriber_runtime(runtime), self._loop
            ).result()
        except RuntimeError:
            logger.debug("Subscriber detached after loop shutdown")

    def _detach_publisher(self, key: int) -> None:
        publisher = self._publishers.pop(key, None)
        if publisher is None:
            return
        runtime = self._publisher_runtime.pop(key, None)
        if runtime is None or self._loop is None or self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._close_publisher_runtime(runtime), self._loop
            ).result()
        except RuntimeError:
            logger.debug("Publisher detached after loop shutdown")

    def __enter__(self) -> EzGuiBridge:
        self._running = True
        self._setup_error = None
        self._shutdown.clear()
        self._install_sigint_handler()

        self._thread = threading.Thread(
            target=self._run_async_loop, daemon=True, name="EzGuiBridge"
        )
        self._thread.start()

        if not self._setup_complete.wait(timeout=30.0):
            raise RuntimeError("EzGuiBridge setup timed out")
        if self._setup_error is not None:
            if self._thread is not None:
                self._thread.join(timeout=5.0)
            raise RuntimeError("EzGuiBridge setup failed") from self._setup_error

        return self

    def __exit__(self, exc_type, exc, exc_tb) -> bool | None:
        self._running = False
        if exc_type is KeyboardInterrupt:
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.quit()

        if self._sidecar is not None:
            try:
                self._sidecar.stop()
            finally:
                self._sidecar = None

        self._shutdown.set()

        if self._thread is not None:
            self._thread.join(timeout=10.0)
            self._thread = None

        self._restore_sigint_handler()
        if exc_type is KeyboardInterrupt:
            return False
        return None

    def _run_async_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        except Exception:
            logger.exception("Error in EzGuiBridge async loop")
        finally:
            self._loop.close()
            self._loop = None

    async def _async_main(self) -> None:
        try:
            try:
                await self._context.__aenter__()
                self._context_entered = True
                await self._async_setup()
            except BaseException as exc:
                self._setup_error = exc
            finally:
                self._setup_complete.set()

            if self._setup_error is None:
                while not self._shutdown.is_set():
                    await asyncio.sleep(0.1)
        finally:
            await self._async_cleanup()

        if self._setup_error is not None:
            raise self._setup_error

    async def _async_setup(self) -> None:
        await self._setup_sidecar()

        for subscriber in list(self._subscribers.values()):
            await self._setup_subscriber(subscriber)

        for publisher in list(self._publishers.values()):
            await self._setup_publisher(publisher)

        for compiled in self._compiled_pipelines:
            await self._setup_pipeline_runtime(compiled)

    async def _setup_sidecar(self) -> None:
        pipelines = list(self._pipelines.values())
        if not pipelines:
            self._compiled_pipelines = []
            return

        components, connections, compiled = build_sidecar_components(pipelines)
        runner = GraphRunner(
            components=components,
            connections=connections,
            graph_address=self._context.graph_address,
        )
        await asyncio.to_thread(runner.start)
        await self._context.sync(timeout=5.0)
        self._sidecar = runner
        self._compiled_pipelines = compiled

    async def _setup_subscriber(self, ez_sub: EzSubscriber) -> None:
        key = id(ez_sub)
        if key in self._subscriber_runtime:
            return

        topic = normalize_topic(ez_sub.topic)
        sub_kwargs: dict[str, object] = {}
        if ez_sub.leaky:
            sub_kwargs["leaky"] = True
            if ez_sub.max_queue is not None:
                sub_kwargs["max_queue"] = ez_sub.max_queue

        client = await self._context.subscriber(topic, **sub_kwargs)
        ez_sub._sub = client
        task = asyncio.create_task(
            self._subscriber_loop(ez_sub, client),
            name=f"sub-{topic}",
        )
        self._track_task(task)
        self._subscriber_runtime[key] = _SubscriberRuntime(client=client, task=task)

    async def _setup_publisher(self, ez_pub: EzPublisher) -> None:
        key = id(ez_pub)
        if key in self._publisher_runtime:
            return

        topic = normalize_topic(ez_pub.topic)
        client = await self._context.publisher(topic)
        ez_pub._pub = client
        if self._loop is None:
            raise RuntimeError("Bridge loop is not initialized")
        ez_pub._bind_runtime(self._loop)
        task = asyncio.create_task(
            self._publisher_loop(ez_pub, client),
            name=f"pub-{topic}",
        )
        self._track_task(task)
        self._publisher_runtime[key] = _PublisherRuntime(client=client, task=task)

    async def _setup_pipeline_runtime(self, compiled: CompiledPipeline) -> None:
        key = id(compiled.chain)
        client = await self._context.subscriber(compiled.output_topic)
        task = asyncio.create_task(
            self._pipeline_output_loop(compiled, client),
            name=f"pipeline-{compiled.chain._chain_id}",
        )
        self._track_task(task)

        gate_publisher = None
        chain = compiled.chain
        if chain.auto_gate and chain.parent_widget is not None:
            gate_publisher = await self._context.publisher(compiled.gate_topic)
            await gate_publisher.broadcast(
                GateMessage(open=chain.parent_widget.isVisible())
            )
            self._dispatcher.schedule(self._setup_auto_gate, chain)

        self._pipeline_runtime[key] = _PipelineRuntime(
            compiled=compiled,
            client=client,
            task=task,
            gate_publisher=gate_publisher,
        )

    def _setup_auto_gate(self, chain: ProcessorChain) -> None:
        from .visibility import VisibilityFilter

        widget = chain.parent_widget
        if widget is None:
            return

        chain_ref = weakref.ref(chain)

        def on_visibility(visible: bool) -> None:
            current_chain = chain_ref()
            if current_chain is None or self._loop is None or not self._running:
                return
            asyncio.run_coroutine_threadsafe(
                self._send_gate_message(current_chain, visible), self._loop
            )

        event_filter = VisibilityFilter(on_visibility, parent=widget)
        widget.installEventFilter(event_filter)
        setattr(chain, "_visibility_filter", event_filter)

    async def _send_gate_message(self, chain: ProcessorChain, open: bool) -> None:
        runtime = self._pipeline_runtime.get(id(chain))
        if runtime is None or runtime.gate_publisher is None:
            return
        await runtime.gate_publisher.broadcast(GateMessage(open=open))

    async def _subscriber_loop(self, ez_sub: EzSubscriber, sub) -> None:
        rate = None
        if ez_sub.throttle_hz is not None:
            from ezmsg.util.rate import Rate

            rate = Rate(float(ez_sub.throttle_hz))

        try:
            while self._running:
                msg = await sub.recv()
                self._dispatcher.schedule(ez_sub._on_message, msg)
                if rate is not None:
                    await rate.sleep()
        except asyncio.CancelledError:
            logger.debug("Subscriber loop cancelled for %s", ez_sub.topic)
        except Exception:
            logger.exception("Error in subscriber loop for %s", ez_sub.topic)

    async def _publisher_loop(self, ez_pub: EzPublisher, pub) -> None:
        try:
            while self._running:
                msg = await ez_pub._get_message()
                await pub.broadcast(msg)
        except asyncio.CancelledError:
            logger.debug("Publisher loop cancelled for %s", ez_pub.topic)
        except Exception:
            logger.exception("Error in publisher loop for %s", ez_pub.topic)

    async def _pipeline_output_loop(self, compiled: CompiledPipeline, sub) -> None:
        try:
            while self._running:
                msg = await sub.recv()
                if compiled.chain.handler is not None:
                    self._dispatcher.schedule(compiled.chain.handler, msg)
        except asyncio.CancelledError:
            logger.debug("Pipeline loop cancelled for %s", compiled.chain._chain_id)
        except Exception:
            logger.exception("Error in pipeline loop for %s", compiled.chain._chain_id)

    def _track_task(self, task: asyncio.Task[None]) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _close_subscriber_runtime(self, runtime: _SubscriberRuntime) -> None:
        runtime.task.cancel()
        await asyncio.gather(runtime.task, return_exceptions=True)
        runtime.client.close()
        await runtime.client.wait_closed()

    async def _close_publisher_runtime(self, runtime: _PublisherRuntime) -> None:
        runtime.task.cancel()
        await asyncio.gather(runtime.task, return_exceptions=True)
        runtime.client.close()
        await runtime.client.wait_closed()

    async def _close_pipeline_runtime(self, runtime: _PipelineRuntime) -> None:
        runtime.task.cancel()
        await asyncio.gather(runtime.task, return_exceptions=True)
        runtime.client.close()
        await runtime.client.wait_closed()
        if runtime.gate_publisher is not None:
            runtime.gate_publisher.close()
            await runtime.gate_publisher.wait_closed()

    async def _async_cleanup(self) -> None:
        for runtime in list(self._subscriber_runtime.values()):
            await self._close_subscriber_runtime(runtime)
        self._subscriber_runtime.clear()

        for runtime in list(self._publisher_runtime.values()):
            await self._close_publisher_runtime(runtime)
        self._publisher_runtime.clear()

        for runtime in list(self._pipeline_runtime.values()):
            await self._close_pipeline_runtime(runtime)
        self._pipeline_runtime.clear()

        if self._tasks:
            for task in list(self._tasks):
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        if self._context_entered:
            await self._context.__aexit__(None, None, None)
            self._context_entered = False

    def _install_sigint_handler(self) -> None:
        try:
            self._prev_sigint_handler = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, self._handle_sigint)
            self._install_signal_wakeup()
        except (ValueError, RuntimeError) as exc:
            logger.debug("Unable to install SIGINT handler: %s", exc)

    def _restore_sigint_handler(self) -> None:
        self._restore_signal_wakeup()
        if self._prev_sigint_handler is None:
            return
        try:
            signal.signal(signal.SIGINT, self._prev_sigint_handler)
        except (ValueError, RuntimeError) as exc:
            logger.debug("Unable to restore SIGINT handler: %s", exc)
        finally:
            self._prev_sigint_handler = None

    def _handle_sigint(self, _sig, _frame) -> None:
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
            logger.debug("Unable to install signal wakeup fd: %s", exc)
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
                logger.debug("Unable to restore wakeup fd: %s", exc)
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
