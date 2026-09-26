from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qtpy import QtCore
from qtpy import QtWidgets

from .chain import ProcessorGraph
from .chain import ProcessorSettingsBinding
from .publisher import EzPublisher
from .session import EzSession
from .settings_form import SettingsForm


_DIRTY_SECTION_STYLE = (
    "QGroupBox {"
    " border: 1px solid #c77d00;"
    " border-radius: 6px;"
    " margin-top: 8px;"
    " padding-top: 8px;"
    " background: rgba(199, 125, 0, 0.08);"
    "}"
    "QGroupBox::title {"
    " subcontrol-origin: margin;"
    " left: 10px;"
    " padding: 0 4px;"
    " color: #8a5a00;"
    "}"
)
_DIRTY_BUTTON_STYLE = (
    "QPushButton { background: #fff2cc; border: 1px solid #c77d00; }"
    "QPushButton:disabled { color: #888888; background: #f0f0f0; border: 1px solid #cccccc; }"
)


@dataclass
class _SettingsSection:
    binding: ProcessorSettingsBinding
    group: QtWidgets.QGroupBox
    form: SettingsForm
    apply_button: QtWidgets.QPushButton
    publisher: EzPublisher
    last_applied: Any | None
    base_title: str


class ProcessorSettingsPanel(QtWidgets.QWidget):
    """Settings forms for runtime-configurable processors in a graph."""

    def __init__(
        self,
        graph: ProcessorGraph,
        session: EzSession,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self._graph = graph
        self._session = session
        self._sections: list[_SettingsSection] = []
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Maximum,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        bindings = graph.settings_bindings()
        if not bindings:
            empty = QtWidgets.QLabel("No runtime settings available.")
            empty.setWordWrap(True)
            layout.addWidget(empty)
            layout.addStretch()
            return

        for binding in bindings:
            section = self._create_section(binding)
            self._sections.append(section)
            layout.addWidget(section.group)

        layout.addStretch()

    @classmethod
    def from_graph(
        cls,
        graph: ProcessorGraph,
        *,
        session: EzSession | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> ProcessorSettingsPanel:
        resolved_session = graph.session if session is None else session
        if resolved_session is None:
            raise RuntimeError(
                "ProcessorGraph must be attached to a session before building settings UI"
            )
        if graph.session is not None and graph.session is not resolved_session:
            raise RuntimeError(
                "ProcessorSettingsPanel session does not match graph session"
            )
        if graph.session is None:
            raise RuntimeError(
                "ProcessorGraph must be attached to a session before building settings UI"
            )
        return cls(graph, resolved_session, parent=parent)

    @property
    def sections(self) -> tuple[QtWidgets.QGroupBox, ...]:
        return tuple(section.group for section in self._sections)

    def _create_section(self, binding: ProcessorSettingsBinding) -> _SettingsSection:
        title = binding.title
        group = QtWidgets.QGroupBox(title, self)
        group.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Maximum,
            QtWidgets.QSizePolicy.Policy.Maximum,
        )
        layout = QtWidgets.QVBoxLayout(group)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        form = SettingsForm(
            binding.settings_type, initial=binding.initial_settings, parent=group
        )
        layout.addWidget(form)

        controls = QtWidgets.QHBoxLayout()
        controls.addStretch()
        apply_button = QtWidgets.QPushButton("Apply", group)
        apply_button.setEnabled(False)
        controls.addWidget(apply_button)
        layout.addLayout(controls)

        publisher = EzPublisher(binding.topic, parent=group, session=self._session)
        section = _SettingsSection(
            binding=binding,
            group=group,
            form=form,
            apply_button=apply_button,
            publisher=publisher,
            last_applied=form.get_settings(),
            base_title=title,
        )

        form.settings_changed.connect(
            lambda _section=section: self._update_dirty_state(_section)
        )
        apply_button.clicked.connect(
            lambda _checked=False, _section=section: self._apply_section(_section)
        )
        self._update_dirty_state(section)
        return section

    def _is_dirty(self, section: _SettingsSection) -> bool:
        return section.form.get_settings() != section.last_applied

    def _update_dirty_state(self, section: _SettingsSection) -> None:
        dirty = self._is_dirty(section)
        section.apply_button.setEnabled(dirty)
        section.group.setTitle(
            f"{section.base_title} *" if dirty else section.base_title
        )
        section.group.setStyleSheet(_DIRTY_SECTION_STYLE if dirty else "")
        section.apply_button.setStyleSheet(_DIRTY_BUTTON_STYLE if dirty else "")

    def _apply_section(self, section: _SettingsSection) -> None:
        settings = section.form.get_settings()
        section.publisher.emit(settings)
        section.last_applied = settings
        self._update_dirty_state(section)
