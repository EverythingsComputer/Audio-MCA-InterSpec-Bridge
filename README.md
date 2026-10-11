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
   gsbridge. With "Push each autosave…" checked (default) every save repaints
   the running InterSpec window in place — that's your live view. Pick the
   Foreground / Background / Secondary lane from the dropdown; no prompts ever.
3. **Pause / Resume** anytime: Pause freezes counting (clocks stop, no pushes)
   so you can calibrate or inspect in InterSpec without the display changing;
   Resume continues accumulating into the same spectrum. Nothing resets.
4. To keep a frozen sample for analysis: stop acquisition and open
   `gsbridge_final.spe` (written once on exit, never pushed over).

### Energy calibration

The "no energy calibration" notice in InterSpec is expected until you calibrate.
Important: each MCP push replaces the foreground spectrum with the file's own
calibration, so a calibration fitted *inside InterSpec* will not survive the
next autosave. gsbridge therefore embeds your coefficients into every file it
writes — once set, pushes carry the calibration and nothing resets:

1. Press **Pause** in gsbridge (spectrum freezes, InterSpec stops updating).
2. In InterSpec: Energy Calibration tool → fit peaks → copy the polynomial
   coefficients (keV).
3. gsbridge Settings → *Energy cal (keV)* → paste as `c0,c1[,c2,c3]` (works
   while paused — takes effect on Resume's next autosave).
4. **Resume.** Pushes now carry the calibration; the warning is gone and every
   future run can reuse it (also via CLI: `--energy-cal -1.5,0.734`).

Headless / scripted:

```bash
interspec &            # start the viewer once
gsbridge --formats spe,spc,n42          # MCP push is the default
gsbridge --lane Background              # load into background instead
gsbridge --push-mode launch --push interspec   # old file-forward fallback
```

### One-time InterSpec setup for live (MCP) push

InterSpec ships a built-in API server, disabled by default. Enable it once:

1. Copy `data/llm_config.xml` from the InterSpec install directory
   (e.g. `/opt/InterSpec/resources/app/data/llm_config.xml`) to
   `~/.config/InterSpec/llm_config.xml`.
2. In that copy, inside `<McpServer>`, set `<Enabled>true</Enabled>` and
   replace `INVALID-BEARER-TOKEN` with a local token of your choice.
3. Restart InterSpec. The log should print `=== MCP Interface Enabled ===`.
4. Tell gsbridge the token: put `{"bearer_token": "<your token>"}` in
   `~/.config/gsbridge/mcp.json` (or export `GSBRIDGE_MCP_TOKEN`).

gsbridge auto-discovers InterSpec's port from its listening socket — no fixed
port config needed. (Do *not* set `HttpPortToServeOn` in
`InterSpec_app_settings.json` to work around discovery; on the 1.0.14 .deb it
prevents the app from finishing startup.)

If MCP is unavailable (disabled, or an older InterSpec build), gsbridge falls
back once per run to the launch-cmd push and says so in the status line.

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

- Live push uses InterSpec's built-in MCP API (`load_spectrum_file`), which
  updates a running session in place, honors the Foreground/Background/
  Secondary lane, and never prompts. It requires the one-time enable step
  above (InterSpec ≥ the 2026 builds; verified on the 1.0.14 .deb). The older
  launch/file-forward fallback (`--push-mode launch`) still exists but is
  degraded: InterSpec's file-model dedup serves stale in-memory copies for
  same-UUID files, so that path only repaints reliably after the first load.
- If InterSpec is *not* running, MCP pushes fail until it starts (gsbridge
  keeps acquiring and saving regardless; start InterSpec and pushes resume on
  the next autosave).
- Coincidence (right-channel) mode: not yet, though the capture layer already
  supports stereo.
- Tested against synthetic pulses + live silent-device runs; hardware QA with a
  real GS-PRO-V5 in progress — see `tests/`.

## License

MIT. InterSpec and SpecUtils are Sandia National Labs (LGPL-2.1); gsbridge uses
only their public file formats and published Python bindings and is not
affiliated with or endorsed by Sandia.
