#!/usr/bin/env bash
# Build a distributable gsbridge release bundle for the CURRENT platform.
#
#   ./scripts/build_release.sh            # build + package into dist/
#   VERSION_OVERRIDE=0.2.1 ./scripts/build_release.sh
#
# Produces (in dist/):
#   Linux   : gsbridge-linux-<arch>.tar.gz  (self-contained folder)
#   macOS   : gsbridge-macos-<arch>.app.tar.gz
#   Windows : gsbridge-win64.zip
#
# The bundle is a single `gsbridge` executable: no args opens the GUI, flags
# run the CLI. Requirements: venv with `pip install -e ".[gui,specutils]" pyinstaller`.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PY:-python3}"
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; fi
VERSION=$($PY -c "import gsbridge; print(gsbridge.__version__)" 2>/dev/null || echo 0.0.0)
VERSION="${VERSION_OVERRIDE:-$VERSION}"

echo "== building with $PY (version $VERSION) =="
"$PY" -m PyInstaller --noconfirm gsbridge.spec

# PyInstaller 6 onedir output: dist/gsbridge-app/  {gsbridge, _internal/}
DIST=dist/gsbridge-$VERSION
rm -rf "$DIST" dist/gsbridge-*.tar.gz dist/gsbridge-*.zip 2>/dev/null || true
cp -a dist/gsbridge-app "$DIST"

case "$(uname -s)" in
Linux)
  ARCH=$(uname -m); [ "$ARCH" = "aarch64" ] && ARCH=arm64
  # bundle PortAudio (+libjack dep) so machines without libportaudio2 work;
  # preload_portaudio() (via rthook) picks it up from _internal/gsbridge_libs
  mkdir -p "$DIST/_internal/gsbridge_libs"
  if [ -d .local/lib ]; then
    cp -an .local/lib/libportaudio.so* .local/lib/libjack.so* \
        "$DIST/_internal/gsbridge_libs/" 2>/dev/null || true
  fi
  # the top-level `gsbridge` binary is directly runnable (finds _internal as a
  # sibling). No-args opens the GUI; flags run the CLI.
  chmod +x "$DIST/gsbridge"
  cp README.md LICENSE "$DIST"/
  ( cd dist && tar czf "gsbridge-linux-$ARCH.tar.gz" "gsbridge-$VERSION" )
  echo "== wrote dist/gsbridge-linux-$ARCH.tar.gz =="
  ;;
Darwin)
  ARCH=$(uname -m); [ "$ARCH" = "arm64" ] && ARCH=arm64 || ARCH=x86_64
  # turn the onedir into a proper .app (Info.plist + MacOS/ layout)
  APP="$DIST/gsbridge.app"
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
  mv "$DIST/_internal" "$APP/Contents/MacOS/_internal"
  cp "$DIST/gsbridge" "$APP/Contents/MacOS/gsbridge"
  cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>GS-Bridge</string>
  <key>CFBundleDisplayName</key><string>GS-Bridge</string>
  <key>CFBundleIdentifier</key><string>com.gsbridge.app</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleExecutable</key><string>gsbridge</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
  cp README.md LICENSE "$APP/Contents/Resources"/
  # ad-hoc sign so Gatekeeper doesn't flat-out reject it (still "unidentified
  # developer" - users right-click→Open, or: xattr -dr com.apple.quarantine)
  codesign --force --deep --sign - "$APP" 2>/dev/null || \
    echo "(codesign unavailable; app will be unsigned)"
  ( cd "$DIST" && tar czf "../gsbridge-macos-$ARCH.app.tar.gz" "gsbridge.app" )
  echo "== wrote dist/gsbridge-macos-$ARCH.app.tar.gz =="
  ;;
MINGW*|MSYS*|CYGWIN*)
  # sounddevice usually ships PortAudio on Windows; bundle a local copy too
  if [ -d .local/lib ]; then
    mkdir -p "$DIST/_internal/gsbridge_libs"
    cp -a .local/lib/*.dll .local/lib/*.bin "$DIST/_internal/gsbridge_libs/" 2>/dev/null || true
  fi
  cp README.md LICENSE "$DIST"/
  ( cd dist && "$PY" -m zipfile -c "gsbridge-win64.zip" "gsbridge-$VERSION" )
  echo "== wrote dist/gsbridge-win64.zip =="
  ;;
*)
  echo "unsupported platform $(uname -s); built folder at $DIST" ;;
esac
