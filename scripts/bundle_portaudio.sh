#!/usr/bin/env bash
# Bundle PortAudio (+ libjack dep) into .local/lib for no-root installs.
# Debian/Ubuntu only (uses apt-get download, no sudo needed).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .local/lib
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
for pkg in libportaudio2 libjack-jackd2-0; do
  ( cd "$tmp" && apt-get download "$pkg" )
  ( cd "$tmp" && dpkg-deb -x "${pkg}"_*.deb extracted )
  cp -a "$tmp"/extracted/usr/lib/*/lib{portaudio,jack}*.so* .local/lib/ 2>/dev/null || true
done
cd .local/lib
[ -e libportaudio.so.2 ] && ln -sf libportaudio.so.2.0.0 libportaudio.so || true
echo "bundled:"; ls -la
echo "mcabridge auto-loads this directory at startup (no LD_LIBRARY_PATH needed)."
