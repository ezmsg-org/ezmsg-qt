"""Tests for ProcessorGraph."""

from collections.abc import AsyncGenerator
from enum import Enum

import ezmsg.core as ez

from ezmsg.qt.chain import BoundProcessor
from ezmsg.qt.chain import ProcessorGraph
from ezmsg.qt.chain import _to_unit


class DemoTopic(Enum):
    INPUT = "INPUT"


class DoubleProcessor(ez.Unit):
    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg * 2


class DoubleSettings(ez.Settings):
    factor: int = 2


class ConfigurableDouble(ez.Unit):
    SETTINGS = DoubleSettings
    INPUT = ez.InputStream(float)
    INPUT_SETTINGS = ez.InputStream(DoubleSettings)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT_SETTINGS)
    async def on_settings(self, msg: DoubleSettings) -> None:
        self.apply_settings(msg)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg * self.SETTINGS.factor


class AsyncTransformer:
    async def __acall__(self, msg: float) -> float:
        return msg * 2


def test_processor_graph_creation():
    graph = ProcessorGraph(source_topic=DemoTopic.INPUT, parent=None)
    assert graph.source_topic == DemoTopic.INPUT
    assert graph.auto_gate is False
    assert graph.auto_gate_position == "input"
    assert graph.stages == []
    assert graph.sinks == []


def test_processor_graph_accepts_output_gate_position():
    graph = ProcessorGraph(DemoTopic.INPUT, auto_gate_position="output")
    assert graph.auto_gate_position == "output"


def test_processor_graph_rejects_invalid_gate_position():
    try:
        ProcessorGraph(DemoTopic.INPUT, auto_gate_position="middle")  # type: ignore[arg-type]
    except ValueError as exc:
        assert "auto_gate_position" in str(exc)
    else:
        raise AssertionError("Expected ProcessorGraph to reject invalid gate position")


def test_bound_processor_stores_metadata_and_stream_overrides():
    bound = BoundProcessor(
        ConfigurableDouble,
        name="double",
        input_name="INPUT_SETTINGS",
        output_name="OUTPUT_STATUS",
    )
    assert bound.processor is ConfigurableDouble
    assert bound.name == "double"
    assert bound.input_name == "INPUT_SETTINGS"
    assert bound.output_name == "OUTPUT_STATUS"


def test_processor_graph_parallel_and_local_add_stages():
    graph = (
        ProcessorGraph(DemoTopic.INPUT).parallel(DoubleProcessor).local(DoubleProcessor)
    )
    assert len(graph.stages) == 2
    assert graph.stages[0].mode == "process"
    assert graph.stages[1].mode == "shared"


def test_processor_graph_apply_and_branch_ignore_return_values():
    graph = ProcessorGraph(DemoTopic.INPUT)

    def add_main(path):
        path.local(BoundProcessor(DoubleProcessor, name="main"))
        return object()

    def add_branch(path):
        path.local(BoundProcessor(ConfigurableDouble, name="branch")).connect(
            lambda _msg: None
        )
        return object()

    graph.apply(add_main).branch(add_branch).connect(lambda _msg: None)

    assert len(graph.stages) == 2
    assert graph.stages[0].source_ref == "__root__"
    assert graph.stages[1].source_ref == graph.stages[0].stage_id
    assert len(graph.sinks) == 2
    assert graph.sinks[0].source_ref == graph.stages[1].stage_id
    assert graph.sinks[1].source_ref == graph.stages[0].stage_id


def test_processor_graph_connect_is_additive():
    received_a: list[float] = []
    received_b: list[float] = []

    graph = ProcessorGraph(DemoTopic.INPUT).local(DoubleProcessor)
    graph.connect(received_a.append).connect(received_b.append)

    assert len(graph.sinks) == 2
    graph.sinks[0].slot(1.0)
    graph.sinks[1].slot(2.0)
    assert received_a == [1.0]
    assert received_b == [2.0]


def test_processor_graph_settings_bindings_after_attach():
    from ezmsg.qt.session import EzSession

    session = EzSession()
    graph = (
        ProcessorGraph(DemoTopic.INPUT)
        .local(BoundProcessor(ConfigurableDouble, name="configured"), DoubleProcessor)
        .branch(
            lambda path: path.local(BoundProcessor(ConfigurableDouble)).connect(
                lambda _msg: None
            )
        )
        .connect(lambda _msg: None)
        .attach(session)
    )

    bindings = graph.settings_bindings()
    assert [binding.name for binding in bindings] == [
        "configured",
        "configurable_double",
    ]
    assert bindings[0].topic.endswith(".configured.settings")
    assert bindings[1].topic.endswith(".configurable_double.settings")
    assert bindings[0].initial_settings == DoubleSettings()


def test_to_unit_with_class_and_settings_tuple():
    unit = _to_unit(DoubleProcessor)
    assert isinstance(unit, DoubleProcessor)

    settings = DoubleSettings(factor=5)
    configured = _to_unit((ConfigurableDouble, settings))
    assert isinstance(configured, ConfigurableDouble)
    assert configured.SETTINGS.factor == 5


def test_processor_graph_parallel_rejects_transformers():
    graph = (
        ProcessorGraph(DemoTopic.INPUT)
        .parallel(AsyncTransformer())
        .connect(lambda _msg: None)
    )

    try:
        graph._validate()
    except TypeError as exc:
        assert "parallel() only supports" in str(exc)
    else:
        raise AssertionError(
            "Expected ProcessorGraph._validate() to reject transformer"
        )
