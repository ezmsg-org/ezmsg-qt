# ezmsg-qt

Qt-native pub/sub bridge that connects GUIs to running ezmsg graphs.

## Overview

`ezmsg-qt` provides a Qt-native interface for connecting widgets to ezmsg topics.
Its purpose is to make GUI integration feel like standard Qt signal/slot code
while still leveraging ezmsg's graph, backpressure, and sidecar execution.
Instead of routing all messages through a single multiplexed channel, widgets
subscribe to and publish on specific topics directly.

When you need extra compute for UI-facing data, `EzGuiBridge` can also manage a
sidecar `GraphRunner`, letting you run processing units off the UI thread while
sharing the same GraphServer.

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
    def __init__(self, bridge: EzGuiBridge):
        super().__init__()

        # Create UI
        self.slider = QtWidgets.QSlider()
        self.label = QtWidgets.QLabel("Waiting for data...")

        # Create ezmsg connections
        self.data_sub = EzSubscriber(
            VelocityTopic.OUTPUT_DATA,
            parent=self,
            bridge=bridge,
        )
        self.settings_pub = EzPublisher(
            VelocityTopic.INPUT_SETTINGS,
            parent=self,
            bridge=bridge,
        )

        # Connect like normal Qt signals
        self.data_sub.connect(self.on_data)
        self.slider.valueChanged.connect(self.on_slider)

    def on_data(self, msg):
        self.label.setText(f"Received: {msg}")

    def on_slider(self, value):
        self.settings_pub.emit({"gain": value})


def main():
    app = QtWidgets.QApplication([])
    bridge = EzGuiBridge(app)
    window = VelocityWidget(bridge)
    window.show()

    with bridge:
        app.exec()


if __name__ == "__main__":
    main()
```

## How It Works

- `EzSubscriber` and `EzPublisher` are QObjects attached explicitly to an `EzGuiBridge`
- `EzGuiBridge` manages a background asyncio thread that handles ezmsg communication
- Messages are passed between threads using Qt's thread-safe signal mechanism
- All async complexity is hidden - user code is 100% synchronous

## Runtime Topic Switching

`EzSubscriber` can retarget to a new topic at runtime without reconnecting Qt slots.

```python
class TopicSwitcher(QtWidgets.QWidget):
    def __init__(self, bridge: EzGuiBridge):
        super().__init__()
        self.sub = EzSubscriber(MyTopic.A, parent=self, bridge=bridge)
        self.sub.connect(self.on_data)

    def switch_to_b(self) -> None:
        self.sub.set_topic(MyTopic.B)

    def pause_updates(self) -> None:
        self.sub.clear_topic()
```

- `set_topic(...)` blocks until the running bridge applies the switch
- `clear_topic()` disconnects the subscriber from all topics
- `topic` reflects the currently active topic
- topic switching requires the subscriber to be attached to a running bridge

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
bridge = EzGuiBridge(app, graph_address=runner.graph_address)
try:
    with bridge:
        app.exec()
finally:
    if runner.running:
        runner.stop()
```

## Processor Pipelines

`ProcessorChain` compiles processing stages into a sidecar ezmsg runtime.

- `.parallel(...)` runs a stage group in its own sidecar process
- `.local(...)` runs a stage group in the shared sidecar process
- neither mode runs on the Qt UI thread

```python
from ezmsg.qt import EzGuiBridge, ProcessorChain

bridge = EzGuiBridge(app)

chain = (
    ProcessorChain(MyTopic.RAW, parent=widget)
    .parallel(LowPassFilter)
    .local(ThresholdDetector)
    .connect(widget.on_processed)
    .attach(bridge)
)
```

## API Reference

### EzSubscriber

```python
EzSubscriber(topic: Enum | str | None = None, parent: QObject = None)
```

- `topic`: The topic enum to subscribe to
- `bridge`: The bridge that owns this subscriber
- `connect(slot)`: Connect a handler to receive messages
- `set_topic(topic)`: Switch to a new topic on a running bridge
- `clear_topic()`: Unsubscribe from the current topic on a running bridge
- `received`: Qt signal emitted when a message arrives

### EzPublisher

```python
EzPublisher(topic: Enum, parent: QObject = None)
```

- `topic`: The topic enum to publish to
- `bridge`: The bridge that owns this publisher
- `emit(message)`: Send a message to the topic

### EzGuiBridge

```python
bridge = EzGuiBridge(app, graph_address=None)
with bridge:
    app.exec()
```

- `app`: The QApplication instance
- `graph_address`: Optional GraphServer address (uses default if not specified)
- `attach(obj)`: Attach an `EzSubscriber`, `EzPublisher`, or `ProcessorChain`
