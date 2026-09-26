from __future__ import annotations

from collections.abc import AsyncGenerator
from enum import Enum

import ezmsg.core as ez
from qtpy import QtCore
from qtpy import QtWidgets

from ezmsg.qt import BoundProcessor
from ezmsg.qt import EzPublisher
from ezmsg.qt import EzSession
from ezmsg.qt import ProcessorGraph
from ezmsg.qt import ProcessorSettingsPanel
from ezmsg.qt import SettingsForm


class DemoTopic(Enum):
    INPUT = "INPUT"


class GainSettings(ez.Settings):
    factor: int = 2


class GainProcessor(ez.Unit):
    SETTINGS = GainSettings
    INPUT = ez.InputStream(float)
    INPUT_SETTINGS = ez.InputStream(GainSettings)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT_SETTINGS)
    async def on_settings(self, msg: GainSettings) -> None:
        self.apply_settings(msg)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg * self.SETTINGS.factor


class PassthroughProcessor(ez.Unit):
    INPUT = ez.InputStream(float)
    OUTPUT = ez.OutputStream(float)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def process(self, msg: float) -> AsyncGenerator:
        yield self.OUTPUT, msg


def test_processor_settings_panel_only_shows_settings_capable_processors(qtbot):
    session = EzSession()
    graph = (
        ProcessorGraph(DemoTopic.INPUT)
        .local(PassthroughProcessor, BoundProcessor(GainProcessor, name="gain"))
        .connect(lambda _msg: None)
        .attach(session)
    )

    panel = ProcessorSettingsPanel.from_graph(graph)
    qtbot.addWidget(panel)

    assert len(panel.sections) == 1
    assert panel.sections[0].title() == "gain"
    assert panel.findChild(SettingsForm) is not None


def test_processor_settings_panel_applies_settings_and_tracks_dirty_state(qtbot):
    session = EzSession()
    host = QtWidgets.QWidget()
    qtbot.addWidget(host)

    received: list[float] = []
    graph = (
        ProcessorGraph(DemoTopic.INPUT, parent=host)
        .local(BoundProcessor(GainProcessor, name="gain"))
        .connect(received.append)
        .attach(session)
    )
    panel = ProcessorSettingsPanel.from_graph(graph, parent=host)
    qtbot.addWidget(panel)
    input_pub = EzPublisher(DemoTopic.INPUT, parent=host, session=session)

    form = panel.findChild(SettingsForm)
    assert form is not None
    spin = form.findChild(QtWidgets.QSpinBox)
    assert spin is not None
    apply_button = panel.findChild(QtWidgets.QPushButton)
    assert apply_button is not None
    section = panel.sections[0]

    with session:
        input_pub.emit(2.0)
        qtbot.waitUntil(lambda: received == [4.0], timeout=2000)

        spin.setValue(5)
        qtbot.waitUntil(apply_button.isEnabled, timeout=1000)
        assert section.title().endswith("*")

        qtbot.mouseClick(apply_button, QtCore.Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: not apply_button.isEnabled(), timeout=1000)
        assert section.title() == "gain"

        input_pub.emit(2.0)
        qtbot.waitUntil(lambda: received[-1] == 10.0, timeout=2000)
