"""
ezmsg.qt - Qt integration for ezmsg with direct topic-based pub/sub.

This package provides Qt widgets that can subscribe to and publish messages
on ezmsg topics using a familiar Qt signal/slot pattern.

Example:
    from ezmsg.qt import EzSubscriber, EzPublisher, EzGuiBridge

    class MyWidget(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            # Simple subscription
            self.data_sub = EzSubscriber(MyTopic.OUTPUT, parent=self)
            self.data_sub.connect(self.on_data)

            # Subscription with processing chain
            self.processed_sub = EzSubscriber(MyTopic.RAW, parent=self)
            self.processed_sub.process(MyProcessor, in_process=True) \
                              .connect(self.on_processed)

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
