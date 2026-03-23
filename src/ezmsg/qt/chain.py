"""ProcessorChain - Fluent API for compiled processing pipelines."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Any
from typing import cast
from typing import Literal
from typing import TYPE_CHECKING

import ezmsg.core as ez
from qtpy import QtCore
from qtpy import QtWidgets

if TYPE_CHECKING:
    from .session import EzSession

# Type alias for processor specifications
# A processor can be specified as:
# - Unit class: LowPassFilter
# - Unit class with settings: (LowPassFilter, LowPassSettings(...))
# - Transformer instance: MyTransformer(factor=2)
ProcessorSpec = type[ez.Unit] | tuple[type[ez.Unit], ez.Settings] | Any
AutoGatePosition = Literal["input", "output"]


def _is_process_safe(spec: ProcessorSpec) -> bool:
    if isinstance(spec, ez.Unit):
        return True
    if isinstance(spec, tuple):
        unit_class, _settings = spec
        return isinstance(unit_class, type) and issubclass(unit_class, ez.Unit)
    return isinstance(spec, type) and issubclass(spec, ez.Unit)


def _to_unit(spec: ProcessorSpec) -> ez.Unit:
    """Convert a ProcessorSpec to an ez.Unit instance.

    Args:
        spec: A Unit instance, Unit class, (class, settings) tuple,
            or transformer instance.

    Returns:
        An instantiated ez.Unit ready for use.

    Raises:
        TypeError: If spec is not a recognized processor type.
    """
    if isinstance(spec, ez.Unit):
        # Already instantiated unit (settings already applied)
        return spec
    elif isinstance(spec, tuple):
        # (UnitClass, settings) tuple
        unit_class, settings = spec
        unit = unit_class()
        unit.apply_settings(settings)
        return unit
    elif isinstance(spec, type) and issubclass(spec, ez.Unit):
        # Unit class without settings
        return spec()
    elif hasattr(spec, "__acall__"):
        # BaseProcessor instance (has async call method)
        from .adapter import TransformerAdapter

        return TransformerAdapter(spec)
    else:
        raise TypeError(
            f"Expected Unit class, (class, settings) tuple, or processor instance "
            f"with __acall__, got {type(spec)}"
        )


@dataclass
class ProcessorGroup:
    """A group of processors that run together in the same execution context."""

    processors: list[ProcessorSpec] = field(default_factory=list)
    mode: Literal["shared", "process"] = "shared"


@dataclass(frozen=True)
class ExternalInputBinding:
    """Bind a public ezmsg topic to an internal processor input stream."""

    topic: Enum | str
    group_index: int
    processor_index: int
    input_name: str


class ProcessorChain:
    """
    Fluent builder for processor chains.

    ProcessorChain accumulates processor groups that will be executed
    in sequence inside a sidecar ezmsg runtime owned by :class:`EzSession`.

    - ``parallel()`` runs a group in its own sidecar process.
    - ``local()`` runs a group in the shared sidecar process.

    Neither mode runs work on the Qt UI thread.

        Example:
            # Using Unit classes
            chain = (
                ProcessorChain(Topic.RAW, parent=widget, auto_gate=True)
                .parallel(LowPassFilter, ScaleProcessor)
                .local(ThresholdDetector)
                .connect(widget.on_data)
            )

            # Using Unit classes with settings
            chain = (
                ProcessorChain(Topic.RAW, parent=widget, auto_gate=True)
                .parallel((LowPassFilter, LowPassSettings(alpha=0.5)))
                .connect(widget.on_data)
            )

            # Using transformer instances
            chain = (
                ProcessorChain(Topic.RAW, parent=widget, auto_gate=True)
                .parallel(LowPassFilter(), ScaleProcessor(factor=2))
                .connect(widget.on_data)
            )
    """

    def __init__(
        self,
        source_topic: Enum | str,
        parent: QtWidgets.QWidget | None = None,
        auto_gate: bool = False,
        auto_gate_position: AutoGatePosition = "input",
    ):
        """Create a processor chain.

        Args:
            source_topic: The topic name to subscribe to.
            parent: Optional parent widget for auto-gating.
            auto_gate: If True, gate based on parent widget visibility.
            auto_gate_position: Place the gate before processors ("input") or
                after processors ("output").
        """
        if auto_gate_position not in ("input", "output"):
            raise ValueError("auto_gate_position must be 'input' or 'output'")
        validated_auto_gate_position = cast(AutoGatePosition, auto_gate_position)

        self._source_topic = source_topic
        self._parent_widget = parent
        self._auto_gate = auto_gate
        self._auto_gate_position: AutoGatePosition = validated_auto_gate_position
        self._groups: list[ProcessorGroup] = []
        self._external_inputs: list[ExternalInputBinding] = []
        self._handler: Callable[[Any], None] | None = None
        self._chain_id: str | None = None
        self._session: EzSession | None = None
        self._attached = False
        self._visibility_filter: Any | None = None

    @property
    def source_topic(self) -> Enum | str:
        """The source topic this chain subscribes to."""
        return self._source_topic

    @property
    def groups(self) -> list[ProcessorGroup]:
        """The processor groups in this chain."""
        return self._groups

    @property
    def parent_widget(self) -> QtWidgets.QWidget | None:
        """The parent widget for auto-gating."""
        return self._parent_widget

    @property
    def auto_gate(self) -> bool:
        """Whether auto-gating based on visibility is enabled."""
        return self._auto_gate

    @property
    def auto_gate_position(self) -> AutoGatePosition:
        """Whether the gate sits at the chain input or output."""
        return self._auto_gate_position

    @property
    def handler(self) -> Callable[[Any], None] | None:
        """The Qt handler connected to this chain's output."""
        return self._handler

    @property
    def external_inputs(self) -> list[ExternalInputBinding]:
        """External topic bindings into specific processor input streams."""
        return self._external_inputs

    def parallel(self, *processors: ProcessorSpec) -> ProcessorChain:
        """Add processors to run in an isolated sidecar process.

        Multiple processors passed to a single parallel() call will be
        grouped together in the same process.

        Args:
            *processors: Unit classes, (class, settings) tuples, or
                ez.Unit instances.

        Returns:
            Self for method chaining.

        Example:
            chain.parallel(LowPassFilter, ScaleProcessor)  # same process
            chain.parallel(FFT)  # different process

        Note:
            ``parallel()`` only supports ez.Unit-based processors. Transformer
            instances with ``__acall__`` are only supported by ``local()``.
        """
        self._groups.append(ProcessorGroup(processors=list(processors), mode="process"))
        return self

    def local(self, *processors: ProcessorSpec) -> ProcessorChain:
        """Add processors to run in the shared sidecar process.

        Multiple processors passed to a single local() call will be
        grouped together.

        Args:
            *processors: Unit classes, (class, settings) tuples, or
                transformer instances.

        Returns:
            Self for method chaining.

        Example:
            chain.local(ThresholdDetector)  # runs in shared sidecar process
        """
        self._groups.append(ProcessorGroup(processors=list(processors), mode="shared"))
        return self

    def connect(self, slot: Callable[[Any], None]) -> ProcessorChain:
        """Connect the chain output to a Qt handler.

        This finalizes the chain configuration. The handler will be
        called with each processed message.

        Args:
            slot: A callable that receives processed messages.
        """
        self._handler = slot
        return self

    def bind_input(
        self,
        topic: Enum | str,
        *,
        group_index: int = -1,
        processor_index: int = 0,
        input_name: str = "INPUT_SETTINGS",
    ) -> ProcessorChain:
        """Bind a public topic to an internal processor input stream.

        This is primarily useful for runtime settings updates, e.g. wiring a
        ``*.settings`` topic into a processor group's ``INPUT_SETTINGS`` stream.
        Negative indices follow standard Python indexing rules.
        """

        self._external_inputs.append(
            ExternalInputBinding(
                topic=topic,
                group_index=group_index,
                processor_index=processor_index,
                input_name=input_name,
            )
        )
        return self

    @property
    def session(self) -> EzSession | None:
        """The session this pipeline is attached to, if any."""
        return self._session

    @property
    def attached(self) -> bool:
        """Whether this pipeline has been attached to a session."""
        return self._attached

    def attach(self, session: EzSession) -> ProcessorChain:
        """Attach this pipeline to a session.

        The pipeline must be fully configured before attachment.
        """
        session.attach(self)
        return self

    def _bind_session(self, session: EzSession) -> None:
        if self._session is not None and self._session is not session:
            raise RuntimeError(
                "ProcessorChain is already attached to a different session"
            )
        self._session = session
        self._attached = True

    def _validate(self) -> None:
        if not self._groups:
            raise ValueError("ProcessorChain must define at least one processor group")
        if self._handler is None:
            raise ValueError("ProcessorChain must connect a handler before attachment")
        for group in self._groups:
            if group.mode != "process":
                continue
            for spec in group.processors:
                if not _is_process_safe(spec):
                    raise TypeError(
                        "parallel() only supports ez.Unit classes, ez.Unit instances, "
                        "or (UnitClass, Settings) tuples"
                    )

        for binding in self._external_inputs:
            group_index = binding.group_index
            if group_index < 0:
                group_index += len(self._groups)
            if group_index < 0 or group_index >= len(self._groups):
                raise IndexError(
                    f"External input binding group index out of range: {binding.group_index}"
                )

            processors = self._groups[group_index].processors
            processor_index = binding.processor_index
            if processor_index < 0:
                processor_index += len(processors)
            if processor_index < 0 or processor_index >= len(processors):
                raise IndexError(
                    "External input binding processor index out of range: "
                    f"{binding.processor_index}"
                )
