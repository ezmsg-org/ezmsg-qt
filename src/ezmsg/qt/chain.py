"""ProcessorChain - Fluent API for chaining processors on subscriptions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Any
from typing import TYPE_CHECKING
from typing import Union

from qtpy import QtWidgets

import ezmsg.core as ez

if TYPE_CHECKING:
    pass

# Type alias for processor specifications
# A processor can be specified as:
# - Unit class: LowPassFilter
# - Unit class with settings: (LowPassFilter, LowPassSettings(...))
# - Transformer instance: MyTransformer(factor=2)
ProcessorSpec = Union[
    type[ez.Unit],  # Unit class
    tuple[type[ez.Unit], ez.Settings],  # (Unit class, settings)
    Any,  # transformer instance (BaseProcessor or similar)
]


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
    parallel: bool = False  # True = sidecar process, False = bridge thread


class ProcessorChain:
    """
    Fluent builder for processor chains.

    ProcessorChain accumulates processor groups that will be executed
    in sequence. Groups can run in parallel (sidecar process) or locally
    (bridge thread).

    Example:
        # Using Unit classes
        chain = (
            ProcessorChain(Topic.RAW, parent=widget)
            .parallel(LowPassFilter, ScaleProcessor)  # grouped in sidecar
            .local(ThresholdDetector)  # bridge thread
            .connect(widget.on_data)
        )

        # Using Unit classes with settings
        chain = (
            ProcessorChain(Topic.RAW, parent=widget)
            .parallel((LowPassFilter, LowPassSettings(alpha=0.5)))
            .connect(widget.on_data)
        )

        # Using transformer instances
        chain = (
            ProcessorChain(Topic.RAW, parent=widget)
            .parallel(LowPassFilter(), ScaleProcessor(factor=2))
            .connect(widget.on_data)
        )
    """

    def __init__(
        self,
        source_topic: Enum,
        parent: QtWidgets.QWidget | None = None,
        auto_gate: bool = True,
    ):
        """Create a processor chain.

        Args:
            source_topic: The topic enum to subscribe to.
            parent: Optional parent widget for auto-gating.
            auto_gate: If True, gate based on parent widget visibility.
        """
        from .bridge import _register_chain

        self._source_topic = source_topic
        self._parent_widget = parent
        self._auto_gate = auto_gate
        self._groups: list[ProcessorGroup] = []
        self._handler: Callable[[Any], None] | None = None
        self._chain_id: str | None = None  # Set by bridge during registration

        # Register with the bridge
        _register_chain(self)

    @property
    def source_topic(self) -> Enum:
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
    def handler(self) -> Callable[[Any], None] | None:
        """The Qt handler connected to this chain's output."""
        return self._handler

    def parallel(self, *processors: ProcessorSpec) -> ProcessorChain:
        """Add processors to run in a sidecar process.

        Multiple processors passed to a single parallel() call will be
        grouped together in the same process.

        Args:
            *processors: Unit classes, (class, settings) tuples, or
                transformer instances.

        Returns:
            Self for method chaining.

        Example:
            chain.parallel(LowPassFilter, ScaleProcessor)  # same process
            chain.parallel(FFT)  # different process
        """
        self._groups.append(ProcessorGroup(processors=list(processors), parallel=True))
        return self

    def local(self, *processors: ProcessorSpec) -> ProcessorChain:
        """Add processors to run in the bridge thread.

        Multiple processors passed to a single local() call will be
        grouped together.

        Args:
            *processors: Unit classes, (class, settings) tuples, or
                transformer instances.

        Returns:
            Self for method chaining.

        Example:
            chain.local(ThresholdDetector)  # runs in bridge thread
        """
        self._groups.append(ProcessorGroup(processors=list(processors), parallel=False))
        return self

    def connect(self, slot: Callable[[Any], None]) -> None:
        """Connect the chain output to a Qt handler.

        This finalizes the chain configuration. The handler will be
        called with each processed message.

        Args:
            slot: A callable that receives processed messages.
        """
        self._handler = slot
