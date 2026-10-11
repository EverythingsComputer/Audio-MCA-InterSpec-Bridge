# gsbridge

Live gamma spectroscopy for **audio-card MCAs** — Gammaspectacular GS-PRO-V5 /
GS-USB-PRO and friends — bridged to [Sandia's InterSpec](https://github.com/sandialabs/InterSpec)
(and any other spectrum-file tool).

Your USB gamma spectrometer is a smart sound card: it digitises detector pulses
at 48 kHz / 16 bit and leaves the multi-channel analysis to software. gsbridge
is that software — digital pulse processing on your CPU — plus a **live push
bridge into InterSpec**: every autosave hands the freshly-written spectrum file
to InterSpec's desktop shell, which forwards it to the already-running window,
re-parses it from disk, and repaints. Live counts in InterSpec, no fork, no
patch.

## Why a file bridge?

InterSpec (open source, LGPL) has no acquisition plugin API: it is an analysis
application. gsbridge therefore keeps 100 % of its own code outside InterSpec —
no fork, no patch — and meets it at the file format level, using Sandia's own
SpecUtils library for writing. What you get:

- live push into the running InterSpec window (each autosave repaints it via
  InterSpec's own single-instance file-forwarding IPC; verified on Linux with
  the .deb build) — or plain re-open of `gsbridge_live.spe` if you prefer
- all of InterSpec's analysis tools on your live data: peak fitting, nuclide ID,
  DRF/efficiency calibrations, decay calculations, dose rate…
- the same files readable by GammaSpy, Spectrum Studio,ROOT-free python, etc.

## Features

- real-time digital pulse processing: baseline tracking, edge trigger,
  parabolic peak interpolation, pile-up rejection, non-paralyzable dead time
- outputs `.spe` (ASCII Ortec), `.spc` (binary), `.n42` (N42 2012 XML), `.pcf`
  — atomically replaced every N seconds so readers never see partial files
- `gsbridge_status.json` sidecar (live/real time, rates, rejections) for
  dashboards and other programs
- PySide6 GUI with live log-scale spectrum plot and device/threshold controls
- CLI for headless / long runs
- WAV replay mode: validate settings on a recorded file before running live

## Install

```bash
git clone https://github.com/<you>/gsbridge && cd gsbridge
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[gui,specutils]"
```

PortAudio (used by `sounddevice`) needs the system library:

```bash
sudo apt install libportaudio2      # Debian/Ubuntu
# Fedora: sudo dnf install portaudio
```

Without root you can unpack the distro package into `.local/lib` (see
`scripts/bundle_portaudio.sh`) — gsbridge auto-loads it as a fallback.

## Usage

### GUI

```bash
gsbridge-gui
```

1. Settings → device match `codec` (the GS appears as *USB Audio Codec*),
   threshold, polarity.
2. **Start InterSpec first** (any file or empty window), then click **Start** in
   gsbridge. With "Push each autosave…" checked (default), every save repaints
   the running InterSpec window with current counts — that's your live view.
3. To keep a frozen sample for analysis: stop acquisition and open
   `gsbridge_final.spe` (written once on exit, never pushed over).

Headless / scripted:

```bash
interspec &            # start the viewer once
gsbridge --push interspec --formats spe,spc,n42
```

(`--push xdg-open` also works once InterSpec owns the `.spe` mime type.)

### CLI

```bash
gsbridge --list                       # capture devices
gsbridge --seconds 600 --formats spe,spc,n42
gsbridge --wav recording.wav          # offline replay
```

## Tuning for the GS-PRO-V5

| Control | What | Guidance |
|---|---|---|
| Volume trimpot (D) | preamp gain | K-40 peak ≈ ch 50 of full scale, Cs-137 662 keV ≈ ch 25 (per the GS manual) |
| `--threshold` | trigger level above baseline | start 50–80 ADC counts; raise until noise triggers vanish |
| `--pulse-samples` | analysis window after trigger | ~40 at 48 kHz for the factory 100 µs pulse; shorten with the pulse-length trimpot to cut dead time |
| polarity | GS pulses are positive on the left channel | use `--negative` only if you inverted somewhere |

Energy calibration happens **in InterSpec** (it is better at it than any
acquisition tool): open a spectrum, fit the K-40 1460.8 keV peak or a known
source, and save the calibration into your analysis — the raw channel scale is
linear by construction.

## How it works

```
GS-PRO-V5 ──USB audio──▶ PortAudio blocks ──▶ PulseProcessor (numpy)
                                               baseline → trigger → peak
                                               → pileup veto → PHA histogram
                                                    │
                              every N s (atomic os.replace)
                                                    ▼
              gsbridge_live.spe / .spc / .n42 + gsbridge_status.json
                    │                            │
              InterSpec (re-open file)    anything else that reads spectra
```

Dead time is non-paralyzable with a per-pulse window of
`pulse-samples / rate + 1 µs`. Pile-up veto rejects pulses with another pulse
in the decay tail or noise in the pre-trigger guard.

## Limitations & roadmap

- Push relies on InterSpec's desktop shell forwarding a file argument to its
  running session (single-instance IPC; verified with the Linux .deb/Electron
  build). If InterSpec is *not* already running, each push cold-launches it —
  start InterSpec once before acquiring. True in-session streaming would need
  Sandia to expose an acquisition API; this uses only their public shell path.
- The Foreground/Background/Secondary "how to open?" prompt is suppressed for
  pushed live files by pinning a stable UUID inside `gsbridge_live.spe`/`.n42`
  (InterSpec treats same-UUID pushes as updates of the loaded spectrum). Binary
  `.spc` has no UUID header field — keep `.spe` or `.n42` in your save formats
  when using push.
- Coincidence (right-channel) mode: not yet, though the capture layer already
  supports stereo.
- Tested against synthetic pulses + live silent-device runs; hardware QA with a
  real GS-PRO-V5 in progress — see `tests/`.

## License

MIT. InterSpec and SpecUtils are Sandia National Labs (LGPL-2.1); gsbridge uses
only their public file formats and published Python bindings and is not
affiliated with or endorsed by Sandia.
