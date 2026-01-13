"""
ezmsg_toy running in a background thread.

This tests that ezmsg can run in a daemon thread while the main thread
does other work (simulating what we'd need for Qt integration).
"""

import threading
import time

# Import the system from ezmsg_toy
from ezmsg_toy import TestSystem, TestSystemSettings

import ezmsg.core as ez


def main():
    print("[Main] Creating ezmsg system...")
    system = TestSystem(TestSystemSettings(name="Threaded"))

    print("[Main] Starting ezmsg in background thread...")
    ez_thread = threading.Thread(
        target=lambda: ez.run(
            SYSTEM=system,
            connections=[
                (system.PING.OUTPUT, "GLOBAL_PING_TOPIC"),
            ],
        ),
        daemon=True,
        name="ezmsg",
    )
    ez_thread.start()

    print("[Main] ezmsg thread started, main thread is free...")
    print("[Main] Simulating main thread work (like Qt event loop)...")

    # Simulate main thread doing work for 10 seconds
    for i in range(10):
        print(f"[Main] Main thread tick {i + 1}/10")
        time.sleep(1.0)

    print("[Main] Main thread done, exiting (daemon thread will be killed)")


if __name__ == "__main__":
    main()
