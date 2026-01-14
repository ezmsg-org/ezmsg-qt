"""Tests for MessageGate unit."""

from ezmsg.qt.gate import GateMessage


def test_gate_message_open():
    msg = GateMessage(open=True)
    assert msg.open is True


def test_gate_message_closed():
    msg = GateMessage(open=False)
    assert msg.open is False
