"""PyInstaller entry shim for mcabridge.

A frozen script loses its package context, so ``from .dsp import ...`` inside
mcabridge.cli fails. This shim restores it by importing the real package module
and delegating to its main(). Build with:  pyinstaller --noconfirm mcabridge.spec
(spec points Analysis at this file).
"""
import runpy
import sys


def _run() -> None:
    # Import the package so relative imports inside it resolve correctly, then
    # execute cli.main() as __main__.
    import mcabridge.cli  # noqa: F401  (ensures package context)
    from mcabridge.cli import main

    sys.exit(main())


if __name__ == "__main__":
    _run()
