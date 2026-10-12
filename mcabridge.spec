# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for mcabridge.

ONE executable, `mcabridge`: run it with no arguments to open the GUI; pass
CLI flags (--list, --wav ..., --seconds ...) for headless operation. A single
entry point avoids PyInstaller's multi-EXE onedir pitfalls (both executables
must share identical binaries/datas).

Build (from the repo root, in an env with all deps installed):
    pyinstaller --noconfirm mcabridge.spec

The runtime hook (hooks/rthook_portaudio.py) preloads bundled PortAudio before
sounddevice is imported anywhere.
"""
import os

ROOT = os.path.dirname(os.path.abspath(SPEC))          # noqa: F821 (PyInstaller)


def _hiddenimports():
    imports = [
        "numpy",
        "sounddevice",
        "_sounddevice_data",
        "SpecUtils",
        "mcabridge",
        "mcabridge.cli",
        "mcabridge.gui",
        "mcabridge.capture",
        "mcabridge.dsp",
        "mcabridge.engine",
        "mcabridge.mcp",
        "mcabridge.writers",
    ]
    # GUI deps are optional at runtime; include only if installed so the spec
    # also works in a minimal (CLI-only) build environment.
    try:
        import PySide6  # noqa: F401
        imports += ["PySide6", "pyqtgraph"]
    except ImportError:
        pass
    return imports


a = Analysis(
    [os.path.join(ROOT, "entrypoint.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=_hiddenimports(),
    hookspath=[os.path.join(ROOT, "hooks")],
    runtime_hooks=[os.path.join(ROOT, "hooks", "rthook_portaudio.py")],
    excludes=["tkinter", "matplotlib", "IPython", "jupyter"],
)

pyz = PYZ(a.pure)

# onedir: EXE holds only the entry script; COLLECT assembles the folder with
# the shared _internal dependency tree (fast startup, easy to inspect/patch).
exe = EXE(
    pyz, a.scripts,
    name="mcabridge",
    debug=False, strip=False, upx=False,
    # console=True: the CLI needs stdout/stderr; the GUI opens its own window
    # on top (a console window also appears on Windows - acceptable trade-off
    # for one entry point).
    console=True,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    # distinct from the EXE basename ("mcabridge") to avoid a path collision
    name="mcabridge-app",
)
