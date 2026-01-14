"""Visibility tracking for auto-gating processor chains."""

from collections.abc import Callable

from qtpy import QtCore
from qtpy import QtWidgets


class VisibilityFilter(QtCore.QObject):
    """
    Event filter that tracks widget visibility changes.

    Installs on a QWidget and calls a callback when the widget
    becomes visible or hidden.
    """

    def __init__(
        self,
        callback: Callable[[bool], None],
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent)
        self._callback = callback
        self._last_visible: bool | None = None

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        """Filter show/hide events."""
        if event.type() == QtCore.QEvent.Type.Show:
            if self._last_visible is not True:
                self._last_visible = True
                self._callback(True)
        elif event.type() == QtCore.QEvent.Type.Hide:
            if self._last_visible is not False:
                self._last_visible = False
                self._callback(False)

        return False  # Don't consume the event
