"""
ezmsg.qt - Qt integration for ezmsg with direct topic-based pub/sub.

This package provides Qt widgets that can subscribe to and publish messages
on ezmsg topics using a familiar Qt signal/slot pattern.

Example:
    from ezmsg.qt import EzSubscriber, EzPublisher, EzSession, ProcessorGraph

    class MyWidget(QtWidgets.QWidget):
        def __init__(self, session):
            super().__init__()
            # Simple subscription (no processing)
            self.data_sub = EzSubscriber(MyTopic.OUTPUT, parent=self, session=session)
            self.data_sub.connect(self.on_data)

            # Processing graph with isolated and shared sidecar stages
            self.graph = (
                ProcessorGraph(MyTopic.RAW, parent=self, auto_gate=True)
                .parallel(LowPassFilter, ScaleProcessor)
                .local(ThresholdDetector)
                .connect(self.on_processed)
                .attach(session)
            )

        def on_data(self, msg):
            pass

        def on_processed(self, msg):
            pass

    app = QtWidgets.QApplication([])
    session = EzSession()
    window = MyWidget(session)
    window.show()

    with session:
        app.exec()
"""

from .chain import BoundProcessor
from .chain import ProcessorGraph
from .gate import GateMessage
from .gate import MessageGate
from .gate import MessageGateSettings
from .publisher import EzPublisher
from .session import EzSession
from .settings_form import SettingsForm
from .settings_panel import ProcessorSettingsPanel
from .subscriber import EzSubscriber

__all__ = [
    "EzSession",
    "EzPublisher",
    "EzSubscriber",
    "ProcessorGraph",
    "BoundProcessor",
    "SettingsForm",
    "ProcessorSettingsPanel",
    "GateMessage",
    "MessageGate",
    "MessageGateSettings",
]
