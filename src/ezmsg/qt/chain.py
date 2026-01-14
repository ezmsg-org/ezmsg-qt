"""ProcessorChain - Fluent API for chaining processors on subscriptions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any
from typing import TYPE_CHECKING

from qtpy import QtWidgets

import ezmsg.core as ez

if TYPE_CHECKING:
    from ezmsg.core.unit import Unit


@dataclass
class ProcessorStage:
    """A single processor stage in a chain."""

    unit_class: type[Unit]
    settings: ez.Settings | None
    in_process: bool


class ProcessorChain:
    """
    Fluent builder for processor chains.

    ProcessorChain accumulates processor stages that will be executed
    in sequence. Stages can run in the bridge thread (default) or in
    a separate sidecar process (in_process=True).

    Example:
        chain = ProcessorChain(Topic.RAW, widget)
        chain.process(Downsample, in_process=True)
             .process(FFT, in_process=True)
             .process(ToNumpy)
             .connect(widget.on_data)
    """

    def __init__(
        self,
        source_topic: Enum,
        parent_widget: QtWidgets.QWidget | None,
        auto_gate: bool = True,
    ):
        self._source_topic = source_topic
        self._parent_widget = parent_widget
        self._auto_gate = auto_gate
        self._stages: list[ProcessorStage] = []
        self._handler: Callable[[Any], None] | None = None
        self._gated: bool = False
        self._chain_id: str | None = None  # Set by bridge during registration

    @property
    def source_topic(self) -> Enum:
        """The source topic this chain subscribes to."""
        return self._source_topic

    @property
    def stages(self) -> list[ProcessorStage]:
        """The processor stages in this chain."""
        return self._stages

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

    def process(
        self,
        processor: type[Unit],
        settings: ez.Settings | None = None,
        *,
        in_process: bool = False,
    ) -> ProcessorChain:
        """
        Add a processor stage to the chain.

        Args:
            processor: The ezmsg Unit class to use as processor.
            settings: Optional settings to apply to the processor.
            in_process: If True, run in sidecar process for parallelism.

        Returns:
            Self for method chaining.
        """
        self._stages.append(ProcessorStage(processor, settings, in_process))
        return self

    def connect(self, slot: Callable[[Any], None]) -> None:
        """
        Connect the chain output to a Qt handler.

        This finalizes the chain configuration. The handler will be
        called with each processed message.

        Args:
            slot: A callable that receives processed messages.
        """
        self._handler = slot

    def set_gated(self, gated: bool) -> None:
        """
        Manually control the gate state.

        Args:
            gated: If True, block messages. If False, allow messages.
        """
        self._gated = gated
        # TODO: Publish gate message to control topic
