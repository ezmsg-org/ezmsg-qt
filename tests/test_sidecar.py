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
    components, connections, process_components, compiled = build_sidecar_components([])
    assert components == {}
    assert connections == []
    assert process_components == ()
    assert compiled == []


def test_build_sidecar_components_single_parallel_group():
    """Single parallel group creates gate + processors."""
    from ezmsg.qt.chain import ProcessorChain

    chain = ProcessorChain(DemoTopic.INPUT, parent=None)
    chain._chain_id = "test_chain"
    chain.parallel(DoubleProcessor).connect(lambda _msg: None)

    components, connections, process_components, compiled = build_sidecar_components(
        [chain]
    )

    assert "test_chain_gate" in components
    assert "test_chain_group_0" in components
    assert len(connections) > 0
    assert process_components == (components["test_chain_group_0"],)
    assert compiled[0].output_topic == "_qt.test_chain.out"


def test_build_sidecar_components_multiple_processors_in_group():
    """Multiple processors in a group are chained together."""
    from ezmsg.qt.chain import ProcessorChain

    chain = ProcessorChain(DemoTopic.INPUT, parent=None)
    chain._chain_id = "test_chain"
    chain.parallel(DoubleProcessor, DoubleProcessor).connect(lambda _msg: None)

    components, connections, process_components, _compiled = build_sidecar_components(
        [chain]
    )

    group = components["test_chain_group_0"]
    assert hasattr(group, "proc_0")
    assert hasattr(group, "proc_1")
    assert process_components == (group,)


def test_build_sidecar_components_ignores_local_groups():
    """Local groups are compiled into the shared sidecar process."""
    from ezmsg.qt.chain import ProcessorChain

    chain = ProcessorChain(DemoTopic.INPUT, parent=None)
    chain._chain_id = "test_chain"
    chain.local(DoubleProcessor).connect(lambda _msg: None)

    components, connections, process_components, compiled = build_sidecar_components(
        [chain]
    )

    assert "test_chain_gate" in components
    assert "test_chain_group_0" in components
    assert connections
    assert process_components == ()
    assert compiled


def test_build_sidecar_components_mixed_groups():
    """Mixed groups retain process boundaries in the compiled collection."""
    from ezmsg.qt.chain import ProcessorChain

    chain = ProcessorChain(DemoTopic.INPUT, parent=None)
    chain._chain_id = "test_chain"
    chain.parallel(DoubleProcessor).local(DoubleProcessor).connect(lambda _msg: None)

    components, connections, process_components, _compiled = build_sidecar_components(
        [chain]
    )

    group_0 = components["test_chain_group_0"]
    group_1 = components["test_chain_group_1"]
    assert group_0 in process_components
    assert group_1 not in process_components


def test_build_sidecar_components_uses_topic_prefix():
    """Compiled topics can be namespaced per session."""
    from ezmsg.qt.chain import ProcessorChain

    chain = ProcessorChain(DemoTopic.INPUT, parent=None)
    chain._chain_id = "test_chain"
    chain.local(DoubleProcessor).connect(lambda _msg: None)

    _components, _connections, _process_components, compiled = build_sidecar_components(
        [chain], topic_prefix="_qt.session_123"
    )

    assert compiled[0].gate_topic == "_qt.session_123.test_chain.gate"
    assert compiled[0].output_topic == "_qt.session_123.test_chain.out"
