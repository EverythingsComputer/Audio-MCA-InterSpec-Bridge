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
  # turn the onedir into a proper .app (Info.plist + MacOS/ layout).
  # NOTE: PyInstaller >=6's bootloader locates the contents directory at
  # Contents/Frameworks when the executable lives in *.app/Contents/MacOS —
  # so _internal must be MOVED there (renamed), not nested under MacOS/,
  # or the launcher dies with "Failed to load Python shared library
  # …/Contents/Frameworks/libpython…".
  APP="$DIST/mcabridge.app"
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
  mv "$DIST/_internal" "$APP/Contents/Frameworks"
  cp "$DIST/mcabridge" "$APP/Contents/MacOS/mcabridge"
  cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Audio MCA Bridge</string>
  <key>CFBundleDisplayName</key><string>Audio MCA Bridge</string>
  <key>CFBundleIdentifier</key><string>com.mcabridge.app</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleExecutable</key><string>mcabridge</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
  cp README.md LICENSE "$APP/Contents/Resources"/
  # Ad-hoc sign the bundle. macOS reports an unsigned/half-sealed bundle as
  # "damaged" — since v0.2.9 moved contents into Contents/Frameworks the
  # bundle seal (_CodeSignature/CodeResources) is mandatory, and it was
  # missing from EVERY release because the old `codesign ... 2>/dev/null ||`
  # hid a silent failure (xattr "detritus" on files copied by tar/pip is the
  # usual cause; clear xattrs first and keep stderr visible).
  xattr -cr "$APP" 2>/dev/null || true
  if command -v codesign >/dev/null 2>&1; then
    codesign --force --deep --sign - "$APP"
  elif command -v rcodesign >/dev/null 2>&1; then
    # fallback for non-mac hosts; exclude non-bundle dirs that rcodesign
    # would otherwise try to seal as nested bundles (PyInstaller puts plain
    # data dirs like numpy-*.dist-info under Contents/Frameworks).
    rcodesign sign --binary-identifier com.mcabridge.app \
      --exclude 'Contents/Frameworks/*.dist-info' "$APP"
  else
    echo "ERROR: no codesign/rcodesign available; cannot produce a runnable macOS bundle" >&2
    exit 1
  fi
  # HARD GATE: never ship an unsealed bundle again.
  [ -f "$APP/Contents/_CodeSignature/CodeResources" ] || {
    echo "ERROR: bundle signature missing (_CodeSignature/CodeResources) — refusing to package" >&2
    exit 1
  }
  codesign --verify --deep --strict --verbose=2 "$APP" 2>&1 | tail -3 || {
    echo "ERROR: codesign verification failed — refusing to package" >&2; exit 1; }
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
