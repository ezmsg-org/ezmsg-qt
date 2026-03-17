"""Gate unit for controlling message flow in processor chains."""

import logging
from dataclasses import dataclass
from typing import Any
from typing import AsyncGenerator

import ezmsg.core as ez

logger = logging.getLogger(__name__)


@dataclass
class GateMessage:
    """Control message for opening/closing a gate."""

    open: bool


class MessageGateSettings(ez.Settings):
    """Settings for MessageGate unit."""

    start_open: bool = True


class MessageGateState(ez.State):
    """Runtime state for MessageGate unit."""

    is_open: bool


class MessageGate(ez.Unit):
    """
    Gate unit that passes or blocks messages based on control input.

    When the gate is open, messages flow through. When closed, messages
    are dropped. Gate state is controlled via INPUT_GATE stream.
    """

    SETTINGS = MessageGateSettings
    STATE = MessageGateState

    INPUT = ez.InputStream(Any)
    OUTPUT = ez.OutputStream(Any)
    INPUT_GATE = ez.InputStream(GateMessage)

    async def initialize(self) -> None:
        self.STATE.is_open = self.SETTINGS.start_open
        logger.debug(f"MessageGate initialized: is_open={self.STATE.is_open}")

    @ez.subscriber(INPUT_GATE)
    async def on_gate(self, msg: GateMessage) -> None:
        """Handle gate control messages."""
        old_state = self.STATE.is_open
        self.STATE.is_open = msg.open
        logger.info(f"Gate state changed: {old_state} -> {msg.open}")

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def on_message(self, msg: Any) -> AsyncGenerator:
        """Pass message through if gate is open."""
        if self.STATE.is_open:
            yield self.OUTPUT, msg
