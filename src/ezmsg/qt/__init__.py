"""
ezmsg.qt - Qt integration for ezmsg with direct topic-based pub/sub.

This package provides Qt widgets that can subscribe to and publish messages
on ezmsg topics using a familiar Qt signal/slot pattern.

Example:
    from ezmsg.qt import EzSubscriber, EzPublisher, EzSession, ProcessorChain

    class MyWidget(QtWidgets.QWidget):
        def __init__(self, session):
            super().__init__()
            # Simple subscription (no processing)
            self.data_sub = EzSubscriber(MyTopic.OUTPUT, parent=self, session=session)
            self.data_sub.connect(self.on_data)

            # Processing pipeline with isolated and shared sidecar stages
            self.chain = (
                ProcessorChain(MyTopic.RAW, parent=self)
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

from .chain import ProcessorChain
from .gate import GateMessage
from .gate import MessageGate
from .gate import MessageGateSettings
from .publisher import EzPublisher
from .session import EzSession
from .settings_form import SettingsForm
from .subscriber import EzSubscriber

__all__ = [
    "EzSession",
    "EzPublisher",
    "EzSubscriber",
    "ProcessorChain",
    "SettingsForm",
    "GateMessage",
    "MessageGate",
    "MessageGateSettings",
]
