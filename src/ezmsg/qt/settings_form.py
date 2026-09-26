from __future__ import annotations

import types
import typing
from dataclasses import dataclass
from enum import Enum
from typing import Any
from typing import get_args
from typing import get_origin
from typing import get_type_hints

from qtpy import QtCore
from qtpy import QtWidgets


@dataclass(frozen=True)
class SettingsFieldSpec:
    name: str
    typ: type[Any]
    optional: bool
    default: Any


def _unwrap_optional(typ: Any) -> tuple[bool, Any]:
    origin = get_origin(typ)
    if origin is None:
        return False, typ

    if origin not in (typing.Union, types.UnionType):
        return False, typ

    args = get_args(typ)
    non_none = [a for a in args if a is not type(None)]
    if len(non_none) == 1 and len(args) == 2:
        return True, non_none[0]
    return False, typ


def _iter_settings_fields(settings_type: type[Any]) -> list[SettingsFieldSpec]:
    hints = get_type_hints(settings_type, include_extras=True)
    specs: list[SettingsFieldSpec] = []
    for name, hint in hints.items():
        is_opt, inner = _unwrap_optional(hint)
        default = getattr(settings_type, name, None)
        specs.append(
            SettingsFieldSpec(
                name=name,
                typ=inner if isinstance(inner, type) else object,
                optional=is_opt,
                default=default,
            )
        )
    return specs


def _make_widget_for_type(typ: type[Any]) -> QtWidgets.QWidget:
    if typ is bool:
        return QtWidgets.QCheckBox()
    if typ is int:
        w = QtWidgets.QSpinBox()
        w.setRange(-2147483648, 2147483647)
        return w
    if typ is float:
        w = QtWidgets.QDoubleSpinBox()
        w.setDecimals(6)
        w.setRange(-1.0e12, 1.0e12)
        w.setSingleStep(0.1)
        return w
    if typ is str:
        return QtWidgets.QLineEdit()
    if isinstance(typ, type) and issubclass(typ, Enum):
        return QtWidgets.QComboBox()
    raise TypeError(f"Unsupported field type for settings form: {typ!r}")


def _get_widget_value(widget: QtWidgets.QWidget, typ: type[Any]) -> Any:
    if typ is bool:
        assert isinstance(widget, QtWidgets.QCheckBox)
        return widget.isChecked()
    if typ is int:
        assert isinstance(widget, QtWidgets.QSpinBox)
        return int(widget.value())
    if typ is float:
        assert isinstance(widget, QtWidgets.QDoubleSpinBox)
        return float(widget.value())
    if typ is str:
        assert isinstance(widget, QtWidgets.QLineEdit)
        return widget.text()
    if isinstance(typ, type) and issubclass(typ, Enum):
        assert isinstance(widget, QtWidgets.QComboBox)
        data = widget.currentData()
        if isinstance(data, typ):
            return data
        return typ[widget.currentText()]
    raise TypeError(f"Unsupported field type for settings form: {typ!r}")


def _set_widget_value(widget: QtWidgets.QWidget, typ: type[Any], value: Any) -> None:
    if typ is bool:
        assert isinstance(widget, QtWidgets.QCheckBox)
        widget.setChecked(bool(value))
        return
    if typ is int:
        assert isinstance(widget, QtWidgets.QSpinBox)
        widget.setValue(int(value))
        return
    if typ is float:
        assert isinstance(widget, QtWidgets.QDoubleSpinBox)
        widget.setValue(float(value))
        return
    if typ is str:
        assert isinstance(widget, QtWidgets.QLineEdit)
        widget.setText("" if value is None else str(value))
        return
    if isinstance(typ, type) and issubclass(typ, Enum):
        assert isinstance(widget, QtWidgets.QComboBox)
        if isinstance(value, typ):
            idx = widget.findData(value)
            if idx >= 0:
                widget.setCurrentIndex(idx)
                return
            widget.setCurrentText(value.name)
            return
        if isinstance(value, str):
            widget.setCurrentText(value)
            return
        raise TypeError(f"Enum field expects {typ.__name__} or str, got {type(value)}")
    raise TypeError(f"Unsupported field type for settings form: {typ!r}")


class SettingsForm(QtWidgets.QWidget):
    settings_changed = QtCore.Signal()  # pyright: ignore[reportPrivateImportUsage]

    def __init__(
        self,
        settings_type: type[Any],
        initial: Any | None = None,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self._settings_type = settings_type
        self._specs = _iter_settings_fields(settings_type)
        self._widgets: dict[str, QtWidgets.QWidget] = {}
        self._updating = False
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Maximum,
            QtWidgets.QSizePolicy.Policy.Maximum,
        )

        layout = QtWidgets.QFormLayout()
        layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint
        )
        layout.setFormAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop
        )
        layout.setLabelAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self.setLayout(layout)

        for spec in self._specs:
            widget = _make_widget_for_type(spec.typ)

            if isinstance(spec.typ, type) and issubclass(spec.typ, Enum):
                assert isinstance(widget, QtWidgets.QComboBox)
                for member in spec.typ:
                    widget.addItem(member.name, member)

            widget.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Maximum,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )

            self._widgets[spec.name] = widget
            layout.addRow(spec.name, widget)

        self._updating = True
        if initial is not None:
            self.set_settings(initial)
        else:
            for spec in self._specs:
                if spec.optional and spec.default is None:
                    continue
                try:
                    _set_widget_value(self._widgets[spec.name], spec.typ, spec.default)
                except Exception:
                    pass
        self._updating = False

        for spec in self._specs:
            self._connect_widget(spec, self._widgets[spec.name])

    @property
    def settings_type(self) -> type[Any]:
        return self._settings_type

    def get_settings(self) -> Any:
        values: dict[str, Any] = {}
        for spec in self._specs:
            widget = self._widgets[spec.name]
            value = _get_widget_value(widget, spec.typ)
            values[spec.name] = value
        return self._settings_type(**values)

    def set_settings(self, settings: Any) -> None:
        self._updating = True
        for spec in self._specs:
            if not hasattr(settings, spec.name):
                continue
            value = getattr(settings, spec.name)
            _set_widget_value(self._widgets[spec.name], spec.typ, value)
        self._updating = False

    def _connect_widget(
        self,
        spec: SettingsFieldSpec,
        widget: QtWidgets.QWidget,
    ) -> None:
        if spec.typ is bool:
            assert isinstance(widget, QtWidgets.QCheckBox)
            widget.toggled.connect(self._emit_settings_changed)
            return
        if spec.typ is int:
            assert isinstance(widget, QtWidgets.QSpinBox)
            widget.valueChanged.connect(self._emit_settings_changed)
            return
        if spec.typ is float:
            assert isinstance(widget, QtWidgets.QDoubleSpinBox)
            widget.valueChanged.connect(self._emit_settings_changed)
            return
        if spec.typ is str:
            assert isinstance(widget, QtWidgets.QLineEdit)
            widget.textChanged.connect(self._emit_settings_changed)
            return
        if isinstance(spec.typ, type) and issubclass(spec.typ, Enum):
            assert isinstance(widget, QtWidgets.QComboBox)
            widget.currentIndexChanged.connect(self._emit_settings_changed)

    def _emit_settings_changed(self, *_args: Any) -> None:
        if not self._updating:
            self.settings_changed.emit()
