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
            self.data_sub = EzSubscriber(MyTopic.OUTPUT, parent=self)
            self.data_sub.connect(self.on_data)

            # Processing chain with parallel (sidecar) and local (bridge) stages
            self.chain = (
                ProcessorChain(MyTopic.RAW, parent=self)
                .parallel(LowPassFilter, ScaleProcessor)  # run in sidecar
                .local(ThresholdDetector)  # run in bridge thread
                .connect(self.on_processed)
            )

        def on_data(self, msg):
            pass

        def on_processed(self, msg):
            pass

    app = QtWidgets.QApplication([])
    window = MyWidget()
    window.show()

    with EzGuiBridge(app):
        app.exec()
"""

from .bridge import EzGuiBridge
from .chain import ProcessorChain
from .gate import GateMessage
from .gate import MessageGate
from .gate import MessageGateSettings
from .publisher import EzPublisher
from .subscriber import EzSubscriber

__all__ = [
    "EzGuiBridge",
    "EzPublisher",
    "EzSubscriber",
    "ProcessorChain",
    "GateMessage",
    "MessageGate",
    "MessageGateSettings",
]
