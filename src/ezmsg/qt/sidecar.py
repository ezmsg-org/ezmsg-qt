"""Sidecar GraphRunner for in_process processor stages."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezmsg.core as ez

from .gate import MessageGate
from .gate import MessageGateSettings

if TYPE_CHECKING:
    from .chain import ProcessorChain


def build_sidecar_components(
    chains: list[ProcessorChain],
) -> tuple[dict[str, ez.Unit], list[tuple[str, str]]]:
    """
    Build components and connections for sidecar GraphRunner.

    Args:
        chains: List of ProcessorChains to process.

    Returns:
        Tuple of (components dict, connections list).
    """
    components: dict[str, ez.Unit] = {}
    connections: list[tuple[str, str]] = []

    for chain in chains:
        if chain._chain_id is None:
            continue

        # Get in_process stages only
        in_process_stages = [s for s in chain.stages if s.in_process]
        if not in_process_stages:
            continue

        chain_id = chain._chain_id
        source_topic = str(chain.source_topic)

        # Create gate unit
        gate = MessageGate()
        gate.apply_settings(MessageGateSettings(start_open=True))
        gate_name = f"{chain_id}_gate"
        components[gate_name] = gate

        # Connect source topic to gate input
        connections.append((source_topic, f"{gate_name}/INPUT"))

        # Connect gate control topic
        gate_control_topic = f"_qt.{chain_id}.gate"
        connections.append((gate_control_topic, f"{gate_name}/INPUT_GATE"))

        # Create processor units
        prev_output = f"{gate_name}/OUTPUT"
        for i, stage in enumerate(in_process_stages):
            unit = stage.unit_class()
            if stage.settings:
                unit.apply_settings(stage.settings)

            proc_name = f"{chain_id}_proc_{i}"
            components[proc_name] = unit

            # Connect previous output to this processor's input
            connections.append((prev_output, f"{proc_name}/INPUT"))
            prev_output = f"{proc_name}/OUTPUT"

        # Connect final output to chain output topic
        output_topic = f"_qt.{chain_id}.out"
        connections.append((prev_output, output_topic))

    return components, connections
