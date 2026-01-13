"""
ezmsg.qt - Qt integration for ezmsg with direct topic-based pub/sub.

This package provides Qt widgets that can subscribe to and publish messages
on ezmsg topics using a familiar Qt signal/slot pattern.

Example:
    from ezmsg.qt import EzSubscriber, EzPublisher, EzGuiBridge

    class MyWidget(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.data_sub = EzSubscriber(MyTopic.OUTPUT, parent=self)
            self.data_sub.connect(self.on_data)

        def on_data(self, msg):
            # Handle message
            pass

    app = QtWidgets.QApplication([])
    window = MyWidget()
    window.show()

    with EzGuiBridge(app):
        app.exec()
"""

from .bridge import EzGuiBridge
from .publisher import EzPublisher
from .subscriber import EzSubscriber

__all__ = ["EzSubscriber", "EzPublisher", "EzGuiBridge"]
