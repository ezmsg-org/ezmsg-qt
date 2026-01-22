"""Sidecar GraphRunner for parallel processor groups."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezmsg.core as ez

from .chain import _to_unit
from .gate import MessageGate
from .gate import MessageGateSettings

if TYPE_CHECKING:
    from .chain import ProcessorChain


# Common input/output stream name patterns in order of priority
_INPUT_STREAM_NAMES = ("INPUT_SIGNAL", "INPUT")
_OUTPUT_STREAM_NAMES = ("OUTPUT_SIGNAL", "OUTPUT")


def _detect_stream_names(unit: ez.Unit) -> tuple[str, str]:
    """Detect input and output stream names for a unit.

    Checks for common stream name patterns on the unit class.
    Returns the first matching input/output pair found.

    Args:
        unit: An instantiated ez.Unit.

    Returns:
        Tuple of (input_stream_name, output_stream_name).

    Raises:
        ValueError: If no known stream names are found.
    """
    unit_class = type(unit)

    input_name = None
    for name in _INPUT_STREAM_NAMES:
        if hasattr(unit_class, name):
            input_name = name
            break

    output_name = None
    for name in _OUTPUT_STREAM_NAMES:
        if hasattr(unit_class, name):
            output_name = name
            break

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


def build_sidecar_components(
    chains: list[ProcessorChain],
) -> tuple[dict[str, ez.Unit], list[tuple[str, str]]]:
    """
    Build components and connections for sidecar GraphRunner.

    Creates the ezmsg components needed to run parallel processor groups
    in a separate process.

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

        # Get parallel groups only
        parallel_groups = [g for g in chain.groups if g.parallel]
        if not parallel_groups:
            continue

        chain_id = chain._chain_id
        source_topic = str(chain.source_topic)
        print(
            f"[Sidecar] Building for chain {chain_id}, source_topic={source_topic}",
            flush=True,
        )

        # Create gate unit (shared for all parallel groups in this chain)
        gate = MessageGate()
        gate.apply_settings(MessageGateSettings(start_open=True))
        gate_name = f"{chain_id}_gate"
        components[gate_name] = gate

        # Connect source topic to gate input
        connections.append((source_topic, f"{gate_name}/INPUT"))

        # Connect gate control topic
        gate_control_topic = f"_qt.{chain_id}.gate"
        connections.append((gate_control_topic, f"{gate_name}/INPUT_GATE"))

        # Track previous output for chaining
        prev_output = f"{gate_name}/OUTPUT"
        proc_index = 0

        # Process each parallel group
        for group in parallel_groups:
            # Create processor units for this group
            for spec in group.processors:
                unit = _to_unit(spec)
                proc_name = f"{chain_id}_proc_{proc_index}"
                components[proc_name] = unit

                # Detect stream names for this unit
                input_name, output_name = _detect_stream_names(unit)

                # Connect previous output to this processor's input
                connections.append((prev_output, f"{proc_name}/{input_name}"))
                prev_output = f"{proc_name}/{output_name}"
                proc_index += 1

        # Connect final output to chain output topic
        output_topic = f"_qt.{chain_id}.out"
        connections.append((prev_output, output_topic))

    return components, connections
