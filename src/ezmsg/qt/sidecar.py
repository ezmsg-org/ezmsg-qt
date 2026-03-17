"""Sidecar runtime compilation for processor pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from typing import Any

import ezmsg.core as ez
from ezmsg.core.collection import NetworkDefinition

from .chain import ProcessorGroup
from .chain import _to_unit
from .gate import GateMessage
from .gate import MessageGate
from .gate import MessageGateSettings

if TYPE_CHECKING:
    from .chain import ProcessorChain


_INPUT_STREAM_NAMES = ("INPUT_SIGNAL", "INPUT")
_OUTPUT_STREAM_NAMES = ("OUTPUT_SIGNAL", "OUTPUT")


def normalize_topic(topic: str | Enum) -> str:
    """Normalize public topic inputs to ezmsg core semantics."""
    if isinstance(topic, Enum):
        return topic.name
    if isinstance(topic, str):
        return topic
    raise TypeError(f"Unsupported topic type: {type(topic)!r}")


def _detect_stream_names(unit: ez.Unit) -> tuple[str, str]:
    unit_class = type(unit)

    input_name = next(
        (name for name in _INPUT_STREAM_NAMES if hasattr(unit_class, name)), None
    )
    output_name = next(
        (name for name in _OUTPUT_STREAM_NAMES if hasattr(unit_class, name)),
        None,
    )

    if input_name is None:
        raise ValueError(
            f"Unit {unit_class.__name__} has no recognized input stream. "
            f"Expected one of: {_INPUT_STREAM_NAMES}"
        )
    if output_name is None:
        raise ValueError(
            f"Unit {unit_class.__name__} has no recognized output stream. "
            f"Expected one of: {_OUTPUT_STREAM_NAMES}"
        )

    return input_name, output_name


class ProcessorGroupCollection(ez.Collection):
    """Collection wrapper for a processor group."""

    INPUT = ez.InputStream(Any)
    OUTPUT = ez.OutputStream(Any)

    def __init__(self, processors: list[Any]):
        super().__init__()
        self._ordered_processors: list[tuple[str, ez.Unit]] = []

        for index, spec in enumerate(processors):
            unit = _to_unit(spec)
            name = f"proc_{index}"
            unit._set_name(name)
            self._components[name] = unit
            setattr(self, name, unit)
            self._ordered_processors.append((name, unit))

    def network(self) -> NetworkDefinition:
        edges: list[tuple[Any, Any]] = []
        previous: Any = self.INPUT

        for _name, unit in self._ordered_processors:
            input_name, output_name = _detect_stream_names(unit)
            edges.append((previous, getattr(unit, input_name)))
            previous = getattr(unit, output_name)

        edges.append((previous, self.OUTPUT))
        return edges


class PipelineCollection(ez.Collection):
    """Collection wrapper for one compiled processor pipeline."""

    INPUT = ez.InputStream(Any)
    OUTPUT = ez.OutputStream(Any)
    INPUT_GATE = ez.InputStream(GateMessage)

    def __init__(self, groups: list[ProcessorGroup]):
        super().__init__()
        self._group_collections: list[tuple[str, ProcessorGroupCollection, str]] = []

        gate = MessageGate(MessageGateSettings(start_open=True))
        gate._set_name("gate")
        self._gate = gate
        self._components["gate"] = gate
        setattr(self, "gate", gate)

        for index, group in enumerate(groups):
            collection = ProcessorGroupCollection(group.processors)
            name = f"group_{index}"
            collection._set_name(name)
            self._components[name] = collection
            setattr(self, name, collection)
            self._group_collections.append((name, collection, group.mode))

    def network(self) -> NetworkDefinition:
        edges: list[tuple[Any, Any]] = [
            (self.INPUT, self._gate.INPUT),
            (self.INPUT_GATE, self._gate.INPUT_GATE),
        ]
        previous: Any = self._gate.OUTPUT

        for _name, collection, _mode in self._group_collections:
            edges.append((previous, collection.INPUT))
            previous = collection.OUTPUT

        edges.append((previous, self.OUTPUT))
        return edges

    def process_components(self) -> tuple[ez.Component, ...]:
        return tuple(
            collection
            for _name, collection, mode in self._group_collections
            if mode == "process"
        )


@dataclass(frozen=True)
class CompiledPipeline:
    """Bridge-facing metadata for a compiled pipeline."""

    chain: ProcessorChain
    component_name: str
    source_topic: str
    output_topic: str
    gate_topic: str
    component: PipelineCollection


def build_sidecar_components(
    chains: list[ProcessorChain],
) -> tuple[
    dict[str, PipelineCollection], list[tuple[Any, Any]], list[CompiledPipeline]
]:
    """Compile pipelines into a sidecar GraphRunner definition."""
    components: dict[str, PipelineCollection] = {}
    connections: list[tuple[Any, Any]] = []
    compiled: list[CompiledPipeline] = []

    for index, chain in enumerate(chains):
        chain._validate()
        chain_id = chain._chain_id or f"chain_{index}"
        component_name = f"pipeline_{chain_id}"
        output_topic = f"_qt.{chain_id}.out"
        gate_topic = f"_qt.{chain_id}.gate"
        source_topic = normalize_topic(chain.source_topic)

        component = PipelineCollection(chain.groups)
        components[component_name] = component
        connections.extend(
            [
                (source_topic, component.INPUT),
                (gate_topic, component.INPUT_GATE),
                (component.OUTPUT, output_topic),
            ]
        )
        compiled.append(
            CompiledPipeline(
                chain=chain,
                component_name=component_name,
                source_topic=source_topic,
                output_topic=output_topic,
                gate_topic=gate_topic,
                component=component,
            )
        )

    return components, connections, compiled
