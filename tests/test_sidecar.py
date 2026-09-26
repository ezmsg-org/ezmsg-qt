"""Tests for sidecar graph compilation."""

from collections.abc import AsyncGenerator
from enum import Enum
from typing import cast

import ezmsg.core as ez

from ezmsg.qt.chain import BoundProcessor
from ezmsg.qt.sidecar import ProcessorStageCollection
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


class ConfigurableSettings(ez.Settings):
    gain: float = 1.0


class ConfigurableProcessor(ez.Unit):
    SETTINGS = ConfigurableSettings
    INPUT = ez.InputStream(float)
    INPUT_SETTINGS = ez.InputStream(ConfigurableSettings)
    OUTPUT = ez.OutputStream(float)
    OUTPUT_STATUS = ez.OutputStream(str)

    @ez.subscriber(INPUT_SETTINGS)
    async def on_settings(self, msg: ConfigurableSettings) -> None:
        self.apply_settings(msg)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg


class ControlProcessor(ez.Unit):
    INPUT = ez.InputStream(float)
    INPUT_CONTROL = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT_CONTROL)
    async def on_control(self, msg: float) -> None:
        _ = msg

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg


class ClockedProcessor(ez.Unit):
    INPUT_CLOCK = ez.InputStream(float)
    OUTPUT_IMAGE = ez.OutputStream(float)

    @ez.subscriber(INPUT_CLOCK)
    @ez.publisher(OUTPUT_IMAGE)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT_IMAGE, msg


def test_build_sidecar_components_empty():
    components, connections, process_components, compiled = build_sidecar_components([])
    assert components == {}
    assert connections == []
    assert process_components == ()
    assert compiled == []


def test_stage_collection_supports_custom_stream_overrides():
    stage = ProcessorStageCollection(
        (
            DoubleProcessor,
            BoundProcessor(
                ConfigurableProcessor,
                input_name="INPUT_SETTINGS",
                output_name="OUTPUT_STATUS",
            ),
        )
    )
    proc_0 = getattr(stage, "proc_0")
    proc_1 = getattr(stage, "proc_1")
    edges = list(stage.network())

    assert edges[0] == (stage.INPUT, proc_0.INPUT)
    assert edges[1] == (proc_0.OUTPUT, proc_1.INPUT_SETTINGS)
    assert edges[2] == (proc_1.OUTPUT_STATUS, stage.OUTPUT)


def test_build_sidecar_components_builds_branching_graph():
    from ezmsg.qt import ProcessorGraph

    graph = ProcessorGraph(DemoTopic.INPUT, parent=None)
    graph.local(BoundProcessor(DoubleProcessor, name="main")).connect(lambda _msg: None)
    graph.branch(
        lambda path: path.local(
            BoundProcessor(ConfigurableProcessor, name="branch")
        ).connect(lambda _msg: None)
    )
    graph._graph_id = "test_graph"

    components, connections, process_components, compiled = build_sidecar_components(
        [graph]
    )

    assert "test_graph_stage_0" in components
    assert "test_graph_stage_1" in components
    assert process_components == ()
    assert ("INPUT", "test_graph_stage_0/INPUT") in connections
    assert ("test_graph_stage_0/OUTPUT", "test_graph_stage_1/INPUT") in connections
    assert ("test_graph_stage_0/OUTPUT", "_qt.test_graph.sink_0.out") in connections
    assert ("test_graph_stage_1/OUTPUT", "_qt.test_graph.sink_1.out") in connections
    assert len(compiled[0].sinks) == 2


def test_build_sidecar_components_can_gate_at_input_and_output():
    from ezmsg.qt import ProcessorGraph

    input_graph = ProcessorGraph(DemoTopic.INPUT, auto_gate=True)
    input_graph.local(DoubleProcessor).connect(lambda _msg: None)
    input_graph._graph_id = "input_graph"

    output_graph = ProcessorGraph(
        DemoTopic.INPUT, auto_gate=True, auto_gate_position="output"
    )
    output_graph.local(DoubleProcessor).connect(lambda _msg: None)
    output_graph._graph_id = "output_graph"

    components, connections, _process_components, compiled = build_sidecar_components(
        [input_graph, output_graph]
    )

    assert "input_graph_gate" in components
    assert ("INPUT", "input_graph_gate/INPUT") in connections
    assert ("input_graph_gate/OUTPUT", "input_graph_stage_0/INPUT") in connections
    assert compiled[0].gate_topic == "_qt.input_graph.gate"

    assert "output_graph_sink_0_gate" in components
    assert (
        "output_graph_stage_0/OUTPUT",
        "output_graph_sink_0_gate/INPUT",
    ) in connections
    assert (
        "output_graph_sink_0_gate/OUTPUT",
        "_qt.output_graph.sink_0.out",
    ) in connections
    assert compiled[1].gate_topic == "_qt.output_graph.gate"


def test_build_sidecar_components_auto_wire_settings_topics():
    from ezmsg.qt import ProcessorGraph

    graph = ProcessorGraph(DemoTopic.INPUT)
    graph.local(BoundProcessor(ConfigurableProcessor, name="configurable")).connect(
        lambda _msg: None
    )
    graph._graph_id = "test_graph"

    _components, connections, _process_components, compiled = build_sidecar_components(
        [graph], topic_prefix="_qt.session"
    )

    assert compiled[0].settings_bindings[0].name == "configurable"
    assert (
        compiled[0].settings_bindings[0].topic
        == "_qt.session.test_graph.configurable.settings"
    )
    assert (
        "_qt.session.test_graph.configurable.settings",
        "test_graph_stage_0/proc_0/INPUT_SETTINGS",
    ) in connections


def test_build_sidecar_components_can_wire_custom_auxiliary_inputs():
    from ezmsg.qt import ProcessorGraph

    graph = ProcessorGraph(DemoTopic.INPUT)
    graph.local(
        BoundProcessor(
            ControlProcessor,
            name="controlled",
            inputs={"INPUT_CONTROL": "CONTROL_TOPIC"},
        )
    ).connect(lambda _msg: None)
    graph._graph_id = "test_graph"

    _components, connections, _process_components, compiled = build_sidecar_components(
        [graph]
    )

    assert compiled[0].input_bindings[0].topic == "CONTROL_TOPIC"
    assert ("CONTROL_TOPIC", "test_graph_stage_0/proc_0/INPUT_CONTROL") in connections


def test_stage_collection_allows_explicit_main_path_stream_overrides():
    stage = ProcessorStageCollection(
        (
            BoundProcessor(
                ClockedProcessor,
                input_name="INPUT_CLOCK",
                output_name="OUTPUT_IMAGE",
            ),
        )
    )
    proc_0 = getattr(stage, "proc_0")

    edges = list(stage.network())

    assert edges[0] == (stage.INPUT, proc_0.INPUT_CLOCK)
    assert edges[1] == (proc_0.OUTPUT_IMAGE, stage.OUTPUT)


def test_build_sidecar_components_marks_process_stages():
    from ezmsg.qt import ProcessorGraph

    graph = ProcessorGraph(DemoTopic.INPUT)
    graph.parallel(DoubleProcessor).local(DoubleProcessor).connect(lambda _msg: None)
    graph._graph_id = "test_graph"

    components, _connections, process_components, _compiled = build_sidecar_components(
        [graph]
    )
    stage_0 = cast(ProcessorStageCollection, components["test_graph_stage_0"])
    stage_1 = cast(ProcessorStageCollection, components["test_graph_stage_1"])
    assert stage_0 in process_components
    assert stage_1 not in process_components
