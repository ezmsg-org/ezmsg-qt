"""Tests for sidecar integration with EzGuiBridge."""

from ezmsg.qt.bridge import EzGuiBridge


def test_bridge_has_sidecar_attribute():
    """EzGuiBridge should have sidecar-related attributes."""
    from qtpy import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    bridge = EzGuiBridge(app)

    assert hasattr(bridge, "_sidecar")
    assert bridge._sidecar is None  # Not started yet
