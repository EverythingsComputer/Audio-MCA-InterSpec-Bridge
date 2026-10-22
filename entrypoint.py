"""PyInstaller entry shim for mcabridge.

A frozen script loses its package context, so ``from .dsp import ...`` inside
mcabridge.cli fails. This shim restores it by importing the real package module
and delegating to its main(). Build with:  pyinstaller --noconfirm mcabridge.spec
(spec points Analysis at this file).
"""
import runpy
import sys


def _log_crash(exc: BaseException) -> None:
    """Append a traceback to a per-user log.

    When the frozen .app is double-clicked, stdout/stderr go nowhere, so a
    startup exception looks like an instant crash/hang with no diagnostics.
    Writing to the platform config dir makes the failure findable. Best-effort:
    never let logging itself crash the app.
    """
    try:
        import datetime
        import os
        import traceback
        from pathlib import Path
        if sys.platform == "darwin":
            d = Path.home() / "Library" / "Logs"
        elif os.name == "nt":
            d = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        else:
            d = Path(os.environ.get("XDG_STATE_HOME",
                                    str(Path.home() / ".local" / "state")))
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "mcabridge-crash.log", "a") as f:
            f.write(f"\n===== {datetime.datetime.now().isoformat()} =====\n")
            traceback.print_exception(exc, file=f)
    except Exception:
        pass


def _run() -> None:
    # Import the package so relative imports inside it resolve correctly, then
    # execute cli.main() as __main__.
    import mcabridge.cli  # noqa: F401  (ensures package context)
    from mcabridge.cli import main

    sys.exit(main())


if __name__ == "__main__":
    try:
        _run()
    except SystemExit:
        raise
    except BaseException as e:      # noqa: BLE001 - log, re-raise for stderr
        _log_crash(e)
        raise
