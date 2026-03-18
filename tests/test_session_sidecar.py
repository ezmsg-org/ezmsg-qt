"""Tests for sidecar integration with EzSession."""

from ezmsg.qt.session import EzSession


def test_session_has_sidecar_attribute():
    """EzSession should have sidecar-related attributes."""
    from qtpy import QtWidgets

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    session = EzSession()

    assert hasattr(session, "_sidecar")
    assert session._sidecar is None  # Not started yet
