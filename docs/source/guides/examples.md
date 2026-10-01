# Examples

The [`examples/`](https://github.com/ezmsg-org/ezmsg-qt/tree/main/examples) directory
contains runnable demos. From a clone of the repository, install the project with a
Qt binding and run a demo:

```bash
uv sync --extra pyside6
uv run python examples/simple_demo.py
```

`spatial_carrier_fft_demo.py` additionally requires the `examples` extra
(`uv sync --extra pyside6 --extra examples`).

| Example | Description |
|---|---|
| [`simple_demo.py`](https://github.com/ezmsg-org/ezmsg-qt/blob/main/examples/simple_demo.py) | A Qt widget publishes numbers to an ezmsg unit that doubles them and receives the results via `EzSession`. |
| [`ezmsg_toy_session.py`](https://github.com/ezmsg-org/ezmsg-qt/blob/main/examples/ezmsg_toy_session.py) | Connects a Qt widget to the ezmsg toy graph running in a `GraphRunner` (publish and subscribe). |
| [`dynamic_topic_switching_demo.py`](https://github.com/ezmsg-org/ezmsg-qt/blob/main/examples/dynamic_topic_switching_demo.py) | Runtime `EzSubscriber` topic switching. |
| [`processor_chain_demo.py`](https://github.com/ezmsg-org/ezmsg-qt/blob/main/examples/processor_chain_demo.py) | Compiled processor pipelines with shared and isolated sidecar execution stages. |
| [`processor_chain_showcase.py`](https://github.com/ezmsg-org/ezmsg-qt/blob/main/examples/processor_chain_showcase.py) | Tour of the `ProcessorGraph` API: `.parallel()` / `.local()` stages, auto-gating when a widget is hidden, and mixed graphs. |
| [`processor_graph_composition_demo.py`](https://github.com/ezmsg-org/ezmsg-qt/blob/main/examples/processor_graph_composition_demo.py) | `ProcessorGraph` composition with reusable recipes and branches. |
| [`processor_graph_toy_demo.py`](https://github.com/ezmsg-org/ezmsg-qt/blob/main/examples/processor_graph_toy_demo.py) | Qt-flavored reimplementation of the ezmsg toy graph using `ProcessorGraph`. |
| [`spatial_carrier_fft_demo.py`](https://github.com/ezmsg-org/ezmsg-qt/blob/main/examples/spatial_carrier_fft_demo.py) | Spatial carrier demo driven by `ezmsg.baseproc.clock.Clock`, plotted with fastplotlib. |
| [`dual_runner_shutdown_test.py`](https://github.com/ezmsg-org/ezmsg-qt/blob/main/examples/dual_runner_shutdown_test.py) | Minimal reproduction of a sidecar `GraphRunner` shutdown deadlock and its fix (diagnostic script). |
