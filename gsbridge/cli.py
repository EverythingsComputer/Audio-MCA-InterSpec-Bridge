"""Command-line interface for gsbridge.

Examples
--------
  # list capture devices
  python -m gsbridge --list

  # record from the GS-PRO-V5 for 60 s, writing .spe + .spc every 5 s
  python -m gsbridge --seconds 60 --formats spe,spc

  # replay a WAV captured with any recorder (validation / demo)
  python -m gsbridge --wav test.wav --formats spe,n42

Then open gsbridge_live.spe in InterSpec (re-open it any time for the latest data).
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from .capture import AudioStreamSource, WavSource
from .dsp import ProcessorConfig
from .engine import Engine
from .writers import HAVE_SPECUTILS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gsbridge",
        description="Audio-card MCA (Gammaspectacular GS-PRO-V5 etc.) to "
                    "InterSpec live-file bridge.")
    p.add_argument("--list", action="store_true", help="list input devices and exit")
    p.add_argument("--device", default="codec",
                   help="substring match on capture device name (default: 'codec')")
    p.add_argument("--rate", type=float, default=48000.0, help="sample rate Hz (default 48000)")
    p.add_argument("--seconds", type=float, default=0,
                   help="stop after N seconds (0 = run until Ctrl-C)")
    p.add_argument("--wav", metavar="FILE", help="replay a 16-bit PCM WAV instead of live capture")
    p.add_argument("--channel", type=int, default=0, help="input channel (GS = left = 0)")
    p.add_argument("--outdir", default="~/Documents/GS-Bridge-output",
                   help="output directory for spectrum files")
    p.add_argument("--formats", default="spe",
                   help="comma list of spe,spc,n42,pcf (spc/n42/pcf need SpecUtils bindings"
                        f"{'' if HAVE_SPECUTILS else ' - NOT installed'})")
    p.add_argument("--autosave", type=float, default=5.0, help="seconds between autosaves")
    p.add_argument("--threshold", type=float, default=60.0, help="trigger threshold (ADC counts)")
    p.add_argument("--pulse-samples", type=int, default=40,
                   help="pulse length in samples after trigger (48k * 0.83ms ~= 40)")
    p.add_argument("--channels", type=int, default=4096, help="MCA channel count")
    p.add_argument("--negative", action="store_true", help="pulses are negative-going")
    p.add_argument("--push", metavar="CMD", default=None,
                   help="fallback push: after each autosave run CMD <file> (e.g. "
                        "'interspec' or 'xdg-open'); used when --push-mode launch "
                        "or when the MCP API is unavailable")
    p.add_argument("--push-mode", choices=("mcp", "launch", "off"), default="mcp",
                   help="how autosaves reach InterSpec: 'mcp' (default) posts to "
                        "InterSpec's built-in MCP API and repaints the running "
                        "window in place; 'launch' uses --push CMD; 'off' disables")
    p.add_argument("--lane", choices=("Foreground", "Background", "Secondary"),
                   default="Foreground", help="which InterSpec slot to load into "
                   "(MCP mode only)")
    p.add_argument("--energy-cal", metavar="C0,C1[,C2,C3]", default=None,
                   help="embed keV energy calibration polynomial in saved/pushed "
                        "spectra (e.g. '-1.5,0.734' = linear); InterSpec then "
                        "shows energies without the no-calibration warning")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.list:
        for i, name in AudioStreamSource.list_inputs():
            print(f"[{i}] {name}")
        return 0

    cfg = ProcessorConfig(threshold_adc=args.threshold,
                          posttrigger_samples=args.pulse_samples,
                          n_channels=args.channels,
                          polarity=-1 if args.negative else 1)

    fmts = [f.strip() for f in args.formats.split(",") if f.strip()]
    for f in fmts:
        if f not in ("spe", "spc", "n42", "pcf"):
            print(f"unknown format '{f}'", file=sys.stderr)
            return 2
        if f != "spe" and not HAVE_SPECUTILS:
            print("SpecUtils bindings missing; install with "
                  "`pip install sandiaspecutils` or use spe only.", file=sys.stderr)
            return 2

    wav = args.wav

    def factory():
        if wav:
            return WavSource(wav, channel=args.channel, blocksize=int(args.rate // 10))
        return AudioStreamSource(device_match=args.device, sample_rate=args.rate,
                                 channel=args.channel)

    import os
    push_cmd = args.push.split() if args.push else ["interspec"]
    ecal = ([float(x) for x in args.energy_cal.split(",")]
            if args.energy_cal else None)
    engine = Engine(factory, cfg, outdir := os.path.expanduser(args.outdir),
                    save_formats=fmts, autosave_s=args.autosave, push_cmd=push_cmd,
                    push_mode=args.push_mode, lane=args.lane, energy_cal=ecal)
    engine.sample_rate = args.rate

    try:
        engine.start()
    except Exception as e:
        print(f"start failed: {e}", file=sys.stderr)
        return 1

    src_desc = f"WAV {wav}" if wav else f"device '{args.device}' @ {args.rate:.0f} Hz"
    print(f"acquiring from {src_desc}; writing {', '.join(fmts)} to {outdir}")
    print("open gsbridge_live.spe in InterSpec; re-open it any time for the latest data.")

    stop = {"want": False}

    def handle_sig(signum, frame):
        if stop["want"]:
            sys.exit(1)
        stop["want"] = True
        print("\nstopping...")

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    t0 = time.monotonic()
    try:
        while engine.running and not stop["want"]:
            time.sleep(0.5)
            spec, stats, elapsed = engine.snapshot()
            cps = stats.get("accepted", 0) / max(elapsed, 1e-6)
            live = stats.get("live_time", 0) / max(stats.get("real_time", 1e-9), 1e-9) * 100
            print(f"\r  {elapsed:6.1f}s  input {cps:7.1f} cps  live {live:5.1f}%  "
                  f"pileup-rej {stats.get('rejected_pileup',0)}   ", end="", flush=True)
            if args.seconds and elapsed >= args.seconds:
                break
    finally:
        engine.stop()

    spec, stats, elapsed = engine.snapshot()
    print(f"\ndone: {stats.get('accepted',0)} counts in {elapsed:.1f}s -> {outdir}")
    if engine.last_error:
        print(f"error: {engine.last_error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
