"""PySide6 GUI for mcabridge.

Layout: live spectrum plot (pyqtgraph), run controls, device/threshold
settings, stats readout, and an output panel telling you exactly which files
to open in InterSpec.
"""

from __future__ import annotations

import sys

import numpy as np
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QGuiApplication
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


class McpTokenDialog(QDialog):
    """Shared-token setup for the InterSpec MCP push, done inside mcabridge.

    The same token must end up in two places: mcabridge's own mcp.json (which
    this dialog writes directly) and InterSpec — either written into its
    llm_config.xml by this dialog ("Configure both", run with InterSpec
    closed), or pasted manually into Tools -> LLM Assistant here in the GUI.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        from . import setup as msetup
        self.setup = msetup
        self.setWindowTitle("InterSpec MCP token")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)

        intro = QLabel(
            "One shared token lets mcabridge push into the running InterSpec.\n"
            "Generate one here, then either click <b>Configure both</b> (needs\n"
            "InterSpec closed) or paste it into InterSpec yourself:\n"
            "<b>Tools → LLM Assistant → MCP Server → token → Save</b>.")
        intro.setTextFormat(Qt.RichText)
        lay.addWidget(intro)

        row = QHBoxLayout()
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("bearer token (hex)")
        self.btn_gen = QPushButton("Generate")
        self.btn_gen.setToolTip("Generate a fresh random token (does not save yet).")
        self.btn_reveal = QPushButton("Show")
        self.btn_reveal.setCheckable(True)
        self.btn_reveal.toggled.connect(
            lambda on: self.token_edit.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password))
        self.btn_copy = QPushButton("Copy")
        row.addWidget(self.token_edit, stretch=1)
        row.addWidget(self.btn_gen)
        row.addWidget(self.btn_reveal)
        row.addWidget(self.btn_copy)
        lay.addLayout(row)

        saved = self.setup.read_bridge_token()
        if saved:
            self.token_edit.setText(saved)
            status = QLabel(f"A token is already saved for mcabridge "
                            f"({saved[:4]}…{saved[-4:]}). Leave it as-is unless "
                            "you also change it in InterSpec.")
        else:
            status = QLabel("No token saved yet — click Generate.")
        status.setStyleSheet("color:#9fb6c9;")
        lay.addWidget(status)

        btns = QHBoxLayout()
        self.btn_save = QPushButton("Save for mcabridge")
        self.btn_save.setToolTip("Write the token to mcabridge's mcp.json only "
                                 "(you paste it into InterSpec yourself).")
        self.btn_both = QPushButton("Configure both (InterSpec + mcabridge)")
        self.btn_both.setToolTip(
            "Writes the token into InterSpec's llm_config.xml AND mcabridge's\n"
            "mcp.json, and enables its MCP server. CLOSE InterSpec first — a\n"
            "running instance overwrites that file when it exits.")
        self.btn_test = QPushButton("Test connection")
        self.btn_test.setToolTip("mcabridge --check: is the InterSpec MCP API "
                                 "reachable and does the token work?")
        btns.addWidget(self.btn_save)
        btns.addWidget(self.btn_both)
        btns.addWidget(self.btn_test)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)
        lay.addWidget(self.status)

        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        close.accepted.connect(self.reject)
        lay.addWidget(close)

        self.btn_gen.clicked.connect(self._generate)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_save.clicked.connect(self._save)
        self.btn_both.clicked.connect(self._both)
        self.btn_test.clicked.connect(self._test)

    def _show(self, msg: str, ok: bool = True):
        color = "#8fd08f" if ok else "#e0a0a0"
        self.status.setText(f'<span style="color:{color}">{msg}</span>')

    def _generate(self):
        self.token_edit.setText(self.setup.generate_token())
        self.btn_reveal.setChecked(True)
        self._show("New token generated — save it, then set the same one in "
                   "InterSpec (paste or 'Configure both').")

    def _copy(self):
        t = self.token_edit.text().strip()
        if t:
            QGuiApplication.clipboard().setText(t)
            self._show("Token copied to clipboard — paste it into InterSpec's "
                       "LLM Assistant MCP token field.")

    def _save(self):
        try:
            path = self.setup.save_bridge_token(self.token_edit.text())
        except ValueError as e:
            self._show(str(e), ok=False)
            return
        self._show(f"Saved for mcabridge → {path}. Now set the same token in "
                   "InterSpec (Tools → LLM Assistant) and click Test.")

    def _both(self):
        try:
            log = self.setup.configure_interspec(self.token_edit.text())
            path = self.setup.save_bridge_token(self.token_edit.text())
        except Exception as e:
            self._show(f"Failed: {e}", ok=False)
            return
        self._show("Configured both sides:<br>" + "<br>".join(
            log[:3]) + f"<br>bridge token → {path}<br>"
            "Restart InterSpec, then click Test connection.")

    def _test(self):
        from .mcp import McpPusher
        try:
            p = McpPusher(bearer_token=self.token_edit.text().strip() or None)
            p._ensure()
            self._show(f"OK: InterSpec MCP reachable on port {p.port}; token "
                       "accepted.")
        except Exception as e:
            self._show(f"NOT READY: {e}<br>Is InterSpec running with MCP "
                       "enabled, and is the token identical on both sides?",
                       ok=False)




class SettingsDialog(QDialog):
    def __init__(self, cfg: ProcessorConfig, device_text: str = "codec",
                 sample_rate: float = 48000.0, cal_text: str = "", parent=None):
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

        self.cal_edit = QLineEdit(cal_text or "")
        self.cal_edit.setPlaceholderText("e.g. -1.5,0.734   (c0,c1[,c2,c3] in keV)")
        self.cal_edit.setToolTip(
            "Optional energy calibration polynomial embedded in every saved and\n"
            "pushed spectrum: E(keV) = c0 + c1*ch + c2*ch^2 + c3*ch^3.\n"
            "Get coefficients from InterSpec's Energy Calibration tool (fit peaks\n"
            "on a paused or stopped run), paste them here, then resume - the\n"
            "'no energy calibration' warning disappears and pushes carry it.")
        form.addRow("Energy cal (keV):", self.cal_edit)

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
        self.setWindowTitle("Audio MCA → InterSpec Bridge")
        self.resize(980, 640)

        self.cfg = ProcessorConfig()
        self.device_text = "codec"
        self.sample_rate = 48000.0
        self.out_dir = None  # set below
        self.engine: Engine | None = None
        self._wav_path: str | None = None
        self.cal_text: str = ""            # energy cal coeffs (comma string)

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
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setEnabled(False)
        self.btn_pause.setToolTip("Freeze counting (clocks stop, no pushes) so you can\n"
                                  "calibrate/inspect in InterSpec; press again to resume.\n"
                                  "The paused spectrum stays loaded and keeps accumulating\n"
                                  "in InterSpec until resumed - nothing resets.")
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
        for w in (self.btn_start, self.btn_pause, self.btn_stop, self.btn_settings,
                  self.btn_wav, self.btn_live, self.btn_open_out):
            ctrl.addWidget(w)
        ctrl.addStretch(1)
        ctrl.addWidget(QLabel("Save:"))
        ctrl.addWidget(self.chk_save_spe)
        ctrl.addWidget(self.chk_save_spc)
        ctrl.addWidget(self.chk_save_n42)
        layout.addLayout(ctrl)

        # ---- push-to-InterSpec row
        pushrow = QHBoxLayout()
        self.chk_push = QCheckBox("Push each autosave into running InterSpec window")
        self.chk_push.setChecked(True)
        self.push_mode_combo = QComboBox()
        self.push_mode_combo.addItems([
            "MCP API (live repaint)",
            "Launch cmd (one-time handoff)"])
        self.push_mode_combo.setToolTip("""
