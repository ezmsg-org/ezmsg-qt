"""Sidecar runtime compilation for processor pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from importlib import import_module
from typing import Any
from typing import TYPE_CHECKING

import ezmsg.core as ez
from ezmsg.core.collection import NetworkDefinition

from .chain import _to_unit
from .gate import MessageGate
from .gate import MessageGateSettings

if TYPE_CHECKING:
    from .chain import ProcessorChain


_INPUT_STREAM_NAMES = ("INPUT_SIGNAL", "INPUT")
_OUTPUT_STREAM_NAMES = ("OUTPUT_SIGNAL", "OUTPUT")

_stream_module = import_module("ezmsg.core.stream")
# TODO: Drop this fallback once a released ezmsg package exposes InputTopic /
# OutputTopic consistently at runtime.
_INPUT_BOUNDARY = getattr(_stream_module, "InputTopic", ez.InputStream)
_OUTPUT_BOUNDARY = getattr(_stream_module, "OutputTopic", ez.OutputStream)


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

    INPUT = _INPUT_BOUNDARY(Any)
    OUTPUT = _OUTPUT_BOUNDARY(Any)

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

    def process_components(self) -> tuple[ez.Component, ...]:
        return ()


@dataclass(frozen=True)
class CompiledPipeline:
    """Session-facing metadata for a compiled pipeline."""

    chain: ProcessorChain
    gate_component_name: str
    group_component_names: tuple[str, ...]
    source_topic: str
    output_topic: str
    gate_topic: str


def build_sidecar_components(
    chains: list[ProcessorChain],
    topic_prefix: str = "_qt",
) -> tuple[
    dict[str, ez.Component],
    list[tuple[Any, Any]],
    tuple[ez.Component, ...],
    list[CompiledPipeline],
]:
    """Compile pipelines into a sidecar GraphRunner definition."""
    components: dict[str, ez.Component] = {}
    connections: list[tuple[Any, Any]] = []
    process_components: list[ez.Component] = []
    compiled: list[CompiledPipeline] = []

    for index, chain in enumerate(chains):
        chain._validate()
        chain_id = chain._chain_id or f"chain_{index}"
        gate_name = f"{chain_id}_gate"
        output_topic = f"{topic_prefix}.{chain_id}.out"
        gate_topic = f"{topic_prefix}.{chain_id}.gate"
        source_topic = normalize_topic(chain.source_topic)

        gate = MessageGate(MessageGateSettings(start_open=True))
        components[gate_name] = gate

        connections.extend(
            [
                (source_topic, f"{gate_name}/INPUT"),
                (gate_topic, f"{gate_name}/INPUT_GATE"),
            ]
        )

        previous: Any = f"{gate_name}/OUTPUT"
        group_names: list[str] = []

        for group_index, group in enumerate(chain.groups):
            group_name = f"{chain_id}_group_{group_index}"
            collection = ProcessorGroupCollection(group.processors)
            components[group_name] = collection
            connections.append((previous, f"{group_name}/INPUT"))
            previous = f"{group_name}/OUTPUT"
            group_names.append(group_name)

            if group.mode == "process":
                process_components.append(collection)

        connections.append((previous, output_topic))

        compiled.append(
            CompiledPipeline(
                chain=chain,
                gate_component_name=gate_name,
                group_component_names=tuple(group_names),
                source_topic=source_topic,
                output_topic=output_topic,
                gate_topic=gate_topic,
            )
        )

    return components, connections, tuple(process_components), compiled
