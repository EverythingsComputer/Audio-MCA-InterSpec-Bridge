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

# read __version__ without importing package deps
_VERSION = "0.0.0"
with open(os.path.join(ROOT, "mcabridge", "__init__.py"), encoding="utf-8") as _f:
    for _line in _f:
        if _line.startswith("__version__"):
            _VERSION = _line.split("=")[1].strip().strip("\"'")


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
        "mcabridge.setup",
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
    # app icon/logo shipped next to the package (QIcon loads it at runtime)
    datas=[(os.path.join(ROOT, "mcabridge", "assets"), "mcabridge/assets")],
    hiddenimports=_hiddenimports(),
    hookspath=[os.path.join(ROOT, "hooks")],
    runtime_hooks=[os.path.join(ROOT, "hooks", "rthook_portaudio.py")],
    excludes=["tkinter", "matplotlib", "IPython", "jupyter"],
)

pyz = PYZ(a.pure)

# onedir: EXE holds only the entry script; COLLECT assembles the folder with
# the shared _internal dependency tree (fast startup, easy to inspect/patch).
# App icon per platform (taskbar / dock / explorer); Linux uses the window
# icon set at runtime by the theme (QApplication.setWindowIcon).
import sys as _sys
_ICON = {
    "win32": os.path.join(ROOT, "mcabridge", "assets", "app.ico"),
    "darwin": os.path.join(ROOT, "mcabridge", "assets", "app.icns"),
}.get(_sys.platform)

exe = EXE(
    pyz, a.scripts,
    name="mcabridge",
    debug=False, strip=False, upx=False,
    icon=_ICON,
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

# macOS: build a real .app via PyInstaller's BUNDLE target. Manual assembly of
# an onedir into an .app is NOT signable: Apple forbids dotted directory names
# under Contents/Frameworks (codesign: "bundle format unrecognized, invalid,
# or unsuitable" on e.g. numpy-2.5.4.dist-info), so the bundle seal
# (_CodeSignature/CodeResources) silently fails to be created and macOS
# reports the app as "damaged". BUNDLE implements Apple's placement rules
# (data -> Contents/Resources, dot-name relocation) — see PyInstaller's
# building/osx.py docs.
import sys as _sys
if _sys.platform == "darwin":
    bundle = BUNDLE(
        coll,
        name="mcabridge.app",
        icon=_ICON,          # -> Contents/Resources + CFBundleIconFile (dock/Finder)
        info_plist={
            "CFBundleName": "Audio MCA Bridge",
            "CFBundleDisplayName": "Audio MCA Bridge",
            "CFBundleIdentifier": "com.mcabridge.app",
            "CFBundleVersion": _VERSION,
            "CFBundleShortVersionString": _VERSION,
            "CFBundlePackageType": "APPL",
            "NSHighResolutionCapable": True,
        },
    )
