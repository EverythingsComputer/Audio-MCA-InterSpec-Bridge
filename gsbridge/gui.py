"""PySide6 GUI for gsbridge.

Layout: live spectrum plot (pyqtgraph), run controls, device/threshold
settings, stats readout, and an output panel telling you exactly which files
to open in InterSpec.
"""

from __future__ import annotations

import sys

import numpy as np
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

import pyqtgraph as pg

from .capture import AudioStreamSource, WavSource
from .dsp import ProcessorConfig
from .engine import Engine
from .writers import HAVE_SPECUTILS


class SettingsDialog(QDialog):
    def __init__(self, cfg: ProcessorConfig, device_text: str = "codec",
                 sample_rate: float = 48000.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Acquisition settings")
        self.cfg = cfg
        form = QFormLayout(self)

        self.device_edit = QLineEdit(device_text)
        form.addRow("Device match:", self.device_edit)

        self.rate_box = QDoubleSpinBox()
        self.rate_box.setRange(8000, 384000)
        self.rate_box.setValue(sample_rate)
        form.addRow("Sample rate (Hz):", self.rate_box)

        self.thr_box = QSpinBox()
        self.thr_box.setRange(1, 32000)
        self.thr_box.setValue(int(cfg.threshold_adc))
        form.addRow("Threshold (ADC):", self.thr_box)

        self.post_box = QSpinBox()
        self.post_box.setRange(5, 480)
        self.post_box.setValue(cfg.posttrigger_samples)
        form.addRow("Pulse length (samples):", self.post_box)

        self.chan_box = QSpinBox()
        self.chan_box.setRange(256, 16384)
        self.chan_box.setValue(cfg.n_channels)
        self.chan_box.setSingleStep(256)
        form.addRow("MCA channels:", self.chan_box)

        self.pol_combo = QComboBox()
        self.pol_combo.addItems(["positive", "negative"])
        self.pol_combo.setCurrentIndex(0 if cfg.polarity > 0 else 1)
        form.addRow("Pulse polarity:", self.pol_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def apply_to_cfg(self) -> ProcessorConfig:
        c = self.cfg
        c.threshold_adc = float(self.thr_box.value())
        c.posttrigger_samples = self.post_box.value()
        c.n_channels = self.chan_box.value()
        c.polarity = 1 if self.pol_combo.currentIndex() == 0 else -1
        return c


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GS-Bridge — audio-MCA → InterSpec")
        self.resize(980, 640)

        self.cfg = ProcessorConfig()
        self.device_text = "codec"
        self.sample_rate = 48000.0
        self.out_dir = None  # set below
        self.engine: Engine | None = None
        self._wav_path: str | None = None

        layout = QVBoxLayout(self)

        # ---- plot
        pg.setConfigOptions(antialias=False)
        self.plot = pg.PlotWidget()
        self.plot.setLogMode(x=False, y=True)
        self.plot.setLabel("left", "Counts")
        self.plot.setLabel("bottom", "Channel")
        self.plot.setMouseEnabled(x=True, y=True)
        self.curve = self.plot.plot(pen=pg.mkPen("#4ea1ff", width=1))
        layout.addWidget(self.plot, stretch=1)

        # ---- stats row
        self.stats_label = QLabel("stopped")
        f = self.stats_label.font(); f.setBold(True); self.stats_label.setFont(f)
        layout.addWidget(self.stats_label)

        # ---- controls
        ctrl = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_settings = QPushButton("Settings…")
        self.btn_wav = QPushButton("Load WAV…")
        self.btn_live = QPushButton("Back to live")
        self.btn_live.setEnabled(False)
        self.btn_open_out = QPushButton("Open output folder")
        self.chk_save_spc = QCheckBox(".spc")
        self.chk_save_n42 = QCheckBox(".n42")
        self.chk_save_spe = QCheckBox(".spe")
        self.chk_save_spe.setChecked(True)
        if not HAVE_SPECUTILS:
            self.chk_save_spc.setEnabled(False)
            self.chk_save_n42.setEnabled(False)
        for w in (self.btn_start, self.btn_stop, self.btn_settings, self.btn_wav,
                  self.btn_live, self.btn_open_out):
            ctrl.addWidget(w)
        ctrl.addStretch(1)
        ctrl.addWidget(QLabel("Save:"))
        ctrl.addWidget(self.chk_save_spe)
        ctrl.addWidget(self.chk_save_spc)
        ctrl.addWidget(self.chk_save_n42)
        layout.addLayout(ctrl)

        # ---- InterSpec hint
        self.hint = QLabel(
            "InterSpec: File → Open the .spe file in the output folder. To see newer "
            "data, open it again (each open re-reads from disk; \"Update Displays\" "
            "inside InterSpec only redraws the copy already loaded).")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("padding:6px; background:#22303c; border-radius:4px;")
        layout.addWidget(self.hint)

        # default output dir next to home
        import os
        self.out_dir = os.path.expanduser("~/Documents/GS-Bridge-output")

        self.btn_start.clicked.connect(self.on_start)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_settings.clicked.connect(self.on_settings)
        self.btn_wav.clicked.connect(self.on_wav)
        self.btn_live.clicked.connect(self.on_back_to_live)
        self.btn_open_out.clicked.connect(self.on_open_out)

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    # ---------------------------------------------------------------- slots
    def formats(self):
        fmts = []
        if self.chk_save_spe.isChecked(): fmts.append("spe")
        if self.chk_save_spc.isChecked(): fmts.append("spc")
        if self.chk_save_n42.isChecked(): fmts.append("n42")
        return fmts or ["spe"]

    def on_start(self):
        fmts = self.formats()
        dtxt = self.device_text
        wav_path = self._wav_path          # capture current mode for this run

        def factory():
            if wav_path:
                return WavSource(wav_path, blocksize=int(self.sample_rate // 10))
            return AudioStreamSource(device_match=dtxt or None, sample_rate=self.sample_rate)

        self.engine = Engine(factory, self.cfg, self.out_dir, save_formats=fmts)
        self.engine.sample_rate = self.sample_rate
        try:
            self.engine.start()
        except Exception as e:
            QMessageBox.critical(self, "Start failed", str(e))
            self.engine = None
            return
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_settings.setEnabled(False)

    def on_stop(self):
        if self.engine:
            self.engine.stop()
            self.engine = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_settings.setEnabled(True)

    def on_settings(self):
        dlg = SettingsDialog(self.cfg, device_text=self.device_text,
                             sample_rate=self.sample_rate, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.cfg = dlg.apply_to_cfg()
            self.device_text = dlg.device_edit.text().strip()
            self.sample_rate = dlg.rate_box.value()

    def on_wav(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open WAV (16-bit PCM)", "",
                                              "WAV files (*.wav);;All files (*)")
        if path:
            self._wav_path = path
            self.btn_live.setEnabled(True)
            self.setWindowTitle(f"GS-Bridge — replaying {path}")

    def on_back_to_live(self):
        self._wav_path = None
        self.btn_live.setEnabled(False)
        self.setWindowTitle("GS-Bridge — audio-MCA → InterSpec")

    def on_open_out(self):
        import os, subprocess, platform
        os.makedirs(self.out_dir, exist_ok=True)
        if platform.system() == "Linux":
            subprocess.Popen(["xdg-open", self.out_dir])

    # ---------------------------------------------------------------- refresh
    def refresh(self):
        if not self.engine:
            return
        spec, stats, elapsed = self.engine.snapshot()
        x = np.arange(len(spec), dtype=np.float64)
        y = spec.astype(np.float64)
        self.curve.setData(x, np.maximum(y, 0.1))
        cps = stats.get("accepted", 0) / max(elapsed, 1e-6)
        live_frac = (stats.get("live_time", 0.0) / max(stats.get("real_time", 1e-9), 1e-9)) * 100
        err = f"  ERROR: {self.engine.last_error}" if self.engine.last_error else ""
        src = "WAV" if self._wav_path else "live"
        self.stats_label.setText(
            f"{src} | real {stats.get('real_time',0):.1f}s  live {live_frac:.1f}%  "
            f"input {cps:.0f} cps  pileup rej {stats.get('rejected_pileup',0)}  "
            f"out {self.out_dir}{err}")
        if self.engine.finished.is_set() and self.engine is not None:
            # wav finished or stream died
            self.on_stop()


def _preload_portaudio() -> None:
    from .capture import preload_portaudio
    preload_portaudio()


def main():
    _preload_portaudio()
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
