# Audio MCA → InterSpec Bridge

*Package and command: `mcabridge` (formerly gsbridge).*

Live gamma spectroscopy for **audio-card MCAs** — Gammaspectacular GS-PRO-V5 /
GS-USB-PRO and similar devices — bridged to [Sandia's
InterSpec](https://github.com/sandialabs/InterSpec).

A USB gamma spectrometer is a smart sound card: it digitises detector pulses at
48 kHz / 16 bit and leaves the multi-channel analysis to software. mcabridge is
that software — digital pulse processing on your CPU — plus a **live bridge
into InterSpec**: every autosave pushes the current spectrum into the running
InterSpec window, which repaints in place. Live counts, pause/resume, lane
selection, embedded energy calibration — no fork, no patch, and no code changes
to InterSpec (one config toggle, see [setup](#one-time-interspec-setup)).

InterSpec is the supported and tested target; standard `.spe`/`.spc`/`.n42`
files are also written to disk throughout.

## Quick start (prebuilt bundle)

No Python required. Download a bundle from [GitHub
Releases](https://github.com/EverythingsComputer/Audio-MCA-InterSpec-Bridge/releases):

| platform | archive |
|---|---|
| Windows x64 | `mcabridge-win64.zip` |
| Linux x86_64 | `mcabridge-linux-x86_64.tar.gz` |
| macOS (Apple Silicon / Intel) | `mcabridge-macos-arm64.app.tar.gz` / `...x86_64.app.tar.gz` |

**Prereqs:** [InterSpec](https://github.com/sandialabs/InterSpec/releases)
1.0.x — a build whose **Tools → LLM Assistant** menu shows an MCP Server
option (verified: Linux `.deb` 1.0.14, Windows x64). On Windows download the
InterSpec *Windows x64* build; if your InterSpec lacks the MCP option, get a
newer build.

Each bundle is a single `mcabridge` executable (`mcabridge.exe` on Windows):
**run it with no arguments to open the GUI**; pass flags for headless CLI use.
Unpack anywhere. On macOS the first launch needs right-click → Open (the app
is ad-hoc signed, not notarized).

1. **Close InterSpec.** Run the one-time token setup:

   ```
   ./mcabridge --setup-mcp
   ```

   Or open the GUI and click **MCP token… → Generate → Configure both** —
   same result, fully in the GUI.

2. **Start InterSpec**, then start mcabridge (no arguments = GUI). Click
   **Start**: every autosave repaints the InterSpec window in place.
   **Pause** freezes counting so you can calibrate or inspect; **Resume**
   continues into the same spectrum.

3. Optional: paste energy-calibration coefficients into Settings → *Energy cal
   (keV)* so pushes carry keV ([details](#energy-calibration)).

To verify the bridge at any time: `mcabridge --check` should report the
InterSpec MCP endpoint reachable and the token accepted.

## Quick start (from source, Linux / macOS)

**Prereqs:** Python ≥ 3.10, InterSpec as above, detector plugged in.

```bash
git clone https://github.com/EverythingsComputer/Audio-MCA-InterSpec-Bridge.git
cd Audio-MCA-InterSpec-Bridge
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[gui,specutils]"
#    Linux only, if PortAudio is missing:  sudo apt install libportaudio2

mcabridge --setup-mcp     # one-time; run with InterSpec CLOSED, restart it after
mcabridge --check         # OK: InterSpec MCP reachable on port NNNNN; token accepted.
mcabridge-gui             # start InterSpec first; or headless: mcabridge
```

## Quick start (from source, Windows PowerShell)

No PortAudio or Visual C++ setup needed — the Python wheels bundle everything.

**Prereqs:** [Python 3.10+](https://www.python.org/downloads/) (check *Add to
PATH*), [Git for Windows](https://git-scm.com/download/win), InterSpec as above.

```powershell
# 1. Check Python + Git are on PATH (py ships with the python.org installer):
py --version
git --version

# 2. Clone and install into an isolated venv:
cd $HOME
git clone https://github.com/EverythingsComputer/Audio-MCA-InterSpec-Bridge.git
cd "$HOME\Audio-MCA-InterSpec-Bridge"
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[gui,specutils]"

# 3. One-time setup with InterSpec CLOSED (generates a token and configures
#    both sides), then reopen InterSpec:
.\.venv\Scripts\mcabridge.exe --setup-mcp
.\.venv\Scripts\mcabridge.exe --check

# 4. Run:
.\.venv\Scripts\mcabridge.exe --list     # the GS usually appears as "USB Audio Codec"
.\.venv\Scripts\mcabridge-gui.exe        # Settings → pick the device → Start
```

Keep the token private — don't paste it into chats or issue reports.

## How the bridge works

InterSpec is an *analysis* application with no acquisition-driver API. Recent
builds (2026+, incl. 1.0.x) ship a built-in **MCP API server** — a
`load_spectrum_file` tool, intended for LLM tool use, that loads spectra
directly into a running session. mcabridge drives that official interface:

```
GS-PRO-V5 ──USB audio──▶ PortAudio blocks ──▶ PulseProcessor (numpy)
                            baseline → trigger → peak
                            → pileup veto → PHA histogram
                                 │  (Pause freezes here)
                    every N s, atomic os.replace
                                 ▼
        mcabridge_live.spe / .spc / .n42 + mcabridge_status.json
              │                                  │
   InterSpec MCP API push                standard spectrum files
   (live repaint, chosen lane)           on disk for later analysis
```

Everything lives outside InterSpec: it meets Sandia's app at its own public
interfaces (the MCP API, or the desktop shell's file-forwarding fallback) and
uses Sandia's SpecUtils library for writing files. What you get:

- **live push** into the running InterSpec window — Foreground / Background /
  Secondary lane of your choice, no open-as prompts, no stale displays
- **pause / resume**: freeze counting to calibrate or inspect in InterSpec,
  then continue accumulating into the same spectrum
- **embedded energy calibration** so pushes keep showing keV
  ([details](#energy-calibration))
- all of InterSpec's analysis tools on live data: peak fitting, nuclide ID,
  DRF/efficiency calibrations, decay calculations, dose rate

## Install

```bash
git clone https://github.com/EverythingsComputer/Audio-MCA-InterSpec-Bridge.git
cd Audio-MCA-InterSpec-Bridge
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[gui,specutils]"
```

This installs the `mcabridge` and `mcabridge-gui` entry points (`mcabridge`
with no arguments also opens the GUI). Windows: use the PowerShell steps in
[Quick start (from source, Windows)](#quick-start-from-source-windows-powershell).

PortAudio (used by `sounddevice`) needs the system library on Linux:

```bash
sudo apt install libportaudio2      # Debian/Ubuntu
# Fedora: sudo dnf install portaudio
```

Without root you can unpack the distro package into `.local/lib` (see
`scripts/bundle_portaudio.sh`) — mcabridge auto-loads it as a fallback. The
prebuilt Linux bundle already includes PortAudio. On Windows and macOS nothing
extra is needed: the `sounddevice` wheel ships PortAudio itself.

## One-time InterSpec setup

Live push uses InterSpec's MCP API, which ships **disabled**. Enable it once;
nothing else about InterSpec is touched, and the setting survives updates. If
your InterSpec build predates the MCP API, everything still works via
`--push-mode launch` (see [Push modes](#push-modes)).

### Option A — mcabridge GUI (recommended)

Close InterSpec, then open `mcabridge-gui` and click **MCP token…** on the
push row:

1. **Generate** — creates a fresh random token (Show/Copy buttons reveal it).
2. **Configure both** — writes the token + `<Enabled>true</Enabled>` into
   InterSpec's `llm_config.xml` *and* saves it for mcabridge in one click.
   Restart InterSpec afterwards.
3. Alternatively use InterSpec's own switch: **Save for mcabridge**, reopen
   InterSpec → Tools → LLM Assistant → MCP Server → paste the same token →
   Save (no restart needed there).
4. **Test connection** runs the same check as `mcabridge --check`.

### Option B — CLI one-shot

```bash
mcabridge --setup-mcp          # with InterSpec CLOSED; generates a token,
                               # configures both sides, prints the token
# then restart InterSpec and:
mcabridge --check
```

Related commands: `mcabridge --gen-token` prints a new token without saving;
`mcabridge --set-token <token>` (or `--set-token -` to read stdin) saves the
mcabridge side only — use it when InterSpec's token is set through InterSpec's
own GUI. `scripts/setup_interspec_mcp.py` is an equivalent standalone script
for source checkouts.

Both paths enable `<McpServer><Enabled>true</Enabled>` + the token in
`~/.config/InterSpec/llm_config.xml` (copied from the install template if
absent; existing files are backed up to `.bak`) and write the matching
`~/.config/mcabridge/mcp.json`. Windows: `%APPDATA%\InterSpec` /
`%APPDATA%\mcabridge`; macOS: `~/Library/Application Support/...`.

### Option C — InterSpec GUI + token handoff

1. Launch InterSpec → **Tools menu → LLM Assistant** → settings panel.
2. Tick **MCP Server**, set a bearer token (any string except the placeholder
   `INVALID-BEARER-TOKEN`), Save/apply — the MCP server starts live, no
   InterSpec restart needed.
3. Give mcabridge the same token: **MCP token… → Save for mcabridge** in the
   GUI, or `mcabridge --set-token <token>`. This writes
   `~/.config/mcabridge/mcp.json` containing `{"bearer_token": "<token>"}`.
   The environment variable `MCABRIDGE_MCP_TOKEN` also works.

### Option D — manual XML edit

Copy `<install>/resources/app/data/llm_config.xml` (Linux `.deb`:
`/opt/InterSpec/resources/app/data/`) to the InterSpec user dir
(`~/.config/InterSpec/` on Linux, `%APPDATA%\InterSpec\` on Windows), then in
that copy:

```xml
<McpServer version="0">
  <Enabled>true</Enabled>
  <BearerToken>pick-a…cret</BearerToken>
</McpServer>
```

Restart InterSpec; its console/log shows `=== MCP Interface Enabled ===`.
Then give mcabridge the token as in Option C.

### Notes

- mcabridge **auto-discovers** InterSpec's port from its listening socket — no
  fixed-port config needed. (Do *not* set `HttpPortToServeOn` in
  `InterSpec_app_settings.json`; on the 1.0.14 `.deb` that breaks app startup.)
- The token protects a localhost-only endpoint; keep it private and change it
  if others use the machine. InterSpec's MCP server also exposes analysis
  tools — mcabridge only ever calls `load_spectrum_file`.

## Usage

### GUI

```bash
mcabridge-gui          # or: mcabridge with no arguments
```

1. Settings → device match `codec` (the GS appears as *USB Audio Codec*),
   threshold, polarity.
2. **Start InterSpec first** (any file or empty window), then click **Start**
   in mcabridge. With "Push each autosave…" checked (default), every save
   repaints the running InterSpec window in place. Pick the Foreground /
   Background / Secondary lane from the dropdown.
3. **Pause / Resume** anytime: Pause freezes counting (clocks stop, no pushes)
   so calibration or inspection in InterSpec isn't disturbed; Resume continues
   accumulating into the same spectrum. Nothing resets.
4. To keep a frozen sample for analysis: stop acquisition and open
   `mcabridge_final.spe` (written once on exit, never pushed over).

### Energy calibration

The "no energy calibration" notice in InterSpec is expected until you
calibrate. Note that each push replaces the foreground spectrum with the
file's own calibration, so a calibration fitted *inside InterSpec* does not
survive the next autosave. mcabridge embeds your coefficients into every file
it writes — once set, pushes carry the calibration and nothing resets:

1. Press **Pause** in mcabridge (spectrum freezes, InterSpec stops updating).
2. In InterSpec: Energy Calibration tool → fit peaks → copy the polynomial
   coefficients (keV).
3. mcabridge Settings → *Energy cal (keV)* → paste as `c0,c1[,c2,c3]` (works
   while paused — takes effect on Resume's next autosave).
4. **Resume.** Pushes now carry the calibration and future runs can reuse it
   (CLI: `--energy-cal -1.5,0.734`).

Even with a valid embedded calibration, InterSpec shows a "no energy
calibration for the selected samples" toast on each push unless the MCP call
names the sample to display; mcabridge always sends `sampleNumbers: [1]` (its
files are single-measurement), which suppresses it.

### CLI

```bash
mcabridge --list                       # capture devices
mcabridge --check                      # InterSpec MCP readiness
mcabridge --setup-mcp                  # one-shot token + config for both sides
mcabridge --gen-token                  # print a fresh bearer token
mcabridge --set-token TOKEN            # save the bridge's bearer token
mcabridge                              # live: acquire + MCP push (defaults)
mcabridge --seconds 600 --formats spe,spc,n42
mcabridge --lane Background            # push into the background lane
mcabridge --energy-cal -1.5,0.734      # embed keV calibration
mcabridge --wav recording.wav          # offline replay
```

On Windows (source install) prefix with `.\.venv\Scripts\` and add `.exe`,
e.g. `.\.venv\Scripts\mcabridge.exe --check`. For the prebuilt bundle, run the
executable from its folder instead.

### Push modes

| mode | what it does | when to use |
|---|---|---|
| `mcp` (default) | posts each autosave to InterSpec's MCP API; repaints the running window in place, chosen lane, carries calibration | InterSpec 2026+ builds with MCP enabled. **The live feed.** |
| `launch` | runs `<cmd> <file>` (default `interspec`) per autosave via the desktop shell's file forwarding | older InterSpec builds without the MCP API — as a **one-time handoff** only. It loads a file into an *empty* InterSpec and re-renders a file already displayed (same path+UUID, once per session); repeated pushes of the same live file are ignored by InterSpec's file model, and a new file each cycle raises an open-as prompt. Foreground lane only. Not a live feed. |
| `off` | just writes files | logging / manual use |

If MCP fails mid-run (InterSpec closed, token wrong), mcabridge says so in the
status line and falls back to `launch` for that run; files keep saving either
way.

## Tuning for the GS-PRO-V5

| Control | What | Guidance |
|---|---|---|
| Volume trimpot (D) | preamp gain | K-40 peak ≈ ch 50 of full scale, Cs-137 662 keV ≈ ch 25 (per the GS manual) |
| `--threshold` | trigger level above baseline | start 50–80 ADC counts; raise until noise triggers vanish |
| `--pulse-samples` | analysis window after trigger | ~40 at 48 kHz for the factory 100 µs pulse; shorten with the pulse-length trimpot to cut dead time |
| polarity | GS pulses are positive on the left channel | use `--negative` only if inverted somewhere upstream |

Energy calibration happens **in InterSpec**: pause, fit the K-40 1460.8 keV
peak or a known source, paste the coefficients into mcabridge as above — the
raw channel scale is linear by construction.

## Features

- real-time digital pulse processing: baseline tracking, edge trigger,
  parabolic peak interpolation, pile-up rejection, non-paralyzable dead time
- outputs `.spe` (ASCII Ortec), `.spc` (binary), `.n42` (N42 2012 XML), `.pcf`
  — atomically replaced every N seconds so readers never see partial files
- `mcabridge_status.json` sidecar (live/real time, rates, rejections) for
  dashboards and other programs
- PySide6 GUI with live log-scale spectrum plot, device/threshold controls,
  pause/resume, lane + push-mode selectors, energy-cal field, MCP token setup
- CLI for headless / long runs; WAV replay mode to validate settings offline

## How it works (internals)

Dead time is non-paralyzable with a per-pulse window of
`pulse-samples / rate + 1 µs`. The pile-up veto rejects pulses with another
pulse in the decay tail or noise in the pre-trigger guard. Live saves pin a
stable session UUID; push prefers `.spe` (or `.n42` when an energy calibration
is embedded — SpecUtils' ASCII parser drops hand-written cal lines, binary/N42
round-trip them). Pause gates the processor callback *and* the autosave/push
loop, so InterSpec holds a frozen frame with clocks stopped.

InterSpec has no file watcher — rewriting a spectrum file on disk never
updates a running InterSpec session (loaded spectra live in memory and are
deduplicated by UUID). The MCP `load_spectrum_file` push is what makes live
updates possible; the plain files exist for later analysis, not for refresh.

## Building from source / for distribution

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[gui,specutils]" pyinstaller
./scripts/build_release.sh        # → dist/mcabridge-<platform>.tar.gz / .zip
```

Windows: `bash scripts/build_release.sh` from Git Bash. GitHub CI
(`.github/workflows/build.yml`) builds all four bundles on every `v*` tag and
attaches them to a Release; the workflow pins **Python 3.12** because that is
the newest version with prebuilt SandiaSpecUtils wheels.

## Limitations & roadmap

- Live push requires InterSpec with the MCP API (2026+/1.0.x builds; verified
  on the Linux `.deb` 1.0.14 and a Windows x64 build). Older builds:
  `--push-mode launch` works as a one-time handoff only (see the Push modes
  table) — not a live feed.
- If InterSpec is *not* running, MCP pushes fail until it starts (mcabridge
  keeps acquiring and saving regardless; pushes resume on the next autosave
  once InterSpec is up).
- Compatibility with spectrum software other than InterSpec has not been
  investigated; the written file formats are standard, but only InterSpec is
  targeted and tested.
- The MCP endpoint also exposes InterSpec's analysis tools to localhost;
  mcabridge never calls them. Keep the bearer token private.
- Coincidence (right-channel) mode: not yet, though the capture layer already
  supports stereo.
- Tested against synthetic pulses + live silent-device runs; hardware QA with
  a real GS-PRO-V5 in progress — see `tests/`.

## License

MIT. InterSpec and SpecUtils are Sandia National Labs (LGPL-2.1); mcabridge uses
only their public file formats, published Python bindings, and the MCP API that
Sandia ships (disabled by default), and is not affiliated with or endorsed by
Sandia. No InterSpec sources are modified — enabling the bridge is a user
config setting, exactly as Sandia intends it to be used.
