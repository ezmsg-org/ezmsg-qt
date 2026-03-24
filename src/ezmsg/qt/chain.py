"""ProcessorGraph - Fluent DAG API for compiled processing graphs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import re
from typing import Any
from typing import cast
from typing import Literal
from typing import Self
from typing import TYPE_CHECKING

import ezmsg.core as ez
from qtpy import QtWidgets

if TYPE_CHECKING:
    from .session import EzSession


@dataclass(frozen=True)
class BoundProcessor:
    """Wrap a processor spec with optional metadata and stream overrides."""

    processor: type[ez.Unit] | tuple[type[ez.Unit], ez.Settings] | Any
    name: str | None = None
    input_name: str | None = None
    output_name: str | None = None
    inputs: dict[str, Enum | str] | None = None


ProcessorSpec = type[ez.Unit] | tuple[type[ez.Unit], ez.Settings] | BoundProcessor | Any
AutoGatePosition = Literal["input", "output"]
GraphRecipe = Callable[["ProcessorPath"], Any]

_ROOT_REF = "__root__"


@dataclass(frozen=True)
class ProcessorSettingsBinding:
    """Runtime settings metadata for a processor in the graph."""

    name: str
    title: str
    node_id: str
    processor_index: int
    settings_type: type[Any]
    topic: str
    initial_settings: Any | None


@dataclass(frozen=True)
class ProcessorInputBinding:
    """Bind a public topic to a named processor input stream."""

    node_id: str
    processor_index: int
    input_name: str
    topic: str


@dataclass(frozen=True)
class ProcessorStage:
    """A linear group of processors sourced from an upstream tail."""

    stage_id: str
    source_ref: str
    processors: tuple[ProcessorSpec, ...]
    mode: Literal["shared", "process"]


@dataclass(frozen=True)
class GraphSink:
    """A Qt-facing observer attached to a tail in the graph."""

    sink_id: str
    source_ref: str
    slot: Callable[[Any], None]


def _is_process_safe(spec: ProcessorSpec) -> bool:
    if isinstance(spec, BoundProcessor):
        spec = spec.processor
    if isinstance(spec, ez.Unit):
        return True
    if isinstance(spec, tuple):
        unit_class, _settings = spec
        return isinstance(unit_class, type) and issubclass(unit_class, ez.Unit)
    return isinstance(spec, type) and issubclass(spec, ez.Unit)


def _to_unit(spec: ProcessorSpec) -> ez.Unit:
    if isinstance(spec, BoundProcessor):
        spec = spec.processor

    if isinstance(spec, ez.Unit):
        return spec
    if isinstance(spec, tuple):
        unit_class, settings = spec
        unit = unit_class()
        unit.apply_settings(settings)
        return unit
    if isinstance(spec, type) and issubclass(spec, ez.Unit):
        return spec()
    if hasattr(spec, "__acall__"):
        from .adapter import TransformerAdapter

        return TransformerAdapter(spec)
    raise TypeError(
        f"Expected Unit class, (class, settings) tuple, or processor instance "
        f"with __acall__, got {type(spec)}"
    )


class ProcessorPath:
    """Mutable builder for a path in a processor graph."""

    def __init__(self, graph: ProcessorGraph, tail_ref: str):
        self._graph = graph
        self._tail_ref = tail_ref

    @property
    def graph(self) -> ProcessorGraph:
        return self._graph

    @property
    def tail_ref(self) -> str:
        return self._tail_ref

    def parallel(self, *processors: ProcessorSpec) -> Self:
        self._tail_ref = self._graph._add_stage(self._tail_ref, processors, "process")
        return self

    def local(self, *processors: ProcessorSpec) -> Self:
        self._tail_ref = self._graph._add_stage(self._tail_ref, processors, "shared")
        return self

    def connect(self, slot: Callable[[Any], None]) -> Self:
        self._graph._add_sink(self._tail_ref, slot)
        return self

    def apply(self, recipe: GraphRecipe) -> Self:
        recipe(self)
        return self

    def branch(self, recipe: GraphRecipe) -> Self:
        branch_path = ProcessorPath(self._graph, self._tail_ref)
        recipe(branch_path)
        return self


class ProcessorGraph(ProcessorPath):
    """Fluent builder for Qt-facing processor graphs."""

    def __init__(
        self,
        source_topic: Enum | str,
        parent: QtWidgets.QWidget | None = None,
        auto_gate: bool = False,
        auto_gate_position: AutoGatePosition = "input",
    ):
        if auto_gate_position not in ("input", "output"):
            raise ValueError("auto_gate_position must be 'input' or 'output'")
        self._source_topic = source_topic
        self._parent_widget = parent
        self._auto_gate = auto_gate
        self._auto_gate_position: AutoGatePosition = cast(
            AutoGatePosition, auto_gate_position
        )
        self._stages: list[ProcessorStage] = []
        self._sinks: list[GraphSink] = []
        self._stage_counter = 0
        self._sink_counter = 0
        self._graph_id: str | None = None
        self._session: EzSession | None = None
        self._attached = False
        self._visibility_filter: Any | None = None
        super().__init__(self, _ROOT_REF)

    @property
    def source_topic(self) -> Enum | str:
        return self._source_topic

    @property
    def parent_widget(self) -> QtWidgets.QWidget | None:
        return self._parent_widget

    @property
    def auto_gate(self) -> bool:
        return self._auto_gate

    @property
    def auto_gate_position(self) -> AutoGatePosition:
        return self._auto_gate_position

    @property
    def stages(self) -> list[ProcessorStage]:
        return self._stages

    @property
    def sinks(self) -> list[GraphSink]:
        return self._sinks

    @property
    def session(self) -> EzSession | None:
        return self._session

    @property
    def attached(self) -> bool:
        return self._attached

    def attach(self, session: EzSession) -> ProcessorGraph:
        session.attach(self)
        return self

    def settings_bindings(self) -> list[ProcessorSettingsBinding]:
        if self._session is None or self._graph_id is None:
            raise RuntimeError(
                "ProcessorGraph must be attached to a session before reading settings bindings"
            )
        return self._collect_settings_bindings(self._session._topic_prefix)

    def input_bindings(self) -> list[ProcessorInputBinding]:
        if self._session is None or self._graph_id is None:
            raise RuntimeError(
                "ProcessorGraph must be attached to a session before reading input bindings"
            )
        return self._collect_input_bindings(self._session._topic_prefix)

    def _add_stage(
        self,
        source_ref: str,
        processors: tuple[ProcessorSpec, ...],
        mode: Literal["shared", "process"],
    ) -> str:
        stage_id = f"stage_{self._stage_counter}"
        self._stage_counter += 1
        self._stages.append(
            ProcessorStage(
                stage_id=stage_id,
                source_ref=source_ref,
                processors=processors,
                mode=mode,
            )
        )
        return stage_id

    def _add_sink(self, source_ref: str, slot: Callable[[Any], None]) -> None:
        sink_id = f"sink_{self._sink_counter}"
        self._sink_counter += 1
        self._sinks.append(GraphSink(sink_id=sink_id, source_ref=source_ref, slot=slot))

    def _bind_session(self, session: EzSession) -> None:
        if self._session is not None and self._session is not session:
            raise RuntimeError(
                "ProcessorGraph is already attached to a different session"
            )
        self._session = session
        self._attached = True

    def _validate(self) -> None:
        if not self._stages:
            raise ValueError("ProcessorGraph must define at least one processor stage")
        if not self._sinks:
            raise ValueError("ProcessorGraph must connect at least one handler")

        known_refs = {_ROOT_REF}
        for stage in self._stages:
            if stage.source_ref not in known_refs:
                raise ValueError(f"Unknown graph source reference: {stage.source_ref}")
            if stage.mode == "process":
                for spec in stage.processors:
                    if not _is_process_safe(spec):
                        raise TypeError(
                            "parallel() only supports ez.Unit classes, ez.Unit instances, "
                            "or (UnitClass, Settings) tuples"
                        )
            known_refs.add(stage.stage_id)

        for sink in self._sinks:
            if sink.source_ref not in known_refs:
                raise ValueError(
                    f"Unknown graph sink source reference: {sink.source_ref}"
                )

    def _collect_settings_bindings(
        self,
        topic_prefix: str,
    ) -> list[ProcessorSettingsBinding]:
        counts: dict[str, int] = {}
        bindings: list[ProcessorSettingsBinding] = []

        for stage in self._stages:
            for processor_index, spec in enumerate(stage.processors):
                unit = _to_unit(spec)
                unit_class = type(unit)
                settings_type = getattr(unit_class, "SETTINGS", None)
                if not isinstance(settings_type, type) or not hasattr(
                    unit_class, "INPUT_SETTINGS"
                ):
                    continue

                base_name = _spec_name(spec)
                occurrence = counts.get(base_name, 0) + 1
                counts[base_name] = occurrence
                name = base_name if occurrence == 1 else f"{base_name}_{occurrence}"
                graph_id = self._graph_id if self._graph_id is not None else "graph"
                topic = f"{topic_prefix}.{graph_id}.{name}.settings"
                bindings.append(
                    ProcessorSettingsBinding(
                        name=name,
                        title=_spec_title(spec, occurrence),
                        node_id=stage.stage_id,
                        processor_index=processor_index,
                        settings_type=settings_type,
                        topic=topic,
                        initial_settings=_initial_settings(unit, settings_type),
                    )
                )

        return bindings

    def _collect_input_bindings(
        self,
        topic_prefix: str,
    ) -> list[ProcessorInputBinding]:
        bindings: list[ProcessorInputBinding] = []

        for stage in self._stages:
            for processor_index, spec in enumerate(stage.processors):
                _inner, bound = _unwrap_bound_processor(spec)
                if bound is None or not bound.inputs:
                    continue

                for input_name, topic in bound.inputs.items():
                    bindings.append(
                        ProcessorInputBinding(
                            node_id=stage.stage_id,
                            processor_index=processor_index,
                            input_name=input_name,
                            topic=normalize_topic(topic),
                        )
                    )

        return bindings


def _unwrap_bound_processor(
    spec: ProcessorSpec,
) -> tuple[ProcessorSpec, BoundProcessor | None]:
    if isinstance(spec, BoundProcessor):
        return spec.processor, spec
    return spec, None


def _spec_name(spec: ProcessorSpec) -> str:
    inner, bound = _unwrap_bound_processor(spec)
    if bound is not None and bound.name:
        return bound.name

    if isinstance(inner, tuple):
        unit_class, _settings = inner
        name = unit_class.__name__
    elif isinstance(inner, ez.Unit):
        name = type(inner).__name__
    elif isinstance(inner, type):
        name = inner.__name__
    else:
        name = type(inner).__name__

    return _to_snake_case(name)


def _spec_title(spec: ProcessorSpec, occurrence: int) -> str:
    inner, bound = _unwrap_bound_processor(spec)
    if bound is not None and bound.name:
        return bound.name

    if isinstance(inner, tuple):
        unit_class, _settings = inner
        base = unit_class.__name__
    elif isinstance(inner, ez.Unit):
        base = type(inner).__name__
    elif isinstance(inner, type):
        base = inner.__name__
    else:
        base = type(inner).__name__

    return base if occurrence == 1 else f"{base} {occurrence}"


def _to_snake_case(name: str) -> str:
    first = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", first).lower()


def _initial_settings(unit: ez.Unit, settings_type: type[Any]) -> Any | None:
    current = getattr(unit, "SETTINGS", None)
    if isinstance(current, settings_type):
        return current
    try:
        return settings_type()
    except Exception:
        return None


def normalize_topic(topic: str | Enum) -> str:
    if isinstance(topic, Enum):
        return topic.name
    if isinstance(topic, str):
        return topic
    raise TypeError(f"Unsupported topic type: {type(topic)!r}")
