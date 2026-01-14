"""Gate unit for controlling message flow in processor chains."""

from dataclasses import dataclass


@dataclass
class GateMessage:
    """Control message for opening/closing a gate."""

    open: bool
