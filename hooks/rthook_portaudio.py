"""PyInstaller runtime hook for gsbridge.

Runs before either entry point (gsbridge / gsbridge-gui). Preloads a bundled
PortAudio if the system has none, so sounddevice works on machines without
libportaudio2 installed. On Windows/macOS the sounddevice wheel already ships
PortAudio, so this is effectively a no-op there.
"""
try:
    from gsbridge.capture import preload_portaudio

    preload_portaudio()
except Exception:
    # capture.py only needs numpy at import time; if even that fails we still
    # want the app to start (WAV mode works without PortAudio)
    pass
