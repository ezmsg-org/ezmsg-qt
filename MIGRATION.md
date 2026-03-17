# Migration Guide

## Explicit Bridge Ownership

`ezmsg-qt` no longer uses module-global pending registration.

Before:

```python
app = QtWidgets.QApplication([])
widget = MyWidget()

with EzGuiBridge(app):
    app.exec()
```

After:

```python
app = QtWidgets.QApplication([])
bridge = EzGuiBridge(app)
widget = MyWidget(bridge)

with bridge:
    app.exec()
```

Attach endpoints explicitly:

```python
self.sub = EzSubscriber(MyTopic.OUTPUT, parent=self, bridge=bridge)
self.pub = EzPublisher(MyTopic.INPUT, parent=self, bridge=bridge)
```

## Runtime Topic Switching

`EzSubscriber` can now switch topics directly.

```python
self.sub = EzSubscriber(MyTopic.A, parent=self, bridge=bridge)
self.sub.connect(self.on_data)

# Later, once the bridge is running:
self.sub.set_topic(MyTopic.B)

# Pause delivery entirely:
self.sub.clear_topic()
```

Notes:

- `set_topic(...)` and `clear_topic()` require a running bridge
- both calls block until the bridge applies the change
- `topic` reflects the currently active topic

## Processor Pipelines

`ProcessorChain` is now attached explicitly and always runs off the UI thread.

Before:

```python
chain = sub.process(Filter, in_process=True)
chain.process(DisplayTransform, in_process=False)
chain.connect(self.on_data)
```

After:

```python
chain = (
    ProcessorChain(MyTopic.RAW, parent=self)
    .parallel(Filter)
    .local(DisplayTransform)
    .connect(self.on_data)
    .attach(bridge)
)
```

Semantics:

- `.parallel(...)` runs a stage group in its own sidecar process
- `.local(...)` runs a stage group in the shared sidecar process
- neither mode runs on the Qt UI thread

## Topic Normalization

Qt bridge topics now follow ezmsg core enum semantics.

- `Enum` topics map to `Enum.name`
- string topics are used as-is

If your graph previously relied on `str(MyEnum.VALUE)`, update external graph
connections to use `MyEnum.VALUE.name` or the plain string topic name.

## Publisher Queueing

`EzPublisher` now supports configurable queue policies:

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
    bridge=bridge,
    queue_policy="coalesce_latest",
    max_pending=1,
)
```
