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


def test_build_sidecar_components_single_stage():
    """Single in_process stage creates gate + processor."""
    from ezmsg.qt.chain import ProcessorChain

    chain = ProcessorChain(DemoTopic.INPUT, parent_widget=None)
    chain._chain_id = "test_chain"
    chain.process(DoubleProcessor, in_process=True)

    components, connections = build_sidecar_components([chain])

    assert "test_chain_gate" in components
    assert "test_chain_proc_0" in components
    assert len(connections) > 0
