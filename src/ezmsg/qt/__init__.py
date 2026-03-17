"""
ezmsg.qt - Qt integration for ezmsg with direct topic-based pub/sub.

This package provides Qt widgets that can subscribe to and publish messages
on ezmsg topics using a familiar Qt signal/slot pattern.

Example:
    from ezmsg.qt import EzSubscriber, EzPublisher, EzGuiBridge, ProcessorChain

    class MyWidget(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            # Simple subscription (no processing)
            self.bridge = bridge
            self.data_sub = EzSubscriber(MyTopic.OUTPUT, parent=self, bridge=bridge)
            self.data_sub.connect(self.on_data)

            # Processing pipeline with isolated and shared sidecar stages
            self.chain = (
                ProcessorChain(MyTopic.RAW, parent=self)
                .parallel(LowPassFilter, ScaleProcessor)
                .local(ThresholdDetector)
                .connect(self.on_processed)
                .attach(bridge)
            )

        def on_data(self, msg):
            pass

        def on_processed(self, msg):
            pass

    app = QtWidgets.QApplication([])
    bridge = EzGuiBridge(app)
    window = MyWidget(bridge)
    window.show()

    with bridge:
        app.exec()
"""

from .bridge import EzGuiBridge
from .chain import ProcessorChain
from .gate import GateMessage
from .gate import MessageGate
from .gate import MessageGateSettings
from .publisher import EzPublisher
from .settings_form import SettingsForm
from .subscriber import EzSubscriber

__all__ = [
    "EzGuiBridge",
    "EzPublisher",
    "EzSubscriber",
    "ProcessorChain",
    "SettingsForm",
    "GateMessage",
    "MessageGate",
    "MessageGateSettings",
]
