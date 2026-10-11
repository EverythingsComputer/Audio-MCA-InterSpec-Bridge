"""Acquisition engine: wires a capture source to the DSP and file outputs.

Used by both the CLI runner and the PySide6 GUI. Thread model:
  - audio thread (live) or reader thread (wav): feed() -> PulseProcessor
  - UI/timer thread: reads spectrum/stats under _lock, triggers saves
"""

from __future__ import annotations

import datetime
import json
import os
import threading
import time

import numpy as np

from .dsp import PulseProcessor, ProcessorConfig
from .writers import HAVE_SPECUTILS, write_spectrum


class Engine:
    def __init__(self, source_factory, cfg: ProcessorConfig, out_dir: str,
                 save_formats=("spe",), autosave_s: float = 5.0,
                 push_cmd: list[str] | None = None,
                 push_mode: str = "mcp", lane: str = "Foreground"):
        """source_factory() -> object with run(callback) and stop().

        push_mode selects how each autosave reaches a running InterSpec:
          "mcp"  (default): POST to InterSpec's built-in MCP API
                  (load_spectrum_file). Updates the visible window in place,
                  no prompts, honors `lane` ("Foreground"/"Background"/
                  "Secondary"). Requires MCP enabled in InterSpec's user
                  llm_config.xml + token in ~/.config/gsbridge/mcp.json or
                  GSBRIDGE_MCP_TOKEN — see gsbridge/mcp.py. Falls back to the
                  "launch" path automatically if InterSpec has no MCP server.
          "launch": run push_cmd + [file] (e.g. ["interspec"]); relies on the
                  desktop shell's single-instance file forwarding.
        """
        self.source_factory = source_factory
        self.cfg = cfg
        self.out_dir = out_dir
        self.save_formats = tuple(f.lstrip(".") for f in save_formats)
        self.autosave_s = autosave_s

        self.processor: PulseProcessor | None = None
        self.source = None
        self.sample_rate: float | None = None
        self.running = False
        self.finished = threading.Event()
        self.last_error: str | None = None
        self.started_at: float | None = None
        self.last_save_at: float | None = None

        self._lock = threading.Lock()
        self._save_thread: threading.Thread | None = None
        self._stop_saving = threading.Event()
        self.push_cmd = push_cmd
        self.push_mode = push_mode          # "mcp" | "launch"
        self.lane = lane                    # Foreground | Background | Secondary
        self._push_proc = None
        self._push_started = 0.0
        self._mcp = None
        self._mcp_dead_logged = False
        self.push_count = 0
        # Stable identity for live saves: InterSpec treats a pushed file whose
        # UUID matches the already-loaded measurement as an update of the same
        # spectrum (loads straight to Foreground, no foreground/background/
        # secondary prompt). final snapshots deliberately get no fixed uuid.
        import uuid as _uuid
        self.session_uuid = str(_uuid.uuid4())

    # ------------------------------------------------------------------ run
    def start(self) -> None:
        os.makedirs(self.out_dir, exist_ok=True)
        self.processor = PulseProcessor(self.sample_rate or 48000.0, self.cfg)
        self.source = self.source_factory()
        self.finished.clear()
        self._stop_saving.clear()
        self.running = True
        self.started_at = time.monotonic()

        def on_block(block: np.ndarray) -> None:
            sr = self.sample_rate or 48000.0
            if self.processor is None:
                return
            with self._lock:
                self.processor.feed(block)

        def runner() -> None:
            try:
                self.source.run(on_block)
            except Exception as e:  # surface to UI
                self.last_error = str(e)
            finally:
                self.running = False
                self.finished.set()

        threading.Thread(target=runner, daemon=True, name="gs-capture").start()
        # write an initial (empty) live file immediately so InterSpec can open
        # it before the first autosave tick
        try:
            self.save_now(tag="live")
        except Exception as e:
            self.last_error = f"initial save failed: {e}"
        self._save_thread = threading.Thread(target=self._saver_loop, daemon=True,
                                             name="gs-saver")
        self._save_thread.start()

    def stop(self) -> None:
        self.running = False
        if self.source is not None:
            self.source.stop()
        self._stop_saving.set()
        # final save even after wav EOF
        try:
            self.save_now(tag="final")
        except Exception:
            pass

    # ------------------------------------------------------------------ save
    def snapshot(self) -> tuple[np.ndarray, dict, float]:
        """(spectrum copy, stats dict, live_time_fraction)."""
        with self._lock:
            spec = self.processor.spectrum.copy() if self.processor is not None \
                else np.zeros(self.cfg.n_channels, dtype=np.uint64)
            stats = self.processor.stats.snapshot() if self.processor else {}
        return spec, stats, time.monotonic() - (self.started_at or time.monotonic())

    def save_now(self, tag: str = "live") -> list[str]:
        spec, stats, _ = self.snapshot()
        st_time = datetime.datetime.now().replace(microsecond=0)
        written = []
        # pin the file UUID for live saves so InterSpec recognises repeated
        # pushes of this session as the same measurement (no open-as prompt)
        uid = self.session_uuid if tag == "live" else None
        for fmt in self.save_formats:
            name = f"gsbridge_{tag}.{fmt}" if tag != "live" else f"gsbridge_live.{fmt}"
            path = os.path.join(self.out_dir, name)
            write_spectrum(path, spec, stats.get("live_time", 0.0),
                           stats.get("real_time", 0.0), title=f"GS-Bridge {tag}",
                           start_time=st_time, uuid=uid)
            written.append(path)
        # machine-readable sidecar for other tools (option-C bridge)
        with open(os.path.join(self.out_dir, "gsbridge_status.json"), "w") as f:
            json.dump({"time": st_time.isoformat(), **stats,
                       "counts_total": int(spec.sum())}, f, indent=1)
        self.last_save_at = time.monotonic()
        if tag == "live":
            self._push(written)
        return written

    def _push(self, paths: list[str]) -> None:
        """Hand the freshly-written file to InterSpec (see __init__ docstring).

        "mcp" mode posts to InterSpec's built-in MCP API and updates the
        visible window in place; if that is unavailable it falls back once to
        the "launch" path. Push failures are non-fatal - files remain
        openable manually.
        """
        if not paths or not self.push_enabled():
            return
        # UUID pinning (which suppresses InterSpec's open-as prompt) works
        # for .spe and .n42; binary .spc has no header field for a UUID.
        primary = next((p for p in paths if p.endswith((".spe", ".n42"))), None)
        if primary is None:
            self.last_error = ("push skipped: save .spe or .n42 "
                               "(UUID pinning needs a header field)")
            return

        if self.push_mode == "mcp":
            try:
                if self._mcp is None:
                    from .mcp import McpPusher
                    self._mcp = McpPusher()
                self._mcp.load(primary, lane=self.lane)
                self.push_count += 1
                return
            except Exception as e:
                self._mcp = None
                if not self._mcp_dead_logged:
                    self.last_error = (f"mcp push unavailable ({e}); "
                                       "falling back to launch push")
                    self._mcp_dead_logged = True
                if not self.push_cmd:
                    return
                # fall through to launch mode

        import subprocess, time as _t
        try:
            # Debounce only briefly: when InterSpec is already running the
            # invoked process forwards and exits in <1 s. On a COLD launch the
            # invoked process *becomes* the app and never exits - so after
            # ~5 s we must keep pushing (those invocations will forward+exit).
            if (self._push_proc is not None and self._push_proc.poll() is None
                    and _t.monotonic() - self._push_started < 5.0):
                return
            self._push_proc = subprocess.Popen(list(self.push_cmd) + [primary],
                                               stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL,
                                               start_new_session=True)
            self._push_started = _t.monotonic()
            self.push_count += 1
        except Exception as e:
            self.last_error = f"push failed: {e}"

    def push_enabled(self) -> bool:
        if self.push_mode == "off":
            return False
        return (self.push_mode == "mcp") or bool(self.push_cmd)

    def _saver_loop(self) -> None:
        while not self._stop_saving.wait(self.autosave_s):
            try:
                self.save_now(tag="live")
            except Exception as e:
                self.last_error = f"save failed: {e}"
