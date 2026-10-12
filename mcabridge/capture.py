"""Audio capture sources: live USB audio codec, or offline WAV for testing.

All sources deliver mono int16 blocks to a callback running on the audio
thread (live) or the calling thread (wav). Device names are matched loosely
so 'USB Audio Codec' finds 'USB AUDIO CODEC', 'hw:CARD=Codec...', etc.
"""

from __future__ import annotations

import queue
import threading
import wave

import numpy as np


def preload_portaudio() -> None:
    """If PortAudio isn't system-installed, try a bundled copy before
    sounddevice gives up (see scripts/bundle_portaudio.sh).

    Search order: PyInstaller bundle dir (_MEIPASS), then <repo>/.local/lib.
    On Windows/macOS the sounddevice wheel already ships PortAudio; this path
    matters mainly for Linux builds without libportaudio2 installed.
    """
    import ctypes
    import ctypes.util
    import os
    import sys
    # In a frozen (PyInstaller) bundle, prefer the BUNDLED copy even if the
    # system has one: that keeps the app self-contained and identical across
    # machines. Outside a bundle, use the system library when present.
    meipass = getattr(sys, "_MEIPASS", None)
    bundled = None
    if meipass:
        for n in ("libportaudio.so.2", "libportaudio.so"):
            cand = os.path.join(meipass, "mcabridge_libs", n)
            if os.path.exists(cand):
                bundled = cand
                break
        if bundled is None:
            cand = os.path.join(meipass, "mcabridge_libs", "portaudio.dll")
            if os.path.exists(cand):
                bundled = cand
    if meipass is not None and bundled is not None:
        pa = bundled                    # frozen: always use the bundle
    elif ctypes.util.find_library("portaudio"):
        return                          # unfrozen + system lib present
    else:
        # unfrozen, no system lib -> try <repo>/.local/lib (no-root installs)
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        libdir = os.path.join(here, ".local", "lib")
        pa = None
        for n in ("libportaudio.so.2", "libportaudio.so"):
            cand = os.path.join(libdir, n)
            if os.path.exists(cand):
                pa = cand
                break
        if pa is None:
            return
    # load jack first (dependency of portaudio); glibc resolves DT_NEEDED
    # against already-loaded objects with RTLD_GLOBAL
    libdir = os.path.dirname(pa)
    for name in ("libjack.so.0", "libportaudio.so.2"):
        cand = os.path.join(libdir, name)
        if os.path.exists(cand):
            try:
                ctypes.CDLL(cand, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass
    # sounddevice probes via ctypes.util.find_library before dlopen; make the
    # chosen copy discoverable (must happen before `import sounddevice`)
    import ctypes.util as _cu
    if _cu.find_library("portaudio") is None:
        _orig = _cu.find_library

        def _patched(name):
            if name == "portaudio":
                return pa
            return _orig(name)

        _cu.find_library = _patched


class WavSource:
    """Offline source: reads a (possibly 16-bit stereo) WAV file block-wise."""

    def __init__(self, path: str, channel: int = 0, blocksize: int = 4800):
        self.path = path
        self.channel = channel
        self.blocksize = blocksize
        self.sample_rate = None
        self._stop = threading.Event()

    def run(self, callback) -> None:
        with wave.open(self.path, "rb") as w:
            assert w.getsampwidth() == 2, "WAV must be 16-bit PCM"
            self.sample_rate = w.getframerate()
            nch = w.getnchannels()
            while not self._stop.is_set():
                frames = w.readframes(self.blocksize)
                if not frames:
                    break
                a = np.frombuffer(frames, dtype=np.int16)
                if nch > 1:
                    a = a.reshape(-1, nch)[:, self.channel]
                callback(a)

    def stop(self) -> None:
        self._stop.set()


class AudioStreamSource:
    """Live capture via sounddevice/PortAudio.

    Falls back gracefully: if the requested device is missing, raises with a
    list of available input devices.
    """

    def __init__(self, device_match: str | None = None, sample_rate: float = 48000.0,
                 blocksize: int = 2400, channel: int = 0):
        self.device_match = device_match.lower() if device_match else None
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self.channel = channel
        self._q: queue.Queue | None = None
        self._stream = None
        self._stop = threading.Event()
        self.overrun_count = 0

    @staticmethod
    def list_inputs() -> list[tuple[int, str]]:
        preload_portaudio()
        import sounddevice as sd
        return [(i, d["name"]) for i, d in enumerate(sd.query_devices())
                if d["max_input_channels"] > 0]

    def _find_device(self) -> int:
        import sounddevice as sd
        devs = self.list_inputs()
        if self.device_match is None:
            # prefer anything that looks like a USB audio codec
            for i, name in devs:
                low = name.lower()
                if "codec" in low or "usb" in low:
                    return i
            raise RuntimeError(
                "No USB audio codec input found. Available inputs:\n  "
                + "\n  ".join(f"[{i}] {n}" for i, n in devs)
                + "\nPlug in the GS-PRO-V5 or pass --device.")
        for i, name in devs:
            if self.device_match in name.lower():
                return i
        raise RuntimeError(
            f"No input device matching '{self.device_match}'. Available inputs:\n  "
            + "\n  ".join(f"[{i}] {n}" for i, n in devs))

    def start(self, callback) -> None:
        preload_portaudio()
        import sounddevice as sd

        def cb(indata, frames, time_info, status):
            if status:
                self.overrun_count += 1
            mono = indata[:, self.channel] if indata.shape[1] > self.channel else indata[:, 0]
            callback(np.array(mono, dtype=np.int16, copy=True))

        dev = self._find_device()
        self._stream = sd.InputStream(
            device=dev, samplerate=self.sample_rate, channels=max(2, self.channel + 1),
            dtype="int16", blocksize=self.blocksize, callback=cb)
        self._stream.start()

    def run(self, callback) -> None:
        """Engine contract: block until stop() is called."""
        import threading
        self.start(callback)
        while not self._stop.is_set():
            threading.Event.wait(self._stop, 0.2)

    def stop(self) -> None:
        self._stop.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
