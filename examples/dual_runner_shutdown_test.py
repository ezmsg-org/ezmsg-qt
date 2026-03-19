#!/usr/bin/env python3
"""
Minimal reproduction and fix verification for GraphRunner shutdown issue.

PROBLEM
=======
When a "session-like" component (background thread with async event loop) creates
a sidecar GraphRunner, calling sidecar.stop() from within the async context
causes a deadlock.

ROOT CAUSE
==========
The deadlock occurs due to a circular dependency:

1. Background thread's event loop calls sidecar.stop() (blocking call)
2. sidecar.stop() waits for sidecar processes to exit
3. Sidecar processes need to communicate with GraphServer during shutdown
   (unregistering subscribers, closing channels, etc.)
4. GraphServer notifications need to be processed by... the blocked event loop
5. Deadlock: event loop waiting for sidecar, sidecar waiting for event loop

This manifests as:
- sidecar.stop() hangs indefinitely
- Leaked semaphores and shared_memory objects on forced termination
- "subscriber backpressure" warnings from the primary runner

SOLUTION
========
Call sidecar.stop() from the MAIN THREAD (outside the async context), not from
within the background thread's async cleanup. This allows the event loop to
continue processing GraphServer notifications while the sidecar shuts down.

In EzSession, this means:
- Move sidecar.stop() from _async_cleanup() to __exit__()
- Call it BEFORE signaling the background thread to stop

RELATED ISSUE: STARTUP DEADLOCK
===============================
A similar deadlock can occur during startup if:
1. Session creates a subscriber for a topic (e.g., OUTPUT_TOPIC)
2. Sidecar starts and creates a publisher for the same topic
3. GraphServer tries to notify the session subscriber about the new publisher
4. But the session event loop is blocked waiting for sidecar.start() to complete

This is avoided by starting the sidecar BEFORE creating subscribers for its
output topics.
"""

import asyncio
import sys
import threading
import time
from collections.abc import AsyncGenerator

import ezmsg.core as ez
from ezmsg.core.backend import GraphRunner

# Add parent path to import our gate
sys.path.insert(0, str(__file__).rsplit("/", 2)[0] + "/src")
from ezmsg.core.graphcontext import GraphContext

from ezmsg.qt.gate import MessageGate
from ezmsg.qt.gate import MessageGateSettings


class DataGenerator(ez.Unit):
    """Simple unit that generates data at 20 Hz."""

    OUTPUT = ez.OutputStream(float)

    @ez.publisher(OUTPUT)
    async def generate(self) -> AsyncGenerator:
        counter = 0.0
        while True:
            yield self.OUTPUT, counter
            counter += 1.0
            await asyncio.sleep(0.05)  # 20 Hz


class DataReceiver(ez.Unit):
    """Simple unit that receives and prints data."""

    INPUT = ez.InputStream(float)

    @ez.subscriber(INPUT)
    async def receive(self, msg: float) -> None:
        print(f"[Receiver] Got: {msg}", flush=True)


# Chain components to match our sidecar setup
class Passthrough1(ez.Unit):
    """First passthrough in chain."""

    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        if int(msg) % 20 == 0:  # Print every 20th message
            print(f"[P1] {msg}", flush=True)
        yield self.OUTPUT, msg


class Passthrough2(ez.Unit):
    """Second passthrough in chain."""

    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg


class Passthrough3(ez.Unit):
    """Third passthrough in chain."""

    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        if int(msg) % 20 == 0:  # Print every 20th message
            print(f"[P3] {msg}", flush=True)
        yield self.OUTPUT, msg


