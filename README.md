# gsbridge

Live gamma spectroscopy for **audio-card MCAs** — Gammaspectacular GS-PRO-V5 /
GS-USB-PRO and friends — bridged to [Sandia's InterSpec](https://github.com/sandialabs/InterSpec)
(and any other spectrum-file tool).

Your USB gamma spectrometer is a smart sound card: it digitises detector pulses
at 48 kHz / 16 bit and leaves the multi-channel analysis to software. gsbridge
is that software — digital pulse processing on your CPU — plus a **live bridge
into InterSpec**: every autosave pushes the current spectrum into the already
running InterSpec window, which repaints in place. Live counts, pause/resume,
lane selection, embedded energy calibration — no fork, no patch, no code
changes to InterSpec (one config toggle, below).

## How the bridge works (and why)

InterSpec is an *analysis* application with no acquisition-driver API. But its
recent builds (2026+, incl. the 1.0.x releases) ship a built-in **MCP API
server** — `load_spectrum_file` and friends, intended for LLM tool use — that
loads spectra directly into a running session. gsbridge drives that official
interface:

```
GS-PRO-V5 ──USB audio──▶ PortAudio blocks ──▶ PulseProcessor (numpy)
                            baseline → trigger → peak
                            → pileup veto → PHA histogram
                                 │  (Pause freezes here)
                    every N s, atomic os.replace
                                 ▼
        gsbridge_live.spe / .spc / .n42 + gsbridge_status.json
              │                                  │
   InterSpec MCP API push                anything else that reads
   (live repaint, chosen lane)           spectra (GammaSpy, python…)
```

Everything lives outside InterSpec; it meets Sandia's app at its own public
interfaces (MCP API, or the desktop shell's file-forwarding fallback), using
Sandia's own SpecUtils library for writing files. What you get:

- **live push** into the running InterSpec window — Foreground / Background /
  Secondary lane of your choice, no open-as prompts, no stale displays
- **pause / resume**: freeze counting to calibrate or inspect in InterSpec,
  then continue accumulating into the same spectrum
- **embedded energy calibration** so pushes keep showing keV (see below)
- all of InterSpec's analysis tools on your live data: peak fitting, nuclide
  ID, DRF/efficiency calibrations, decay calculations, dose rate…
- plain `.spe`/`.spc`/`.n42` files on disk the whole time — readable by any
  tool even with InterSpec closed

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

## One-time InterSpec setup (config only — no code changes)

Live push uses InterSpec's MCP API, which ships **disabled**. Enable it once;
nothing else about InterSpec is touched, and the setting survives updates. Any
InterSpec build that contains the MCP server works (gsbridge was developed and
verified against the Linux `.deb` 1.0.14). If your build predates the MCP API,
everything still works via `--push-mode launch` (see fallbacks).

### Option A — from inside InterSpec (GUI)

1. Launch InterSpec → **Tools menu → LLM Assistant**.
2. Open its settings/configuration panel, tick the **MCP Server** checkbox,
   and set a bearer token (any string except the placeholder
   `INVALID-BEARER-TOKEN`). Save/apply — the MCP server starts live; no
   InterSpec restart needed.
3. Give gsbridge the same token: create `~/.config/gsbridge/mcp.json`
   containing `{"bearer_token": "<your token>"}` (or export
   `GSBRIDGE_MCP_TOKEN`).

### Option B — script it

```bash
python scripts/setup_interspec_mcp.py --token "$(openssl rand -hex 16)"
# then restart InterSpec
```

The script enables `<McpServer><Enabled>true</Enabled>` + your token in
`~/.config/InterSpec/llm_config.xml` (copied from the install template if you
don't have one; existing files are backed up to `.bak`) and writes the matching
`~/.config/gsbridge/mcp.json`. Windows: the config lives under
`%APPDATA%\InterSpec`; macOS under `~/Library/Application Support/InterSpec`.

### Option C — manual XML tweak

Copy `<install>/resources/app/data/llm_config.xml` (Linux `.deb`:
`/opt/InterSpec/resources/app/data/`) to your InterSpec user dir
(`~/.config/InterSpec/` on Linux), then in that copy:

```xml
<McpServer version="0">
  <Enabled>true</Enabled>
  <BearerToken>pick-a…cret</BearerToken>
</McpServer>
```

Restart InterSpec; its console/log shows `=== MCP Interface Enabled ===`.
Then write the token to `~/.config/gsbridge/mcp.json` as above.

### Verify

```bash
gsbridge --check
# OK: InterSpec MCP reachable on port 34903; token accepted.
```

Notes:
- gsbridge **auto-discovers** InterSpec's port from its listening socket — no
  fixed-port config needed. (Do *not* set `HttpPortToServeOn` in
  `InterSpec_app_settings.json`; on the 1.0.14 `.deb` that breaks app startup.)
- The token protects a localhost-only endpoint; still keep it private and
  change it if others use your machine. InterSpec's MCP server also exposes
  analysis tools — gsbridge only ever calls `load_spectrum_file`.

## Usage

### GUI

```bash
gsbridge-gui
```

1. Settings → device match `codec` (the GS appears as *USB Audio Codec*),
   threshold, polarity.
2. **Start InterSpec first** (any file or empty window), then click **Start**
   in gsbridge. With "Push each autosave…" checked (default) every save repaints
   the running InterSpec window in place — that's your live view. Pick the
   Foreground / Background / Secondary lane from the dropdown; no prompts ever.
3. **Pause / Resume** anytime: Pause freezes counting (clocks stop, no pushes)
   so you can calibrate or inspect in InterSpec without the display changing;
   Resume continues accumulating into the same spectrum. Nothing resets.
4. To keep a frozen sample for analysis: stop acquisition and open
   `gsbridge_final.spe` (written once on exit, never pushed over).

### Energy calibration

The "no energy calibration" notice in InterSpec is expected until you calibrate.
Important: each push replaces the foreground spectrum with the file's own
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

### CLI

```bash
gsbridge --list                       # capture devices
gsbridge --check                      # InterSpec MCP readiness
gsbridge                              # live: acquire + MCP push (defaults)
gsbridge --seconds 600 --formats spe,spc,n42
gsbridge --lane Background            # push into the background lane
gsbridge --energy-cal -1.5,0.734      # embed keV calibration
gsbridge --wav recording.wav          # offline replay
```

Headless with fallback push (no MCP):

```bash
interspec &                                   # start the viewer once
gsbridge --push-mode launch --push interspec  # file-forward per autosave
```

### Push modes

| mode | what it does | when to use |
|---|---|---|
| `mcp` (default) | posts each autosave to InterSpec's MCP API; repaints the running window in place, chosen lane, carries calibration | InterSpec 2026+ builds with MCP enabled (setup above) |
| `launch` | runs `<cmd> <file>` (default `interspec`) per autosave; relies on the desktop shell's file forwarding | older InterSpec builds without the MCP API. Loads to Foreground only, and InterSpec's same-UUID memory dedup means later saves may not repaint until you re-open — use it as a viewer handoff, not a live feed |
| `off` | just writes files | other tools / logging only |

If MCP fails mid-run (InterSpec closed, token wrong), gsbridge says so in the
status line and falls back to `launch` for that run; files keep saving either
way.

## Tuning for the GS-PRO-V5

| Control | What | Guidance |
|---|---|---|
| Volume trimpot (D) | preamp gain | K-40 peak ≈ ch 50 of full scale, Cs-137 662 keV ≈ ch 25 (per the GS manual) |
| `--threshold` | trigger level above baseline | start 50–80 ADC counts; raise until noise triggers vanish |
| `--pulse-samples` | analysis window after trigger | ~40 at 48 kHz for the factory 100 µs pulse; shorten with the pulse-length trimpot to cut dead time |
| polarity | GS pulses are positive on the left channel | use `--negative` only if you inverted somewhere |

Energy calibration happens **in InterSpec** (it is better at it than any
acquisition tool): pause, fit the K-40 1460.8 keV peak or a known source, paste
the coefficients into gsbridge as above — the raw channel scale is linear by
construction.

## Features

- real-time digital pulse processing: baseline tracking, edge trigger,
  parabolic peak interpolation, pile-up rejection, non-paralyzable dead time
- outputs `.spe` (ASCII Ortec), `.spc` (binary), `.n42` (N42 2012 XML), `.pcf`
  — atomically replaced every N seconds so readers never see partial files
- `gsbridge_status.json` sidecar (live/real time, rates, rejections) for
  dashboards and other programs
- PySide6 GUI with live log-scale spectrum plot, device/threshold controls,
  pause/resume, lane + push-mode selectors, energy-cal field
- CLI for headless / long runs; WAV replay mode to validate settings offline

## How it works (internals)

Dead time is non-paralyzable with a per-pulse window of
`pulse-samples / rate + 1 µs`. Pile-up veto rejects pulses with another pulse
in the decay tail or noise in the pre-trigger guard. Live saves pin a stable
session UUID; push prefers `.spe` (or `.n42` when an energy calibration is
embedded — SpecUtils' ASCII parser drops hand-written cal lines, binary/N42
round-trip them). Pause gates the processor callback *and* the autosave/push
loop, so InterSpec holds a frozen frame with clocks stopped.

## Limitations & roadmap

- Live push requires InterSpec with the MCP API (2026+/1.0.x builds; verified
  on the Linux `.deb` 1.0.14). Older builds: `--push-mode launch` works as a
  handoff viewer but not a live feed (InterSpec's file-model dedup serves stale
  copies for same-UUID files).
- If InterSpec is *not* running, MCP pushes fail until it starts (gsbridge
  keeps acquiring and saving regardless; start InterSpec and pushes resume on
  the next autosave).
- The MCP endpoint also exposes InterSpec's analysis tools to localhost;
  gsbridge never calls them. Keep your bearer token private.
- Coincidence (right-channel) mode: not yet, though the capture layer already
  supports stereo.
- Tested against synthetic pulses + live silent-device runs; hardware QA with a
  real GS-PRO-V5 in progress — see `tests/`.

## License

MIT. InterSpec and SpecUtils are Sandia National Labs (LGPL-2.1); gsbridge uses
only their public file formats, published Python bindings, and the MCP API that
Sandia ships (disabled by default), and is not affiliated with or endorsed by
Sandia. No InterSpec sources are modified — enabling the bridge is a user
config setting, exactly as Sandia intends it to be used.
