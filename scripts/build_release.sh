#!/usr/bin/env bash
# Build a distributable mcabridge release bundle for the CURRENT platform.
#
#   ./scripts/build_release.sh            # build + package into dist/
#   VERSION_OVERRIDE=0.2.1 ./scripts/build_release.sh
#
# Produces (in dist/):
#   Linux   : mcabridge-linux-<arch>.tar.gz  (self-contained folder)
#   macOS   : mcabridge-macos-<arch>.app.tar.gz
#   Windows : mcabridge-win64.zip
#
# The bundle is a single `mcabridge` executable: no args opens the GUI, flags
# run the CLI. Requirements: venv with `pip install -e ".[gui,specutils]" pyinstaller`.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PY:-python3}"
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; fi
# git-bash on Windows has no python3 alias; fall back to `python`
if ! command -v "$PY" >/dev/null 2>&1; then PY=python; fi
VERSION=$($PY -c "import mcabridge; print(mcabridge.__version__)" 2>/dev/null || echo 0.0.0)
VERSION="${VERSION_OVERRIDE:-$VERSION}"

echo "== building with $PY (version $VERSION) =="
"$PY" -m PyInstaller --noconfirm mcabridge.spec

# PyInstaller 6 onedir output: dist/mcabridge-app/  {mcabridge, _internal/}
DIST=dist/mcabridge-$VERSION
rm -rf "$DIST" dist/mcabridge-*.tar.gz dist/mcabridge-*.zip 2>/dev/null || true
cp -a dist/mcabridge-app "$DIST"

case "$(uname -s)" in
Linux)
  ARCH=$(uname -m); [ "$ARCH" = "aarch64" ] && ARCH=arm64
  # bundle PortAudio (+libjack dep) so machines without libportaudio2 work;
  # preload_portaudio() (via rthook) picks it up from _internal/mcabridge_libs
  mkdir -p "$DIST/_internal/mcabridge_libs"
  if [ -d .local/lib ]; then
    cp -an .local/lib/libportaudio.so* .local/lib/libjack.so* \
        "$DIST/_internal/mcabridge_libs/" 2>/dev/null || true
  fi
  # the top-level `mcabridge` binary is directly runnable (finds _internal as a
  # sibling). No-args opens the GUI; flags run the CLI.
  chmod +x "$DIST/mcabridge"
  cp README.md LICENSE "$DIST"/
  ( cd dist && tar czf "mcabridge-linux-$ARCH.tar.gz" "mcabridge-$VERSION" )
  echo "== wrote dist/mcabridge-linux-$ARCH.tar.gz =="
  ;;
Darwin)
  ARCH=$(uname -m); [ "$ARCH" = "arm64" ] && ARCH=arm64 || ARCH=x86_64
  # The spec's BUNDLE target built dist/mcabridge.app with Apple-conformant
  # layout (data under Contents/Resources, dotted dir names relocated) — the
  # only layout codesign can seal. Hand-assembling an onedir into an .app put
  # e.g. numpy-2.5.4.dist-info under Contents/Frameworks, which Apple's
  # bundle format forbids: `codesign` failed with "bundle format unrecognized,
  # invalid, or unsuitable", no _CodeSignature/CodeResources was ever created
  # (the failure was hidden behind 2>/dev/null), and macOS opened the result
  # as "damaged".
  APPSRC=dist/mcabridge.app
  [ -d "$APPSRC" ] || { echo "ERROR: spec BUNDLE target did not produce $APPSRC" >&2; exit 1; }
  rm -rf "$DIST"; mkdir -p "$DIST"
  cp -a "$APPSRC" "$DIST/mcabridge.app"
  APP="$DIST/mcabridge.app"
  cp README.md LICENSE "$APP/Contents/Resources"/
  # Clear xattrs: stale com.apple.cs.* attributes ("detritus" from pip/tar)
  # make codesign refuse files. Non-fatal exit (files may have no xattrs).
  xattr -cr "$APP" 2>/dev/null || true
  chmod +x "$APP/Contents/MacOS/mcabridge"
  echo "== signing bundle =="
  # stderr kept visible and annotated on failure (v0.2.1–v0.2.9 hid it).
  if ! codesign --force --deep --sign - "$APP" 2> codesign_err.txt; then
    cat codesign_err.txt
    python3 -c "import urllib.parse; print('::error::CODESIGN_LOG='+urllib.parse.quote(open('codesign_err.txt').read()))" || true
    exit 1
  fi
  cat codesign_err.txt
  # HARD GATE: never ship an unsealed bundle again.
  [ -f "$APP/Contents/_CodeSignature/CodeResources" ] || {
    echo "ERROR: bundle signature missing (_CodeSignature/CodeResources) — refusing to package" >&2
    exit 1
  }
  codesign --verify --deep --strict --verbose=2 "$APP"
  ( cd "$DIST" && tar czf "../mcabridge-macos-$ARCH.app.tar.gz" "mcabridge.app" )
  echo "== wrote dist/mcabridge-macos-$ARCH.app.tar.gz =="
  ;;
MINGW*|MSYS*|CYGWIN*)
  # sounddevice usually ships PortAudio on Windows; bundle a local copy too
  if [ -d .local/lib ]; then
    mkdir -p "$DIST/_internal/mcabridge_libs"
    cp -a .local/lib/*.dll .local/lib/*.bin "$DIST/_internal/mcabridge_libs/" 2>/dev/null || true
  fi
  cp README.md LICENSE "$DIST"/
  # zip with forward-slash entry names (python -m zipfile keeps Windows
  # backslashes, which some extractors mishandle) and no 260-char path limit
  # (PowerShell Compress-Archive chokes on PySide6's deep _internal trees).
  "$PY" - "$DIST" "dist/mcabridge-win64.zip" <<'ZIPHELPER'
import os, sys, zipfile
src, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(src):
        for f in files:
            p = os.path.join(root, f)
            z.write(p, os.path.relpath(p, os.path.dirname(src)).replace(os.sep, "/"))
print("zipped", out)
ZIPHELPER
  echo "== wrote dist/mcabridge-win64.zip =="
  ;;
*)
  echo "unsupported platform $(uname -s); built folder at $DIST" ;;
esac
