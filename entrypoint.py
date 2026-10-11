"""PyInstaller entry shim for gsbridge.

A frozen script loses its package context, so ``from .dsp import ...`` inside
gsbridge.cli fails. This shim restores it by importing the real package module
and delegating to its main(). Build with:  pyinstaller --noconfirm gsbridge.spec
(spec points Analysis at this file).
"""
import runpy
import sys


def _run() -> None:
    # Import the package so relative imports inside it resolve correctly, then
    # execute cli.main() as __main__.
    import gsbridge.cli  # noqa: F401  (ensures package context)
    from gsbridge.cli import main

    sys.exit(main())


if __name__ == "__main__":
    _run()
