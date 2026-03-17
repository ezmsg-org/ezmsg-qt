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
    components, connections, compiled = build_sidecar_components([])
    assert components == {}
    assert connections == []
    assert compiled == []


def test_build_sidecar_components_single_parallel_group():
    """Single parallel group creates gate + processors."""
    from ezmsg.qt.chain import ProcessorChain

    chain = ProcessorChain(DemoTopic.INPUT, parent=None)
    chain._chain_id = "test_chain"
    chain.parallel(DoubleProcessor).connect(lambda _msg: None)

    components, connections, compiled = build_sidecar_components([chain])

    assert "pipeline_test_chain" in components
    assert len(connections) > 0
    assert compiled[0].output_topic == "_qt.test_chain.out"


def test_build_sidecar_components_multiple_processors_in_group():
    """Multiple processors in a group are chained together."""
    from ezmsg.qt.chain import ProcessorChain

    chain = ProcessorChain(DemoTopic.INPUT, parent=None)
    chain._chain_id = "test_chain"
    chain.parallel(DoubleProcessor, DoubleProcessor).connect(lambda _msg: None)

    components, connections, _compiled = build_sidecar_components([chain])

    pipeline = components["pipeline_test_chain"]
    group = getattr(pipeline, "group_0")
    assert hasattr(group, "proc_0")
    assert hasattr(group, "proc_1")


def test_build_sidecar_components_ignores_local_groups():
    """Local groups are compiled into the shared sidecar process."""
    from ezmsg.qt.chain import ProcessorChain

    chain = ProcessorChain(DemoTopic.INPUT, parent=None)
    chain._chain_id = "test_chain"
    chain.local(DoubleProcessor).connect(lambda _msg: None)

    components, connections, compiled = build_sidecar_components([chain])

    assert "pipeline_test_chain" in components
    assert connections
    assert compiled


def test_build_sidecar_components_mixed_groups():
    """Mixed groups retain process boundaries in the compiled collection."""
    from ezmsg.qt.chain import ProcessorChain

    chain = ProcessorChain(DemoTopic.INPUT, parent=None)
    chain._chain_id = "test_chain"
    chain.parallel(DoubleProcessor).local(DoubleProcessor).connect(lambda _msg: None)

    components, connections, _compiled = build_sidecar_components([chain])

    pipeline = components["pipeline_test_chain"]
    group_0 = getattr(pipeline, "group_0")
    group_1 = getattr(pipeline, "group_1")
    process_components = pipeline.process_components()
    assert group_0 in process_components
    assert group_1 not in process_components
