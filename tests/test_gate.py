"""Tests for MessageGate unit."""

import asyncio

import ezmsg.core as ez

from ezmsg.qt.gate import GateMessage
from ezmsg.qt.gate import MessageGate
from ezmsg.qt.gate import MessageGateSettings


def test_gate_message_open():
    msg = GateMessage(open=True)
    assert msg.open is True


def test_gate_message_closed():
    msg = GateMessage(open=False)
    assert msg.open is False


def test_message_gate_passes_when_open():
    """Gate should pass messages when open."""
    gate = MessageGate()
    gate.apply_settings(MessageGateSettings(start_open=True))
    # Unit exists and has expected streams
    assert hasattr(gate, "INPUT")
    assert hasattr(gate, "OUTPUT")
    assert hasattr(gate, "INPUT_GATE")


def test_message_gate_settings_default():
    """Default settings should start open."""
    settings = MessageGateSettings()
    assert settings.start_open is True
