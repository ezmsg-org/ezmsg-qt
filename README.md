# ezmsg-qt

Qt-native pub/sub bridge that connects GUIs to running ezmsg graphs.

## Overview

`ezmsg-qt` provides a Qt-native interface for connecting widgets to ezmsg topics.
Its purpose is to make GUI integration feel like standard Qt signal/slot code
while still leveraging ezmsg's graph, backpressure, and process isolation.
Instead of routing all messages through a single multiplexed channel, widgets
subscribe to and publish on specific topics directly.

When you need extra compute for UI-facing data, EzGuiBridge can also manage a
local `GraphRunner`, letting you run processing units (including separate
processes) alongside the GUI while sharing the same GraphServer.

## Installation

```bash
# With PyQt6
pip install ezmsg-qt[pyqt6]

# With PySide6
pip install ezmsg-qt[pyside6]
```

## Quick Start

```python
from enum import Enum, auto
from qtpy import QtWidgets
from ezmsg.qt import EzSubscriber, EzPublisher, EzGuiBridge

# Define topics (typically in your processing module)
class VelocityTopic(Enum):
    INPUT_SETTINGS = auto()
    OUTPUT_DATA = auto()

class VelocityWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        # Create UI
        self.slider = QtWidgets.QSlider()
        self.label = QtWidgets.QLabel("Waiting for data...")

        # Create ezmsg connections
        self.data_sub = EzSubscriber(VelocityTopic.OUTPUT_DATA, parent=self)
        self.settings_pub = EzPublisher(VelocityTopic.INPUT_SETTINGS, parent=self)

        # Connect like normal Qt signals
        self.data_sub.connect(self.on_data)
        self.slider.valueChanged.connect(self.on_slider)

    def on_data(self, msg):
        self.label.setText(f"Received: {msg}")

    def on_slider(self, value):
        self.settings_pub.emit({"gain": value})

def main():
    app = QtWidgets.QApplication([])
    window = VelocityWidget()
    window.show()

    with EzGuiBridge(app):
        app.exec()

if __name__ == "__main__":
    main()
```

## How It Works

- `EzSubscriber` and `EzPublisher` are QObjects that register themselves with the `EzGuiBridge`
- `EzGuiBridge` manages a background asyncio thread that handles ezmsg communication
- Messages are passed between threads using Qt's thread-safe signal mechanism
- All async complexity is hidden - user code is 100% synchronous

## Local Processing (GraphRunner)

If the GUI needs additional computation, you can run a small ezmsg graph
alongside the app. Use a `GraphRunner` to launch the processing graph, then
point the bridge at the runner's graph address.

```python
from ezmsg.core.backend import GraphRunner
from ezmsg.qt import EzGuiBridge

runner = GraphRunner(
    components={"PLOTTER": PlotterCollection()},
    connections=[
        (DataTopic.RAW, PlotterCollection.INPUT),
        (PlotterCollection.OUTPUT, DataTopic.PROCESSED),
    ],
    process_components=[PlotterCollection],
)

runner.start()
try:
    with EzGuiBridge(app, graph_address=runner.graph_address):
        app.exec()
finally:
    if runner.running:
        runner.stop()
```

## API Reference

### EzSubscriber

```python
EzSubscriber(topic: Enum, parent: QObject = None)
```

- `topic`: The topic enum to subscribe to
- `connect(slot)`: Connect a handler to receive messages
- `received`: Qt signal emitted when a message arrives

### EzPublisher

```python
EzPublisher(topic: Enum, parent: QObject = None)
```

- `topic`: The topic enum to publish to
- `emit(message)`: Send a message to the topic

### EzGuiBridge

```python
with EzGuiBridge(app, graph_address=None):
    app.exec()
```

- `app`: The QApplication instance
- `graph_address`: Optional GraphServer address (uses default if not specified)

## Design Document

See [docs/plans/2026-01-13-qt-integration-design.md](docs/plans/2026-01-13-qt-integration-design.md) for the full design specification.
