#!/usr/bin/env python3
"""
Spatial carrier demo driven by ``ezmsg.baseproc.clock.Clock``.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from typing import cast

import ezmsg.core as ez
import fastplotlib as fpl
import numpy as np
from ezmsg.baseproc.clock import Clock
from ezmsg.baseproc.clock import ClockSettings
from ezmsg.core.backend import GraphRunner
from ezmsg.util.messages.axisarray import AxisArray
from qtpy import QtCore
from qtpy import QtWidgets

from ezmsg.qt import BoundProcessor
from ezmsg.qt import EzSession
from ezmsg.qt import ProcessorGraph
from ezmsg.qt import ProcessorSettingsPanel

ClockTickType = object if AxisArray is None else AxisArray.LinearAxis
REFERENCE_AZIMUTH_DEG = 45.0


class WindowKind(Enum):
    BOXCAR = "boxcar"
    HANN = "hann"
    HAMMING = "hamming"
    BLACKMAN = "blackman"


class CarrierTopic(Enum):
    CLOCK_TICK = "CLOCK_TICK"
    RAW_IMAGE = "RAW_IMAGE"
    FFT_IMAGE = "FFT_IMAGE"


@dataclass(frozen=True)
class CarrierFrame:
    image: np.ndarray
    timestamp: float
    reference_tilt: float
    reference_distance: float
    carrier_fx: float
    carrier_fy: float
    curvature: float


@dataclass(frozen=True)
class SpectrumFrame:
    image: np.ndarray
    timestamp: float
    peak_row_offset: int
    peak_col_offset: int
    window: WindowKind


class CarrierGeneratorSettings(ez.Settings):
    image_size: int = 256
    reference_tilt: float = 8.0
    reference_distance: float = 1.5
    curvature_gain: float = 8.0
    temporal_frequency: float = 0.5


class SpatialFFTSettings(ez.Settings):
    window: WindowKind = WindowKind.BOXCAR


def generate_spatial_carrier_images(
    t: np.ndarray | list[float],
    *,
    image_size: int,
    reference_tilt: float,
    reference_distance: float = 1.5,
    curvature_gain: float = 8.0,
    temporal_frequency: float = 0.5,
) -> np.ndarray:
    """Generate hologram fringes from a paraxial tilted reference wave."""
    t_arr = np.asarray(t, dtype=np.float32)
    coords = (
        np.arange(image_size, dtype=np.float32) - ((image_size - 1) / 2.0)
    ) / image_size
    grid_x, grid_y = np.meshgrid(coords, coords, indexing="xy")
    carrier_fx, carrier_fy, curvature = reference_phase_parameters(
        reference_tilt=reference_tilt,
        reference_distance=reference_distance,
        curvature_gain=curvature_gain,
    )
    spatial_phase = (
        2.0
        * np.pi
        * (
            carrier_fx * grid_x
            + carrier_fy * grid_y
            + 0.5 * curvature * (grid_x**2 + grid_y**2)
        )
    )
    temporal_phase = 2.0 * np.pi * temporal_frequency * t_arr[:, None, None]
    return 0.5 + 0.5 * np.cos(spatial_phase[None, ...] + temporal_phase)


def reference_phase_parameters(
    *,
    reference_tilt: float,
    reference_distance: float,
    curvature_gain: float,
) -> tuple[float, float, float]:
    """Map DH controls to the paraxial reference phase parameters.

    The linear carrier terms move the +1/-1 orders in the Fourier plane.
    The quadratic term controls how curved or planar the reference appears.
    """
    angle_rad = np.deg2rad(REFERENCE_AZIMUTH_DEG)
    carrier_fx = float(reference_tilt * np.cos(angle_rad))
    carrier_fy = float(reference_tilt * np.sin(angle_rad))
    safe_distance = max(float(reference_distance), 1.0e-6)
    curvature = float(curvature_gain / safe_distance)
    return carrier_fx, carrier_fy, curvature


def generate_spatial_carrier_frame(
    timestamp: float, settings: CarrierGeneratorSettings
) -> np.ndarray:
    images = generate_spatial_carrier_images(
        [timestamp],
        image_size=settings.image_size,
        reference_tilt=settings.reference_tilt,
        reference_distance=settings.reference_distance,
        curvature_gain=settings.curvature_gain,
        temporal_frequency=settings.temporal_frequency,
    )
    return images[0].astype(np.float32, copy=False)


def spatial_window_1d(window: WindowKind, size: int) -> np.ndarray:
    if window is WindowKind.BOXCAR:
        return np.ones(size, dtype=np.float32)
    if window is WindowKind.HANN:
        return np.hanning(size).astype(np.float32)
    if window is WindowKind.HAMMING:
        return np.hamming(size).astype(np.float32)
    if window is WindowKind.BLACKMAN:
        return np.blackman(size).astype(np.float32)
    raise ValueError(f"Unsupported window kind: {window}")


def spatial_window_2d(window: WindowKind, shape: tuple[int, int]) -> np.ndarray:
    row_window = spatial_window_1d(window, shape[0])
    col_window = spatial_window_1d(window, shape[1])
    return np.outer(row_window, col_window).astype(np.float32, copy=False)


def apply_spatial_window(image: np.ndarray, window: WindowKind) -> np.ndarray:
    if window is WindowKind.BOXCAR:
        return image.astype(np.float32, copy=False)
    weights = spatial_window_2d(window, image.shape)
    return (image * weights).astype(np.float32, copy=False)


def spatial_fft_magnitude(
    image: np.ndarray, *, window: WindowKind = WindowKind.BOXCAR
) -> np.ndarray:
    windowed = apply_spatial_window(image, window)
    centered = windowed - float(np.mean(windowed))
    return np.abs(np.fft.fftshift(np.fft.fft2(centered)))


def spatial_fft_magnitude_image(
    image: np.ndarray, *, window: WindowKind = WindowKind.BOXCAR
) -> np.ndarray:
    """Compute a normalized log-magnitude image of the 2D spatial FFT."""
    magnitude = spatial_fft_magnitude(image, window=window)
    log_magnitude = np.log1p(magnitude)
    peak = float(np.max(log_magnitude))
    if peak <= 0.0:
        return np.zeros_like(image, dtype=np.float32)
    return (log_magnitude / peak).astype(np.float32, copy=False)


def dominant_spatial_peak_offset(
    image: np.ndarray, *, window: WindowKind = WindowKind.BOXCAR
) -> tuple[int, int]:
    """Return the dominant positive-quadrant FFT peak offset from center."""
    magnitude = spatial_fft_magnitude(image, window=window)
    if float(np.max(magnitude)) <= 0.0:
        return 0, 0
    center_row = magnitude.shape[0] // 2
    center_col = magnitude.shape[1] // 2
    row_lo = max(center_row - 1, 0)
    row_hi = min(center_row + 2, magnitude.shape[0])
    col_lo = max(center_col - 1, 0)
    col_hi = min(center_col + 2, magnitude.shape[1])
    magnitude[row_lo:row_hi, col_lo:col_hi] = 0.0

    rows, cols = np.indices(magnitude.shape)
    positive_quadrant = (rows >= center_row) & (cols >= center_col)
    masked = np.where(positive_quadrant, magnitude, -np.inf)
    peak_row, peak_col = np.unravel_index(np.argmax(masked), masked.shape)
    return peak_row - center_row, peak_col - center_col


class SpatialCarrierGenerator(ez.Unit):
    SETTINGS = CarrierGeneratorSettings

    INPUT_CLOCK = ez.InputStream(ClockTickType)
    INPUT_SETTINGS = ez.InputStream(CarrierGeneratorSettings)
    OUTPUT_IMAGE = ez.OutputStream(CarrierFrame)

    @ez.subscriber(INPUT_SETTINGS)
    async def on_settings(self, msg: CarrierGeneratorSettings) -> None:
        self.apply_settings(msg)

    @ez.subscriber(INPUT_CLOCK)
    @ez.publisher(OUTPUT_IMAGE)
    async def on_clock(self, tick: Any) -> AsyncGenerator:
        timestamp = float(getattr(tick, "offset", 0.0))
        image = generate_spatial_carrier_frame(
            timestamp,
            cast(CarrierGeneratorSettings, self.SETTINGS),
        )
        carrier_fx, carrier_fy, curvature = reference_phase_parameters(
            reference_tilt=self.SETTINGS.reference_tilt,
            reference_distance=self.SETTINGS.reference_distance,
            curvature_gain=self.SETTINGS.curvature_gain,
        )
        yield (
            self.OUTPUT_IMAGE,
            CarrierFrame(
                image=image,
                timestamp=timestamp,
                reference_tilt=self.SETTINGS.reference_tilt,
                reference_distance=self.SETTINGS.reference_distance,
                carrier_fx=carrier_fx,
                carrier_fy=carrier_fy,
                curvature=curvature,
            ),
        )


class SpatialFFTProjector(ez.Unit):
    SETTINGS = SpatialFFTSettings

    INPUT = ez.InputStream(CarrierFrame)
    INPUT_SETTINGS = ez.InputStream(SpatialFFTSettings)
    OUTPUT = ez.OutputStream(SpectrumFrame)

    @ez.subscriber(INPUT_SETTINGS)
    async def on_settings(self, msg: SpatialFFTSettings) -> None:
        self.apply_settings(msg)

    @ez.subscriber(INPUT)
    @ez.publisher(OUTPUT)
    async def on_image(self, msg: CarrierFrame) -> AsyncGenerator:
        peak_row_offset, peak_col_offset = dominant_spatial_peak_offset(
            msg.image, window=self.SETTINGS.window
        )
        yield (
            self.OUTPUT,
            SpectrumFrame(
                image=spatial_fft_magnitude_image(
                    msg.image, window=self.SETTINGS.window
                ),
                timestamp=msg.timestamp,
                peak_row_offset=peak_row_offset,
                peak_col_offset=peak_col_offset,
                window=self.SETTINGS.window,
            ),
        )


def _require_clock_dependencies() -> tuple[type[Any], type[Any]]:
    if Clock is None or ClockSettings is None:
        raise RuntimeError(
            "This example requires ezmsg-baseproc and numpy. Run:\n"
            "  uv run --with numpy --with ezmsg-baseproc --with fastplotlib "
            "python examples/spatial_carrier_fft_demo.py"
        )
    return Clock, ClockSettings


def _require_fastplotlib() -> Any:
    if fpl is None:
        raise RuntimeError(
            "This example requires fastplotlib. Run:\n"
            "  uv run --with numpy --with ezmsg-baseproc --with fastplotlib "
            "python examples/spatial_carrier_fft_demo.py"
        )
    return fpl


class SpatialCarrierWidget(QtWidgets.QWidget):
    def __init__(
        self,
        session: EzSession,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self._session = session
        self._fpl = _require_fastplotlib()
        self.setWindowTitle("Spatial Carrier FFT Demo")
        self._generator_settings = CarrierGeneratorSettings()
        self._fft_settings = SpatialFFTSettings()
        self._plots_scaled = False

        self._root_layout = QtWidgets.QVBoxLayout()
        self.setLayout(self._root_layout)
        self._init_pipelines()
        self._init_controls()
        self._init_graphics()
        self._init_status_row()
        self._update_control_label()

    def _init_pipelines(self) -> None:
        self._graph = (
            ProcessorGraph(CarrierTopic.CLOCK_TICK, parent=self, auto_gate=True)
            .local(
                BoundProcessor(
                    SpatialCarrierGenerator,
                    name="generator",
                    input_name="INPUT_CLOCK",
                    output_name="OUTPUT_IMAGE",
                )
            )
            .connect(self._on_raw_frame)
            .branch(
                lambda path: path.local(
                    BoundProcessor(SpatialFFTProjector, name="fft")
                ).connect(self._on_spectrum_frame)
            )
            .attach(self._session)
        )

    def _init_controls(self) -> None:
        controls = QtWidgets.QGroupBox("Processor Settings")
        controls_layout = QtWidgets.QVBoxLayout(controls)
        controls_layout.addWidget(
            QtWidgets.QLabel(
                "Adjust generator and FFT settings, then apply each section "
                "to update the running processor graph."
            )
        )

        self._settings_panel = ProcessorSettingsPanel.from_graph(
            self._graph,
            parent=controls,
        )
        controls_layout.addWidget(self._settings_panel)

        self._control_label = QtWidgets.QLabel()
        controls_layout.addWidget(self._control_label)
        self._root_layout.addWidget(controls)

    def _init_graphics(self) -> None:
        self._figure = self._fpl.Figure(
            shape=(1, 2),
            canvas="qt",
            size=(1000, 420),
            names=[["Raw Carrier", "Spatial FFT Magnitude"]],
        )
        zero_image = np.zeros(
            (
                self._generator_settings.image_size,
                self._generator_settings.image_size,
            ),
            dtype=np.float32,
        )
        self._raw_plot = self._figure[0, 0]
        self._fft_plot = self._figure[0, 1]
        self._raw_graphic = self._raw_plot.add_image(
            zero_image,
            cmap="gray",
            interpolation="nearest",
            vmin=0.0,
            vmax=1.0,
        )
        self._fft_graphic = self._fft_plot.add_image(
            zero_image,
            cmap="magma",
            interpolation="nearest",
            vmin=0.0,
            vmax=1.0,
        )
        self._raw_plot.axes.grids.xy.visible = False
        self._fft_plot.axes.grids.xy.visible = False
        self._canvas_widget = self._figure.show(maintain_aspect=True)
        self._root_layout.addWidget(self._canvas_widget, stretch=1)

    def _update_image_graphic(
        self,
        plot,
        graphic_attr: str,
        image: np.ndarray,
        **image_kwargs: Any,
    ) -> None:
        graphic = getattr(self, graphic_attr)
        contiguous = np.ascontiguousarray(image)

        if graphic.data.value.shape != contiguous.shape:
            plot.remove_graphic(graphic)
            graphic = plot.add_image(contiguous, **image_kwargs)
            setattr(self, graphic_attr, graphic)
            self._plots_scaled = False
            return

        graphic.data[:] = contiguous

    def _init_status_row(self) -> None:
        status_layout = QtWidgets.QHBoxLayout()
        self._raw_caption = QtWidgets.QLabel("Waiting for raw frames...")
        self._fft_caption = QtWidgets.QLabel("Waiting for FFT frames...")
        status_layout.addWidget(self._raw_caption, stretch=1)
        status_layout.addWidget(self._fft_caption, stretch=1)
        self._root_layout.addLayout(status_layout)

    def _update_control_label(self) -> None:
        tilt = self._generator_settings.reference_tilt
        distance = self._generator_settings.reference_distance
        carrier_fx, carrier_fy, curvature = reference_phase_parameters(
            reference_tilt=tilt,
            reference_distance=distance,
            curvature_gain=self._generator_settings.curvature_gain,
        )
        window = self._fft_settings.window.value
        if abs(tilt) < 1.0e-9:
            self._control_label.setText(
                f"On-axis reference carrier. +1 and -1 overlap around DC. "
                f"FFT window: {window}."
            )
            return
        self._control_label.setText(
            f"Reference tilt {tilt:.1f} cyc/img, distance {distance:.2f}, "
            f"carrier = ({carrier_fx:+.2f}, {carrier_fy:+.2f}), "
            f"curvature = {curvature:.2f}. "
            f"FFT window: {window}."
        )

    def _on_raw_frame(self, msg: CarrierFrame) -> None:
        self._generator_settings = CarrierGeneratorSettings(
            image_size=int(msg.image.shape[0]),
            reference_tilt=msg.reference_tilt,
            reference_distance=msg.reference_distance,
            curvature_gain=msg.curvature * msg.reference_distance,
            temporal_frequency=self._generator_settings.temporal_frequency,
        )
        self._update_control_label()
        self._update_image_graphic(
            self._raw_plot,
            "_raw_graphic",
            msg.image,
            cmap="gray",
            interpolation="nearest",
            vmin=0.0,
            vmax=1.0,
        )
        self._raw_caption.setText(
            f"Raw: tilt {msg.reference_tilt:.1f}, "
            f"distance {msg.reference_distance:.2f}, "
            f"carrier ({msg.carrier_fx:+.2f}, {msg.carrier_fy:+.2f})"
        )
        if self._plots_scaled is False:
            self._raw_plot.auto_scale()
            self._fft_plot.auto_scale()
            self._plots_scaled = True
        self._figure.canvas.request_draw()

    def _on_spectrum_frame(self, msg: SpectrumFrame) -> None:
        self._fft_settings = SpatialFFTSettings(window=msg.window)
        self._update_control_label()
        self._update_image_graphic(
            self._fft_plot,
            "_fft_graphic",
            msg.image,
            cmap="magma",
            interpolation="nearest",
            vmin=0.0,
            vmax=1.0,
        )
        if abs(self._generator_settings.reference_tilt) < 1.0e-9:
            self._fft_caption.setText(
                f"FFT: {msg.window.value}, on-axis carrier. Orders overlap near DC."
            )
        else:
            self._fft_caption.setText(
                f"FFT: {msg.window.value}, +1/-1 order offsets = "
                f"({msg.peak_row_offset:+d}, {msg.peak_col_offset:+d}) / "
                f"({-msg.peak_row_offset:+d}, {-msg.peak_col_offset:+d})"
            )
        self._figure.canvas.request_draw()


def build_runner() -> GraphRunner:
    clock_cls, clock_settings_cls = _require_clock_dependencies()

    class CarrierClock(ez.Collection):
        CLOCK = clock_cls()

        OUTPUT_TICK = ez.OutputStream(ClockTickType)

        def configure(self) -> None:
            self.CLOCK.apply_settings(clock_settings_cls(dispatch_rate=12.0))

        def network(self) -> ez.NetworkDefinition:
            return ((self.CLOCK.OUTPUT_SIGNAL, self.OUTPUT_TICK),)

    pipeline = CarrierClock()
    return GraphRunner(
        components={"pipeline": pipeline},
        connections=[
            (pipeline.OUTPUT_TICK, CarrierTopic.CLOCK_TICK.name),
        ],
    )


def main() -> None:
    _require_fastplotlib()

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(Path(__file__).stem)

    auto_close_ms = os.getenv("EZMSG_QT_DEMO_AUTOCLOSE_MS")
    if auto_close_ms is not None:
        QtCore.QTimer.singleShot(int(auto_close_ms), app.quit)

    runner = build_runner()
    runner.start()
    session = EzSession(graph_address=runner.graph_address)
    widget = SpatialCarrierWidget(session)
    widget.resize(1200, 720)
    widget.show()
    try:
        with session:
            app.exec()
    finally:
        if runner.running:
            runner.stop()


if __name__ == "__main__":
    main()
