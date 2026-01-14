"""Tests for ProcessorChain."""

from enum import Enum
from typing import Any
from typing import AsyncGenerator
from unittest.mock import MagicMock

import ezmsg.core as ez

from ezmsg.qt.chain import ProcessorChain
from ezmsg.qt.chain import ProcessorStage


class TestTopic(Enum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"


class DoubleProcessor(ez.Unit):
    """Test processor that doubles numeric values."""

    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg * 2


def test_processor_chain_creation():
    """ProcessorChain can be created with source topic."""
    chain = ProcessorChain(source_topic=TestTopic.INPUT, parent_widget=None)
    assert chain.source_topic == TestTopic.INPUT
    assert len(chain.stages) == 0


def test_processor_chain_add_stage():
    """ProcessorChain.process() adds a stage and returns self for chaining."""
    chain = ProcessorChain(source_topic=TestTopic.INPUT, parent_widget=None)
    result = chain.process(DoubleProcessor)

    assert result is chain  # Returns self for chaining
    assert len(chain.stages) == 1
    assert chain.stages[0].unit_class is DoubleProcessor
    assert chain.stages[0].settings is None
    assert chain.stages[0].in_process is False


def test_processor_chain_with_settings():
    """ProcessorChain.process() accepts settings."""

    class MySettings(ez.Settings):
        factor: int = 2

    class MyProcessor(ez.Unit):
        SETTINGS = MySettings
        INPUT = ez.InputStream(float)
        OUTPUT = ez.OutputStream(float)

    settings = MySettings(factor=3)
    chain = ProcessorChain(source_topic=TestTopic.INPUT, parent_widget=None)
    chain.process(MyProcessor, settings=settings)

    assert chain.stages[0].settings is settings


def test_processor_chain_in_process_flag():
    """ProcessorChain.process() respects in_process flag."""
    chain = ProcessorChain(source_topic=TestTopic.INPUT, parent_widget=None)
    chain.process(DoubleProcessor, in_process=True)

    assert chain.stages[0].in_process is True


def test_processor_chain_chaining():
    """Multiple process() calls chain correctly."""
    chain = ProcessorChain(source_topic=TestTopic.INPUT, parent_widget=None)
    chain.process(DoubleProcessor).process(DoubleProcessor, in_process=True)

    assert len(chain.stages) == 2
    assert chain.stages[0].in_process is False
    assert chain.stages[1].in_process is True
