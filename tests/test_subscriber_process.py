"""Tests for EzSubscriber.process() method."""

from enum import Enum
from typing import AsyncGenerator

import ezmsg.core as ez
from qtpy import QtCore

from ezmsg.qt.subscriber import EzSubscriber
from ezmsg.qt.chain import ProcessorChain


class DemoTopic(Enum):
    DATA = "DATA"


class DoubleProcessor(ez.Unit):
    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg * 2


def test_subscriber_process_returns_chain(qtbot):
    """EzSubscriber.process() returns a ProcessorChain."""
    sub = EzSubscriber(DemoTopic.DATA)
    result = sub.process(DoubleProcessor)

    assert isinstance(result, ProcessorChain)
    assert result.source_topic == DemoTopic.DATA


def test_subscriber_process_chain_is_registered(qtbot):
    """ProcessorChain is registered for later setup."""
    from ezmsg.qt.bridge import _pending_chains

    initial_count = len(_pending_chains)
    sub = EzSubscriber(DemoTopic.DATA)
    chain = sub.process(DoubleProcessor)
    chain.connect(lambda x: None)  # Finalize chain

    assert len(_pending_chains) == initial_count + 1
    assert _pending_chains[-1] is chain
