# ezmsg-qt

Qt-native pub/sub runtime for connecting GUIs to ezmsg graphs.

## Overview

`ezmsg-qt` lets Qt widgets publish to and subscribe from ezmsg topics using a
familiar signal/slot style while keeping ezmsg runtime ownership explicit.

- `EzSession` owns the ezmsg runtime thread, `GraphContext`, and sidecar pipelines
- `EzSubscriber` and `EzPublisher` attach to a session
- `ProcessorChain` compiles processing stages into a sidecar runtime owned by the session

## Quick Start

```python
from enum import Enum, auto
from qtpy import QtWidgets

from ezmsg.qt import EzPublisher, EzSession, EzSubscriber


class VelocityTopic(Enum):
    INPUT_SETTINGS = auto()
    OUTPUT_DATA = auto()


class VelocityWidget(QtWidgets.QWidget):
    def __init__(self, session: EzSession):
        super().__init__()

        self.slider = QtWidgets.QSlider()
        self.label = QtWidgets.QLabel("Waiting for data...")

        self.data_sub = EzSubscriber(
            VelocityTopic.OUTPUT_DATA,
            parent=self,
            session=session,
        )
        self.settings_pub = EzPublisher(
            VelocityTopic.INPUT_SETTINGS,
            parent=self,
            session=session,
        )

        self.data_sub.connect(self.on_data)
        self.slider.valueChanged.connect(self.on_slider)

    def on_data(self, msg):
        self.label.setText(f"Received: {msg}")

    def on_slider(self, value):
        self.settings_pub.emit({"gain": value})


def main() -> None:
    app = QtWidgets.QApplication([])
    session = EzSession()
    window = VelocityWidget(session)
    window.show()

    with session:
        app.exec()
```

## Runtime Topic Switching

`EzSubscriber` can retarget to a new topic at runtime without reconnecting Qt slots.

```python
class TopicSwitcher(QtWidgets.QWidget):
    def __init__(self, session: EzSession):
        super().__init__()
        self.sub = EzSubscriber(MyTopic.A, parent=self, session=session)
        self.sub.connect(self.on_data)

    def switch_to_b(self) -> None:
        self.sub.set_topic(MyTopic.B)

    def pause_updates(self) -> None:
        self.sub.clear_topic()
```

- `set_topic(...)` blocks until the running session applies the switch
- `clear_topic()` disconnects the subscriber from all topics
- `topic` reflects the currently active topic
- topic switching requires the subscriber to be attached to a running session
- signals available for UI state: `switch_started`, `topic_changed`, `topic_cleared`, `switch_failed`

## Local Processing

Use `ProcessorChain` when widget-facing data needs ezmsg processing off the UI thread.

```python
from ezmsg.qt import EzSession, ProcessorChain

session = EzSession()

chain = (
    ProcessorChain(MyTopic.RAW, parent=widget)
    .parallel(LowPassFilter)
    .local(ThresholdDetector)
    .connect(widget.on_processed)
    .attach(session)
)
```

- `.parallel(...)` runs a stage group in its own sidecar process
- `.local(...)` runs a stage group in the shared sidecar process
- neither mode runs on the Qt UI thread

## External Graphs

Point a session at an existing `GraphRunner` or `GraphServer` by providing
`graph_address`.

```python
runner.start()
session = EzSession(graph_address=runner.graph_address)
try:
    with session:
        app.exec()
finally:
    if runner.running:
        runner.stop()
```

## API Reference

### EzSession

```python
session = EzSession(graph_address=None)
with session:
    app.exec()
```

- `graph_address`: Optional GraphServer address
- `attach(obj)`: Attach an `EzSubscriber`, `EzPublisher`, or `ProcessorChain`
- `detach(obj)`: Detach an `EzSubscriber` or `EzPublisher`
- `running`: Whether the session runtime is active

### EzSubscriber

```python
EzSubscriber(
    topic: Enum | str | None = None,
    parent: QObject = None,
    *,
    session: EzSession | None = None,
    leaky: bool = False,
    max_queue: int | None = None,
    throttle_hz: float | None = None,
)
```

- `session`: The session that owns this subscriber
- `connect(slot)`: Connect a handler to receive messages
- `set_topic(topic)`: Switch to a new topic on a running session
- `clear_topic()`: Unsubscribe from the current topic on a running session
- `received`: Qt signal emitted when a message arrives
- `switch_started`, `topic_changed`, `topic_cleared`, `switch_failed`: lifecycle signals for runtime switching

### EzPublisher

```python
EzPublisher(
    topic: Enum | str | None = None,
    parent: QObject = None,
    *,
    session: EzSession | None = None,
    queue_policy: QueuePolicy = "unbounded",
    max_pending: int | None = None,
)
```

- `session`: The session that owns this publisher
- `emit(message)`: Send a message to the topic
- `set_topic(topic)`: Switch to a new topic on a running session
- `clear_topic()`: Unpublish from the current topic on a running session
- `switch_started`, `topic_changed`, `topic_cleared`, `switch_failed`: lifecycle signals for runtime switching
