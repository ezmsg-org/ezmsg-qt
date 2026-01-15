"""Tests for sidecar GraphRunner."""

from enum import Enum
from typing import AsyncGenerator

import ezmsg.core as ez

from ezmsg.qt.sidecar import build_sidecar_components


class DemoTopic(Enum):
    INPUT = "INPUT"


class DoubleProcessor(ez.Unit):
    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg * 2


def test_build_sidecar_components_empty():
    """Empty chain list produces no components."""
    components, connections = build_sidecar_components([])
    assert components == {}
    assert connections == []


def test_build_sidecar_components_single_parallel_group():
    """Single parallel group creates gate + processors."""
    from ezmsg.qt.chain import ProcessorChain

    chain = ProcessorChain(DemoTopic.INPUT, parent=None)
    chain._chain_id = "test_chain"
    chain.parallel(DoubleProcessor)

    components, connections = build_sidecar_components([chain])

    assert "test_chain_gate" in components
    assert "test_chain_proc_0" in components
    assert len(connections) > 0


def test_build_sidecar_components_multiple_processors_in_group():
    """Multiple processors in a group are chained together."""
    from ezmsg.qt.chain import ProcessorChain

    chain = ProcessorChain(DemoTopic.INPUT, parent=None)
    chain._chain_id = "test_chain"
    chain.parallel(DoubleProcessor, DoubleProcessor)

    components, connections = build_sidecar_components([chain])

    assert "test_chain_gate" in components
    assert "test_chain_proc_0" in components
    assert "test_chain_proc_1" in components


def test_build_sidecar_components_ignores_local_groups():
    """Local groups are not included in sidecar components."""
    from ezmsg.qt.chain import ProcessorChain

    chain = ProcessorChain(DemoTopic.INPUT, parent=None)
    chain._chain_id = "test_chain"
    chain.local(DoubleProcessor)

    components, connections = build_sidecar_components([chain])

    # No parallel groups means no components
    assert components == {}
    assert connections == []


def test_build_sidecar_components_mixed_groups():
    """Mixed parallel and local groups - only parallel in sidecar."""
    from ezmsg.qt.chain import ProcessorChain

    chain = ProcessorChain(DemoTopic.INPUT, parent=None)
    chain._chain_id = "test_chain"
    chain.parallel(DoubleProcessor).local(DoubleProcessor)

    components, connections = build_sidecar_components([chain])

    # Only the parallel processor should be in sidecar
    assert "test_chain_gate" in components
    assert "test_chain_proc_0" in components
    # Local processor (proc_1) should NOT be in sidecar
    assert "test_chain_proc_1" not in components
