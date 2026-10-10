# gsbridge

Live gamma spectroscopy for **audio-card MCAs** — Gammaspectacular GS-PRO-V5 /
GS-USB-PRO and friends — bridged to [Sandia's InterSpec](https://github.com/sandialabs/InterSpec)
(and any other spectrum-file tool).

Your USB gamma spectrometer is a smart sound card: it digitises detector pulses
at 48 kHz / 16 bit and leaves the multi-channel analysis to software. gsbridge
is that software — digital pulse processing on your CPU — plus an **InterSpec
live-file bridge**: it continuously writes standard spectrum files
(`.spe`, `.spc`, `.n42`, `.pcf`) that you open once in InterSpec and refresh
with the **Reload** button.

## Why a file bridge?

InterSpec (open source, LGPL) has no acquisition plugin API: it is an analysis
application. gsbridge therefore keeps 100 % of its own code outside InterSpec —
no fork, no patch — and meets it at the file format level, using Sandia's own
SpecUtils library for writing. What you get:

- live counts streaming into InterSpec (press ⟳ Reload, or reopen)
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
2. **Start**. The spectrum forms in the plot; files land in
   `~/Documents/GS-Bridge-output/`.
3. In InterSpec: File → Open `gsbridge_live.spe`, then hit **⟳ Reload**
   whenever you want the current data (autosave interval defaults to 5 s).

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
              InterSpec (⟳ Reload)      anything else that reads spectra
```

Dead time is non-paralyzable with a per-pulse window of
`pulse-samples / rate + 1 µs`. Pile-up veto rejects pulses with another pulse
in the decay tail or noise in the pre-trigger guard.

## Limitations & roadmap

- Reload in InterSpec is manual (one click). InterSpec's web frontend talks to
  its embedded server over HTTP — an auto-refresh proxy is on the roadmap but
  requires reverse-engineering a private protocol; file polling keeps this
  project stable across InterSpec releases.
- Coincidence (right-channel) mode: not yet, though the capture layer already
  supports stereo.
- Tested against synthetic pulses + live silent-device runs; hardware QA with a
  real GS-PRO-V5 in progress — see `tests/`.

## License

MIT. InterSpec and SpecUtils are Sandia National Labs (LGPL-2.1); gsbridge uses
only their public file formats and published Python bindings and is not
affiliated with or endorsed by Sandia.
