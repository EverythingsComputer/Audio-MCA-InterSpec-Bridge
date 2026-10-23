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

# ------------------------------------------------------------------ theme
# Dark navy cyberpunk palette, deliberately high-contrast (WCAG-ish): the
# plot and log/status text must never be dark-on-dark regardless of the
# host desktop's Qt theme. Accents: electric blue (primary), neon green
# (spectrum curve / OK), amber-orange (pause/warning).

BG      = "#0d1420"   # window background
PANEL   = "#131c2b"   # panels, inputs
EDGE    = "#26344a"   # borders
TEXT    = "#dbe7f7"   # primary text (high contrast on BG)
DIM     = "#8fa6c4"   # secondary text (still ~7:1 on BG)
BLUE    = "#4ea1ff"
GREEN   = "#59f7a0"
ORANGE  = "#ffa04d"
GRID_PEN = "#6c86a8"   # grid/tick lines: must be clearly lighter than BG —
                       # pyqtgraph draws gridlines with the AXIS pen, so the
                       # near-black EDGE pen made the grid effectively
                       # invisible (the "grid doesn't work" report).

QSS = f"""
QWidget            {{ background: {BG}; color: {TEXT}; }}
QLabel             {{ background: transparent; color: {TEXT}; }}
QToolTip           {{ background: {PANEL}; color: {TEXT}; border: 1px solid {BLUE}; }}
QPushButton        {{ background: {PANEL}; color: {TEXT}; border: 1px solid {EDGE};
                       border-radius: 4px; padding: 5px 12px; }}
QPushButton:hover  {{ border-color: {BLUE}; color: #ffffff; }}
QPushButton:pressed{{ background: #1b2a40; }}
QPushButton:disabled {{ color: {DIM}; }}
QPushButton:checked  {{ border-color: {GREEN}; color: {GREEN}; }}
QCheckBox          {{ background: transparent; color: {TEXT}; spacing: 6px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {EDGE};
                       border-radius: 3px; background: {PANEL}; }}
QCheckBox::indicator:checked {{ background: {BLUE}; border-color: {BLUE}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox
                   {{ background: {PANEL}; color: {TEXT}; border: 1px solid {EDGE};
                      border-radius: 4px; padding: 3px 6px; selection-background-color: {BLUE};
                      selection-color: #ffffff; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; color: {TEXT};
                      selection-background-color: #1b3a5c; border: 1px solid {EDGE}; }}
QGroupBox          {{ border: 1px solid {EDGE}; border-radius: 6px; margin-top: 8px;
                      color: {DIM}; background: {PANEL}; }}
QGroupBox::title   {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
QDialogButtonBox QPushButton {{ min-width: 72px; }}
"""


def apply_theme(app) -> None:
    """Dark theme + app icon, safe on any host palette."""
    from PySide6.QtGui import QIcon, QPalette, QColor
    app.setStyleSheet(QSS)
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.Base, QColor(PANEL))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(PANEL))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(BLUE))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor(PANEL))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    app.setPalette(pal)
    icon = app_icon()
    if icon is not None:
        app.setWindowIcon(icon)