MCP API: posts each autosave to InterSpec's built-in MCP server
(load_spectrum_file) - updates the visible window in place, no prompts,
and honors the lane selector. Requires enabling MCP once in InterSpec
(see README). This is the live feed.

Launch cmd: runs `<cmd> <file>` after each autosave. Works as a ONE-TIME
handoff into an empty InterSpec, and re-renders a file that is ALREADY
displayed (same path+UUID, once per session). It does NOT work as a live
feed: repeated pushes of the same file are ignored by InterSpec's file
model, and a new file each cycle triggers an open-as prompt. Use only for
older InterSpec builds without MCP.""")
        self.lane_combo = QComboBox()
        self.lane_combo.addItems(["Foreground", "Background", "Secondary"])
        self.lane_combo.setToolTip("Which InterSpec slot to load into (MCP mode).")
        self.push_cmd_edit = QLineEdit("interspec")
        self.push_cmd_edit.setToolTip(
            "Command run as `<cmd> <file>` after each autosave in launch-cmd "
            "mode (one-time handoff only - see mode tooltip).")
        self.push_cmd_edit.setMaximumWidth(140)
        self.btn_token = QPushButton("MCP token…")
        self.btn_token.setToolTip(
            "Generate / enter / test the shared InterSpec MCP bearer token.\n"
            "Same token goes in InterSpec (Tools → LLM Assistant) and here;\n"
            "'Configure both' can write it into InterSpec's config directly.")
        pushrow.addWidget(self.chk_push)
        pushrow.addWidget(self.push_mode_combo)
        pushrow.addWidget(QLabel("lane:"))
        pushrow.addWidget(self.lane_combo)
        pushrow.addWidget(QLabel("cmd:"))
        pushrow.addWidget(self.push_cmd_edit)
        pushrow.addWidget(self.btn_token)
        pushrow.addStretch(1)
        layout.addLayout(pushrow)

        # ---- InterSpec hint
        self.hint = QLabel(
            "Push ON (MCP): start InterSpec first, then Start here — each autosave\n"
            "repaints the running window in place, into the chosen lane, no prompts.\n"
            "Needs MCP enabled once in InterSpec (see README). Launch-cmd mode is a\n"
            "one-time handoff for older InterSpec builds without MCP (not a live feed).\n"
            "Push OFF: open the .spe manually.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("padding:6px; background:#22303c; border-radius:4px;")
        layout.addWidget(self.hint)

        # default output dir next to home
        import os
        self.out_dir = os.path.expanduser("~/Documents/mca-bridge-output")

        self.btn_start.clicked.connect(self.on_start)
        self.btn_pause.clicked.connect(self.on_pause)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_settings.clicked.connect(self.on_settings)
        self.btn_wav.clicked.connect(self.on_wav)
        self.btn_live.clicked.connect(self.on_back_to_live)
        self.btn_open_out.clicked.connect(self.on_open_out)
        self.btn_token.clicked.connect(self.on_token)

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
        try:
            ecal = ([float(x) for x in self.cal_text.split(",")]
                    if self.cal_text.strip() else None)
        except ValueError:
            QMessageBox.warning(self, "Energy cal",
                                "Coefficients must be comma-separated numbers,"
                                " e.g. -1.5,0.734")
            return

        def factory():
            if wav_path:
                return WavSource(wav_path, blocksize=int(self.sample_rate // 10))
            return AudioStreamSource(device_match=dtxt or None, sample_rate=self.sample_rate)

        mode = ("mcp" if self.push_mode_combo.currentIndex() == 0 else "launch") \
            if self.chk_push.isChecked() else "off"
        self.engine = Engine(factory, self.cfg, self.out_dir, save_formats=fmts,
                             push_cmd=self.push_cmd_edit.text().strip().split()
                             or ["interspec"],
                             push_mode=mode, lane=self.lane_combo.currentText(),
                             energy_cal=ecal)
        self.engine.sample_rate = self.sample_rate
        try:
            self.engine.start()
        except Exception as e:
            QMessageBox.critical(self, "Start failed", str(e))
            self.engine = None
            return
        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("Pause")
        self.btn_stop.setEnabled(True)
        # settings stay available while running: energy cal applies live (next
        # autosave); device/threshold changes apply on next Start.

    def on_pause(self):
        if not self.engine:
            return
        if self.engine.paused.is_set():
            self.engine.resume()
            self.btn_pause.setText("Pause")
        else:
            self.engine.pause()
            self.btn_pause.setText("Resume")

    def on_stop(self):
        if self.engine:
            self.engine.stop()
            self.engine = None
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("Pause")
        self.btn_stop.setEnabled(False)
        self.btn_settings.setEnabled(True)

    def on_settings(self):
        dlg = SettingsDialog(self.cfg, device_text=self.device_text,
                             sample_rate=self.sample_rate,
                             cal_text=self.cal_text, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.cfg = dlg.apply_to_cfg()
            self.device_text = dlg.device_edit.text().strip()
            self.sample_rate = dlg.rate_box.value()
            self.cal_text = dlg.cal_edit.text().strip()
            # energy cal can be applied to a live/paused run (e.g. paste coeffs
            # fitted in InterSpec during a pause; takes effect on next autosave)
            if self.engine is not None:
                try:
                    self.engine.energy_cal = ([float(x) for x in self.cal_text.split(",")]
                                              if self.cal_text.strip() else None)
                except ValueError:
                    QMessageBox.warning(self, "Energy cal",
                                        "Coefficients must be comma-separated numbers,"
                                        " e.g. -1.5,0.734")

    def on_wav(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open WAV (16-bit PCM)", "",
                                              "WAV files (*.wav);;All files (*)")
        if path:
            self._wav_path = path
            self.btn_live.setEnabled(True)
            self.setWindowTitle(f"Audio MCA Bridge — replaying {path}")

    def on_back_to_live(self):
        self._wav_path = None
        self.btn_live.setEnabled(False)
        self.setWindowTitle("Audio MCA → InterSpec Bridge")

    def on_token(self):
        dlg = McpTokenDialog(parent=self)
        dlg.exec()

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
        if self.engine.paused.is_set():
            src += " PAUSED"
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
