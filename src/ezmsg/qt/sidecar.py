"""Sidecar runtime compilation for processor graphs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from importlib import import_module
from typing import Any
from typing import TYPE_CHECKING

import ezmsg.core as ez
from ezmsg.core.collection import NetworkDefinition

from .chain import _ROOT_REF
from .chain import _to_unit
from .chain import GraphSink
from .chain import ProcessorGraph
from .chain import ProcessorInputBinding
from .chain import ProcessorSettingsBinding
from .chain import ProcessorStage
from .gate import MessageGate
from .gate import MessageGateSettings

if TYPE_CHECKING:
    from collections.abc import Callable


_INPUT_STREAM_NAMES = ("INPUT_SIGNAL", "INPUT")
_OUTPUT_STREAM_NAMES = ("OUTPUT_SIGNAL", "OUTPUT")

_stream_module = import_module("ezmsg.core.stream")
_INPUT_BOUNDARY = getattr(_stream_module, "InputTopic", ez.InputStream)
_OUTPUT_BOUNDARY = getattr(_stream_module, "OutputTopic", ez.OutputStream)


def normalize_topic(topic: str | Enum) -> str:
    if isinstance(topic, Enum):
        return topic.name
    if isinstance(topic, str):
        return topic
    raise TypeError(f"Unsupported topic type: {type(topic)!r}")


def _detect_stream_name(
    unit: ez.Unit,
    candidates: tuple[str, ...],
    kind: str,
) -> str:
    unit_class = type(unit)
    stream_name = next((name for name in candidates if hasattr(unit_class, name)), None)
    if stream_name is None:
        raise ValueError(
            f"Unit {unit_class.__name__} has no recognized {kind} stream. "
            f"Expected one of: {candidates}"
        )
    return stream_name


class ProcessorStageCollection(ez.Collection):
    """Collection wrapper for a linear processor stage."""

    INPUT = _INPUT_BOUNDARY(Any)
    OUTPUT = _OUTPUT_BOUNDARY(Any)

    def __init__(self, processors: tuple[Any, ...]):
        super().__init__()
        self._ordered_processors: list[tuple[str, ez.Unit, str | None, str | None]] = []

        for index, spec in enumerate(processors):
            input_name = getattr(spec, "input_name", None)
            output_name = getattr(spec, "output_name", None)
            unit = _to_unit(spec)
            name = f"proc_{index}"
            unit._set_name(name)
            self._components[name] = unit
            setattr(self, name, unit)
            self._ordered_processors.append((name, unit, input_name, output_name))

    def network(self) -> NetworkDefinition:
        edges: list[tuple[Any, Any]] = []
        previous: Any = self.INPUT

        for _name, unit, input_override, output_override in self._ordered_processors:
            input_name = input_override or _detect_stream_name(
                unit,
                _INPUT_STREAM_NAMES,
                "input",
            )
            output_name = output_override or _detect_stream_name(
                unit,
                _OUTPUT_STREAM_NAMES,
                "output",
            )
            edges.append((previous, getattr(unit, input_name)))
            previous = getattr(unit, output_name)

        edges.append((previous, self.OUTPUT))
        return edges

    def process_components(self) -> tuple[ez.Component, ...]:
        return ()


@dataclass(frozen=True)
class CompiledSink:
    sink_id: str
    topic: str
    slot: Callable[[Any], None]
    gate_component_name: str | None = None


@dataclass(frozen=True)
class CompiledGraph:
    graph: ProcessorGraph
    gate_component_name: str | None
    stage_component_names: tuple[str, ...]
    source_topic: str
    gate_topic: str | None
    sinks: tuple[CompiledSink, ...]
    settings_bindings: tuple[ProcessorSettingsBinding, ...] = ()
    input_bindings: tuple[ProcessorInputBinding, ...] = ()


def build_sidecar_components(
    graphs: list[ProcessorGraph],
    topic_prefix: str = "_qt",
) -> tuple[
    dict[str, ez.Component],
    list[tuple[Any, Any]],
    tuple[ez.Component, ...],
    list[CompiledGraph],
]:
    components: dict[str, ez.Component] = {}
    connections: list[tuple[Any, Any]] = []
    process_components: list[ez.Component] = []
    compiled: list[CompiledGraph] = []

    for index, graph in enumerate(graphs):
        graph._validate()
        graph_id = graph._graph_id or f"graph_{index}"
        source_topic = normalize_topic(graph.source_topic)
        settings_bindings = graph._collect_settings_bindings(topic_prefix)
        input_bindings = graph._collect_input_bindings(topic_prefix)
        gate_topic = f"{topic_prefix}.{graph_id}.gate" if graph.auto_gate else None

        ref_endpoints: dict[str, Any] = {_ROOT_REF: source_topic}
        stage_names: list[str] = []

        root_gate_name: str | None = None
        if graph.auto_gate and graph.auto_gate_position == "input":
            root_gate_name = f"{graph_id}_gate"
            components[root_gate_name] = MessageGate(
                MessageGateSettings(start_open=True)
            )
            assert gate_topic is not None
            connections.append((gate_topic, f"{root_gate_name}/INPUT_GATE"))
            connections.append((source_topic, f"{root_gate_name}/INPUT"))
            ref_endpoints[_ROOT_REF] = f"{root_gate_name}/OUTPUT"

        for stage in graph.stages:
            stage_name = f"{graph_id}_{stage.stage_id}"
            collection = ProcessorStageCollection(stage.processors)
            components[stage_name] = collection
            stage_names.append(stage_name)
            connections.append((ref_endpoints[stage.source_ref], f"{stage_name}/INPUT"))
            ref_endpoints[stage.stage_id] = f"{stage_name}/OUTPUT"
            if stage.mode == "process":
                process_components.append(collection)

        for binding in settings_bindings:
            stage_name = f"{graph_id}_{binding.node_id}"
            target = f"{stage_name}/proc_{binding.processor_index}/INPUT_SETTINGS"
            connections.append((binding.topic, target))

        for binding in input_bindings:
            stage_name = f"{graph_id}_{binding.node_id}"
            target = f"{stage_name}/proc_{binding.processor_index}/{binding.input_name}"
            connections.append((binding.topic, target))

        sink_bindings: list[CompiledSink] = []
        for sink in graph.sinks:
            sink_topic = f"{topic_prefix}.{graph_id}.{sink.sink_id}.out"
            sink_gate_name: str | None = None

            if graph.auto_gate and graph.auto_gate_position == "output":
                sink_gate_name = f"{graph_id}_{sink.sink_id}_gate"
                components[sink_gate_name] = MessageGate(
                    MessageGateSettings(start_open=True)
                )
                assert gate_topic is not None
                connections.append((gate_topic, f"{sink_gate_name}/INPUT_GATE"))
                connections.append(
                    (ref_endpoints[sink.source_ref], f"{sink_gate_name}/INPUT")
                )
                connections.append((f"{sink_gate_name}/OUTPUT", sink_topic))
            else:
                connections.append((ref_endpoints[sink.source_ref], sink_topic))

            sink_bindings.append(
                CompiledSink(
                    sink_id=sink.sink_id,
                    topic=sink_topic,
                    slot=sink.slot,
                    gate_component_name=sink_gate_name,
                )
            )

        compiled.append(
            CompiledGraph(
                graph=graph,
                gate_component_name=root_gate_name,
                stage_component_names=tuple(stage_names),
                source_topic=source_topic,
                gate_topic=gate_topic,
                sinks=tuple(sink_bindings),
                settings_bindings=tuple(settings_bindings),
                input_bindings=tuple(input_bindings),
            )
        )

    return components, connections, tuple(process_components), compiled