def app_icon():
    import os
    from PySide6.QtGui import QIcon
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo.png")
    return QIcon(p) if os.path.exists(p) else None


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
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            p = McpPusher(bearer_token=self.token_edit.text().strip() or None)
            p._ensure()
            self._show(f"OK: InterSpec MCP reachable on port {p.port}; token "
                       "accepted.")
        except Exception as e:
            self._show(f"NOT READY: {e}<br>Is InterSpec running with MCP "
                       "enabled, and is the token identical on both sides?",
                       ok=False)
        finally:
            QApplication.restoreOverrideCursor()




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
        self.plot = pg.PlotWidget(background=BG)
        # NOTE: gridlines are drawn with the AXIS pen (pyqtgraph AxisItem),
        # so the pen must be lighter than BG or the grid reads as invisible.
        self.plot.getAxis("left").setPen(pg.mkPen(GRID_PEN))
        self.plot.getAxis("bottom").setPen(pg.mkPen(GRID_PEN))
        self.plot.getAxis("left").setTextPen(pg.mkPen(DIM))
        self.plot.getAxis("bottom").setTextPen(pg.mkPen(DIM))
        self.plot.showGrid(x=True, y=True, alpha=0.4)
        self.plot.setLabel("left", "Counts")
        self.plot.setLabel("bottom", "Channel")
        self.plot.setMouseEnabled(x=True, y=True)
        self.curve = self.plot.plot(pen=pg.mkPen(GREEN, width=1))
        self.peak_vline = pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen(ORANGE, width=1))
        self.peak_vline.setVisible(False)
        self.plot.addItem(self.peak_vline)
        self.peak_text = pg.TextItem("", color=ORANGE, anchor=(0, 1))
        self.plot.addItem(self.peak_text)
        self._y_floor = 0.1          # bottom of the y range (counts units)
        self._placeholder = pg.TextItem(
            "no data — press Start", color=DIM, anchor=(0.5, 0.5))
        from PySide6.QtGui import QFont as _QFont
        self._placeholder.setFont(_QFont("Sans Serif", 13))
        self.plot.addItem(self._placeholder, ignoreBounds=True)
        self.plot.scene().sigMouseClicked.connect(self._on_plot_click)
        self._last_spec = None
        layout.addWidget(self.plot, stretch=1)

        # ---- visualization row (scale controls; Reset restores defaults)
        visrow = QHBoxLayout()
        visrow.addWidget(QLabel("Y scale:"))
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["Log", "Linear", "Sqrt"])
        self.scale_combo.setToolTip("Vertical axis scale for the live spectrum.")
        self.scale_combo.setFixedWidth(90)
        visrow.addWidget(self.scale_combo)
        self.floor_spin = QDoubleSpinBox()
        self.floor_spin.setRange(0.0, 1e6)
        self.floor_spin.setSingleStep(1.0)
        self.floor_spin.setValue(0.0)
        self.floor_spin.setToolTip(
            "Y-axis floor: set the bottom of the plot to this count and\n"
            "stretch the range above it (e.g. 1 or 10 cuts away the empty\n"
            "sub-count region on a log axis). 0 = automatic vertical range.")
        self.floor_spin.setFixedWidth(90)
        visrow.addWidget(self.floor_spin)
        self.chk_grid = QCheckBox("Grid")
        self.chk_grid.setChecked(True)
        visrow.addWidget(self.chk_grid)
        self.btn_view_reset = QPushButton("Reset view")
        self.btn_view_reset.setToolTip("Restore scale, floor, grid and zoom defaults.")
        visrow.addWidget(self.btn_view_reset)
        visrow.addStretch(1)
        layout.addLayout(visrow)

        def _vis_connect():
            self.scale_combo.currentIndexChanged.connect(self._apply_scale)
            self.floor_spin.valueChanged.connect(self._apply_scale)
            self.chk_grid.toggled.connect(
                lambda on: self.plot.showGrid(x=on, y=on, alpha=0.4))
            self.btn_view_reset.clicked.connect(self._reset_view)
        _vis_connect()
        self._apply_scale()

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
        self.push_mode_combo.setMinimumWidth(210)   # no clipped text
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
        self.hint.setStyleSheet(
            f"padding:6px; background:{PANEL}; border:1px solid {EDGE};"
            f" border-radius:4px; color:{TEXT};")
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
        out = self.out_dir or os.path.expanduser("~/Documents/mca-bridge-output")
        self.out_dir = out
        os.makedirs(out, exist_ok=True)
        system = platform.system()
        try:
            if system == "Linux":
                subprocess.Popen(["xdg-open", self.out_dir])
            elif system == "Darwin":
                subprocess.Popen(["open", self.out_dir])
            elif system == "Windows":
                os.startfile(self.out_dir)  # type: ignore[attr-defined]
        except Exception as e:
            QMessageBox.warning(self, "Open folder", f"Could not open {self.out_dir}: {e}")

    # ---------------------------------------------------------------- refresh
    def _on_plot_click(self, ev):
        if self._last_spec is None:
            return
        pos = ev.scenePos()
        vb = self.plot.getViewBox()
        pt = vb.mapSceneToView(pos)
        ch = int(round(pt.x()))
        if ch < 0 or ch >= len(self._last_spec):
            return
        counts = int(self._last_spec[ch])
        self.peak_vline.setPos(ch)
        self.peak_vline.setVisible(True)
        self.peak_text.setText(f"ch {ch}: {counts} counts")
        self.peak_text.setPos(ch, counts if counts > 0 else 1)
    def _apply_scale(self):
        mode = self.scale_combo.currentText() if hasattr(self, "scale_combo") else "Log"
        # Sqrt is a data transform done in refresh(); the axis itself stays
        # linear. Only Log toggles the axis.
        self.plot.setLogMode(x=False, y=(mode == "Log"))

    def _reset_view(self):
        self.scale_combo.setCurrentText("Log")
        self.floor_spin.setValue(0.0)
        self.chk_grid.setChecked(True)
        self.plot.enableAutoRange(axis="y")
        self.plot.enableAutoRange(axis="x")

    def refresh(self):
        if not self.engine:
            # keep the "no data" note centered in the current view
            vb = self.plot.viewRange()
            self._placeholder.setPos(
                (vb[0][0] + vb[0][1]) / 2, (vb[1][0] + vb[1][1]) / 2)
            self._placeholder.show()
            return
        self._placeholder.hide()
        spec, stats, elapsed = self.engine.snapshot()
        x = np.arange(len(spec), dtype=np.float64)
        mode = self.scale_combo.currentText()
        floor = self.floor_spin.value()
        eff_floor = floor if floor > 0 else (0.1 if mode == "Log" else 0.0)
        y = np.maximum(spec.astype(np.float64), eff_floor)
        if mode == "Sqrt":
            y = np.sqrt(y)
        self.curve.setData(x, y)
        self._last_spec = spec
        cps = stats.get("accepted", 0) / max(elapsed, 1e-6)
        live_frac = (stats.get("live_time", 0.0) / max(stats.get("real_time", 1e-9), 1e-9)) * 100
        err = (f'  <span style="color:#ff7070">ERROR: {self.engine.last_error}</span>'
               if self.engine.last_error else "")
        src = "WAV" if self._wav_path else "live"
        if self.engine.paused.is_set():
            src = f'<span style="color:{ORANGE}">{src} PAUSED</span>'
        total = int(spec.sum())
        if total > 0:
            max_ch = int(np.argmax(spec))
            # crude FWHM around peak
            peak = int(spec[max_ch])
            half = peak / 2.0
            lo = max_ch
            while lo > 0 and spec[lo] > half:
                lo -= 1
            hi = max_ch
            while hi < len(spec) - 1 and spec[hi] > half:
                hi += 1
            fwhm = hi - lo
        else:
            max_ch = 0
            fwhm = 0
        dead_pct = (1.0 - live_frac / 100.0) * 100.0
        self.stats_label.setText(
            f"{src} | real {stats.get('real_time',0):.1f}s  live {live_frac:.1f}%  "
            f"dead {dead_pct:.1f}%  input {cps:.0f} cps  "
            f"total {total}  peak ch {max_ch} (FWHM {fwhm})  "
            f"pileup rej {stats.get('rejected_pileup',0)}  "
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
    apply_theme(app)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


def run_self_test() -> int:
    """Construct the full GUI headlessly and exit (CI bundle smoke test).

    Proves the frozen bundle's GUI path works end to end — PySide6 imports,
    Qt platform plugin loads, theme applies, MainWindow builds and shows —
    without needing a display or touching audio devices. The v0.2.x smoke
    tests only ran --gen-token (pure CLI), so a broken GUI could ship
    silently; that is what this gates against.

    Exits via os._exit() on success: letting the interpreter tear down a
    QApplication created in function scope segfaults at shutdown (PySide6
    destruction-order issue, harmless to users but it would fail CI).
    """
    import os as _os
    if not _os.environ.get("QT_QPA_PLATFORM"):
        _os.environ["QT_QPA_PLATFORM"] = "offscreen"
    _preload_portaudio()
    app = QApplication(sys.argv[:1])     # strip our flag from Qt's parsing
    apply_theme(app)
    w = MainWindow()
    w.show()
    QTimer.singleShot(400, app.quit)     # one event-loop spin: proves show()
    app.exec()
    print("self-test OK")
    sys.stdout.flush()
    _os._exit(0)
