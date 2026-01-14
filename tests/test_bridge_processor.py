"""Tests for bridge-thread processor execution."""

import asyncio
from enum import Enum
from typing import AsyncGenerator

import ezmsg.core as ez
from qtpy import QtWidgets

from ezmsg.qt.bridge import EzGuiBridge
from ezmsg.qt.bridge import _pending_chains
from ezmsg.qt.subscriber import EzSubscriber


class DemoTopic(Enum):
    INPUT = "INPUT"


class DoubleProcessor(ez.Unit):
    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg * 2


def test_bridge_registers_chains(qtbot):
    """EzGuiBridge processes pending chains on enter."""
    _pending_chains.clear()

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    received = []
    sub = EzSubscriber(DemoTopic.INPUT)
    chain = sub.process(DoubleProcessor, in_process=False)
    chain.connect(received.append)

    assert len(_pending_chains) == 1

    # Note: Full integration test requires running GraphServer
    # This test verifies registration works