class SessionLikeContext:
    """
    Mimics the EzSession runtime - has its own async loop in a background thread,
    with a GraphContext that creates its own subscribers.
    """

    def __init__(self, graph_address):
        self._graph_address = graph_address
        self._loop = None
        self._thread = None
        self._context = None
        self._sidecar = None
        self._shutdown = threading.Event()
        self._setup_complete = threading.Event()
        self._tasks = set()

    def __enter__(self):
        self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._thread.start()
        # Wait for async setup AND sidecar to be ready
        self._setup_complete.wait(timeout=30.0)
        return self

    def __exit__(self, *args):
        print("[Session] __exit__ starting...", flush=True)
        self._shutdown.set()

        # FIX: Stop sidecar from MAIN THREAD, not from async context!
        # This avoids the deadlock where sidecar needs event loop to process
        # GraphServer notifications, but event loop is blocked on sidecar.stop()
        if self._sidecar is not None:
            print("[Session] Stopping sidecar from main thread...", flush=True)
            self._sidecar.stop()
            self._sidecar = None
            print("[Session] Sidecar stopped", flush=True)

        if self._thread is not None:
            print("[Session] Joining background thread...", flush=True)
            self._thread.join(timeout=10.0)
            if self._thread.is_alive():
                print("[Session] WARNING: Thread still alive after 10s!")
            else:
                print("[Session] Thread joined", flush=True)
        print("[Session] __exit__ complete", flush=True)

    def _run_async_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        finally:
            self._loop.close()

    async def _async_main(self):
        print("[Session] _async_main starting...", flush=True)
        # Create our own GraphContext (like EzSession does)
        self._context = GraphContext(self._graph_address)
        await self._context.__aenter__()
        print("[Session] GraphContext entered", flush=True)

        # Create and start sidecar FIRST (like the real session runtime does)
        print("[Session] Creating sidecar from async context...", flush=True)
        gate = MessageGate()
        gate.apply_settings(MessageGateSettings(start_open=True))
        p1 = Passthrough1()
        p2 = Passthrough2()
        self._sidecar = GraphRunner(
            components={"gate": gate, "p1": p1, "p2": p2},
            connections=[
                ("DATA_TOPIC", gate.INPUT),
                (gate.OUTPUT, p1.INPUT),
                (p1.OUTPUT, p2.INPUT),
                (p2.OUTPUT, "OUTPUT_TOPIC"),
                ("GATE_CONTROL", gate.INPUT_GATE),
            ],
            graph_address=self._graph_address,
        )
        print("[Session] Starting sidecar (sync call from async)...", flush=True)
        self._sidecar.start()  # BLOCKING - like the real session runtime
        print("[Session] Sidecar started", flush=True)

        await asyncio.sleep(0.5)  # Like the real session runtime does

        # NOW create subscriber for sidecar's output
        #  (like the real session does after sidecar start)
        print("[Session] Creating subscriber for OUTPUT_TOPIC...", flush=True)
        sub = await self._context.subscriber("OUTPUT_TOPIC")
        print("[Session] Subscriber created", flush=True)
        task = asyncio.create_task(self._subscriber_loop(sub))
        self._tasks.add(task)

        self._setup_complete.set()
        print("[Session] Setup complete, waiting for shutdown...", flush=True)

        # Wait for shutdown
        while not self._shutdown.is_set():
            await asyncio.sleep(0.1)

        # Cleanup - sidecar is already stopped from __exit__ (main thread)
        print("[Session] Async cleanup starting...", flush=True)

        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._context.__aexit__(None, None, None)
        print("[Session] Async cleanup complete", flush=True)

    async def _subscriber_loop(self, sub):
        """Receive messages from OUTPUT_TOPIC (like EzSession does)."""
        try:
            while not self._shutdown.is_set():
                msg = await sub.recv()
                if int(msg) % 20 == 0:
                    print(f"[SessionSub] {msg}", flush=True)
        except asyncio.CancelledError:
            pass


def main():
    print("=" * 60)
    print("Dual GraphRunner Shutdown Test (Session-like setup)")
    print("=" * 60)

    # Create primary runner with data generator
    generator = DataGenerator()
    primary = GraphRunner(
        components={"generator": generator},
        connections=[
            (generator.OUTPUT, "DATA_TOPIC"),
        ],
    )

    print("[Main] Starting primary runner...", flush=True)
    primary.start()
    print(f"[Main] Primary started, graph_address={primary.graph_address}", flush=True)

    # Give primary time to initialize
    time.sleep(0.5)

    # Use our session-like context (mimics EzSession)
    print("[Main] Creating session-like context...", flush=True)
    try:
        with SessionLikeContext(primary.graph_address) as _:
            print("[Main] Session active, running for 3 seconds...", flush=True)
            time.sleep(3)
            print(
                "[Main] Exiting session context (will try to stop sidecar)...",
                flush=True,
            )
        print("[Main] Session context exited", flush=True)
    finally:
        print("[Main] Stopping primary...", flush=True)
        if primary.running:
            primary.stop()
        print("[Main] Primary stopped", flush=True)

    print("[Main] Test complete")


if __name__ == "__main__":
    main()
