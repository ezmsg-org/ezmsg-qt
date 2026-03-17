"""Tests for ProcessorChain."""

from enum import Enum
from typing import AsyncGenerator

import ezmsg.core as ez

from ezmsg.qt.chain import ProcessorChain
from ezmsg.qt.chain import ProcessorGroup
from ezmsg.qt.chain import _to_unit


class DemoTopic(Enum):
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


class DoubleSettings(ez.Settings):
    factor: int = 2


class ConfigurableDouble(ez.Unit):
    """Test processor with configurable settings."""

    SETTINGS = DoubleSettings
    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg * self.SETTINGS.factor


def test_processor_chain_creation():
    """ProcessorChain can be created with source topic."""
    chain = ProcessorChain(source_topic=DemoTopic.INPUT, parent=None)
    assert chain.source_topic == DemoTopic.INPUT
    assert len(chain.groups) == 0


def test_processor_chain_parallel():
    """ProcessorChain.parallel() adds a parallel group."""
    chain = ProcessorChain(source_topic=DemoTopic.INPUT, parent=None)
    result = chain.parallel(DoubleProcessor)

    assert result is chain  # Returns self for chaining
    assert len(chain.groups) == 1
    assert chain.groups[0].mode == "process"
    assert len(chain.groups[0].processors) == 1
    assert chain.groups[0].processors[0] is DoubleProcessor


def test_processor_chain_local():
    """ProcessorChain.local() adds a local group."""
    chain = ProcessorChain(source_topic=DemoTopic.INPUT, parent=None)
    result = chain.local(DoubleProcessor)

    assert result is chain  # Returns self for chaining
    assert len(chain.groups) == 1
    assert chain.groups[0].mode == "shared"


def test_processor_chain_multiple_processors_in_group():
    """Multiple processors in a single parallel/local call are grouped together."""
    chain = ProcessorChain(source_topic=DemoTopic.INPUT, parent=None)
    chain.parallel(DoubleProcessor, ConfigurableDouble)

    assert len(chain.groups) == 1
    assert len(chain.groups[0].processors) == 2
    assert chain.groups[0].processors[0] is DoubleProcessor
    assert chain.groups[0].processors[1] is ConfigurableDouble


def test_processor_chain_multiple_groups():
    """Multiple parallel/local calls create separate groups."""
    chain = ProcessorChain(source_topic=DemoTopic.INPUT, parent=None)
    chain.parallel(DoubleProcessor).parallel(ConfigurableDouble).local(DoubleProcessor)

    assert len(chain.groups) == 3
    assert chain.groups[0].mode == "process"
    assert chain.groups[1].mode == "process"
    assert chain.groups[2].mode == "shared"


def test_processor_chain_with_settings_tuple():
    """ProcessorChain accepts (UnitClass, settings) tuples."""
    settings = DoubleSettings(factor=3)
    chain = ProcessorChain(source_topic=DemoTopic.INPUT, parent=None)
    chain.parallel((ConfigurableDouble, settings))

    assert len(chain.groups) == 1
    spec = chain.groups[0].processors[0]
    assert isinstance(spec, tuple)
    assert spec[0] is ConfigurableDouble
    assert spec[1] is settings


def test_to_unit_with_class():
    """_to_unit converts Unit class to instance."""
    unit = _to_unit(DoubleProcessor)
    assert isinstance(unit, DoubleProcessor)


def test_to_unit_with_settings_tuple():
    """_to_unit converts (class, settings) tuple to configured instance."""
    settings = DoubleSettings(factor=5)
    unit = _to_unit((ConfigurableDouble, settings))
    assert isinstance(unit, ConfigurableDouble)
    assert unit.SETTINGS.factor == 5


def test_processor_chain_connect():
    """ProcessorChain.connect() sets the handler."""
    chain = ProcessorChain(source_topic=DemoTopic.INPUT, parent=None)

    def handler(msg):
        pass

    result = chain.connect(handler)
    assert result is chain
    assert chain.handler is handler
