# Migration Guide

## Session Ownership

`ezmsg-qt` now uses `EzSession` as the only public runtime owner.

Before:

```python
app = QtWidgets.QApplication([])
bridge = EzGuiBridge(app)
widget = MyWidget(bridge)

with bridge:
    app.exec()
```

After:

```python
app = QtWidgets.QApplication([])
session = EzSession()
widget = MyWidget(session)

with session:
    app.exec()
```

The public bridge object is gone; `EzSession` is now the only public runtime owner.

Attach endpoints explicitly:

```python
self.sub = EzSubscriber(MyTopic.OUTPUT, parent=self, session=session)
self.pub = EzPublisher(MyTopic.INPUT, parent=self, session=session)
```

## Runtime Topic Switching

`EzSubscriber` can switch topics directly, and `EzPublisher` now supports the same API.

```python
self.sub = EzSubscriber(MyTopic.A, parent=self, session=session)
self.pub = EzPublisher(MyTopic.B, parent=self, session=session)

self.sub.set_topic(MyTopic.C)
self.pub.set_topic(MyTopic.D)

self.sub.clear_topic()
self.pub.clear_topic()
```

Notes:

- `set_topic(...)` and `clear_topic()` require a running session
- both calls block until the session applies the change
- `topic` reflects the currently active topic

## Processor Pipelines

`ProcessorChain` attaches to a session and always runs off the UI thread.

```python
chain = (
    ProcessorChain(MyTopic.RAW, parent=self)
    .parallel(Filter)
    .local(DisplayTransform)
    .connect(self.on_data)
    .attach(session)
)
```

- `.parallel(...)` runs a stage group in its own sidecar process
- `.local(...)` runs a stage group in the shared sidecar process

## Topic Normalization

Qt session topics follow ezmsg core enum semantics.

- `Enum` topics map to `Enum.name`
- string topics are used as-is

If your graph previously relied on `str(MyEnum.VALUE)`, update external graph
connections to use `MyEnum.VALUE.name` or the plain string topic name.

## Publisher Queueing

`EzPublisher` supports configurable queue policies:

- `unbounded`
- `block`
- `drop_oldest`
- `drop_latest`
- `coalesce_latest`

Example:

```python
self.pub = EzPublisher(
    MyTopic.INPUT,
    parent=self,
    session=session,
    queue_policy="coalesce_latest",
    max_pending=1,
)
```
