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
                 push_cmd: list[str] | None = None):
        """source_factory() -> object with run(callback) and stop().

        push_cmd: if given (e.g. ["xdg-open"] or ["/path/to/InterSpec.AppImage"]),
        executed as push_cmd + [saved_file_path] after each autosave. InterSpec's
        desktop shell forwards a file argument to its already-running session,
        which re-parses the file and repaints -> live display updates.
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
        self._push_proc = None
        self.push_count = 0

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
        for fmt in self.save_formats:
            name = f"gsbridge_{tag}.{fmt}" if tag != "live" else f"gsbridge_live.{fmt}"
            path = os.path.join(self.out_dir, name)
            write_spectrum(path, spec, stats.get("live_time", 0.0),
                           stats.get("real_time", 0.0), title=f"GS-Bridge {tag}",
                           start_time=st_time)
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
        """Hand the freshly-written file to InterSpec's desktop shell.

        The previous push process must have exited (it does, once the running
        session accepts the file); this prevents double-launching a cold-start
        InterSpec. Push failures are non-fatal - files remain openable manually.
        """
        if not self.push_cmd or not paths:
            return
        import subprocess
        try:
            if self._push_proc is not None and self._push_proc.poll() is None:
                return                      # previous push still in flight; skip
            primary = next((p for p in paths if p.endswith((".spe", ".spc", ".n42"))), paths[0])
            self._push_proc = subprocess.Popen(list(self.push_cmd) + [primary],
                                               stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL)
            self.push_count += 1
        except Exception as e:
            self.last_error = f"push failed: {e}"

    def _saver_loop(self) -> None:
        while not self._stop_saving.wait(self.autosave_s):
            try:
                self.save_now(tag="live")
            except Exception as e:
                self.last_error = f"save failed: {e}"
