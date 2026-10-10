"""Digital pulse processing for audio-card MCAs (numpy, block based).

The GS-PRO-V5 sends raw detector pulses through a 16-bit / 48 kHz USB audio
codec.  This module performs the multi-channel-analysis steps in software:

  baseline tracking -> edge trigger -> peak measurement (parabolic
  interpolation) -> pile-up rejection -> pulse-height histogram, with
  non-paralyzable dead-time accounting.

The processor is fed mono int16 blocks from the capture thread.  Pulses that
straddle block boundaries are handled by carrying the last ``pre + post +
guard`` samples into the next block; each trigger is decided exactly once via
an absolute resume index.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np


@dataclass
class ProcessorConfig:
    threshold_adc: float = 60.0        # trigger level above baseline (ADC counts)
    polarity: int = 1                  # +1 for positive pulses, -1 for negative
    pretrigger_samples: int = 8        # quiet samples required before the trigger
    posttrigger_samples: int = 40      # samples watched after crossing (pulse length)
    guard_forward: int = 12            # extra tail samples that must stay quiet (pileup veto)
    n_channels: int = 4096             # histogram channels
    full_scale_adc: float = 32768.0    # pulse height mapping to the top channel
    dead_time_extra_us: float = 1.0    # extra fixed dead time per processed pulse
    parabolic_peak: bool = True        # interpolate apex between samples


@dataclass
class ProcessorStats:
    real_time: float = 0.0
    live_time: float = 0.0
    accepted: int = 0
    rejected_pileup: int = 0
    rejected_overrange: int = 0
    overflows: int = 0

    def snapshot(self) -> dict:
        return dict(real_time=round(self.real_time, 3), live_time=round(self.live_time, 3),
                    accepted=self.accepted, rejected_pileup=self.rejected_pileup,
                    rejected_overrange=self.rejected_overrange, overflows=self.overflows)


class PulseProcessor:
    """Streaming pulse-height analyser for a mono int16 audio stream."""

    def __init__(self, sample_rate: float, cfg: ProcessorConfig | None = None):
        self.sample_rate = float(sample_rate)
        self.cfg = cfg or ProcessorConfig()
        self.spectrum = np.zeros(self.cfg.n_channels, dtype=np.uint64)
        self.stats = ProcessorStats()
        self._carry = np.zeros(0, dtype=np.float64)   # already polarity-fixed
        self._block_start_abs = 0                     # abs index of _carry[0]... of next block's sample 0? see feed
        self._resume_abs = 0                          # triggers below this are decided
        self._dead_until_abs = 0
        self._total_samples = 0                       # absolute samples fed so far
        self._baseline = 0.0

    def reset(self) -> None:
        cfg = self.cfg
        sr = self.sample_rate
        self.cfg = ProcessorConfig(**{k: getattr(cfg, k) for k in cfg.__dataclass_fields__})
        self.__init__(sr, self.cfg)

    # ------------------------------------------------------------------ feed
    def feed(self, block_int16: np.ndarray) -> None:
        """Process one capture block (mono int16 array)."""
        cfg = self.cfg
        sign = 1.0 if cfg.polarity >= 0 else -1.0
        x = sign * block_int16.astype(np.float64)

        carry_n = self._carry.size
        if carry_n:
            x = np.concatenate((self._carry, x))
        block_start_abs = self._total_samples - carry_n   # abs index of x[0]
        n = x.size
        keep = cfg.pretrigger_samples + cfg.posttrigger_samples + cfg.guard_forward + 2

        self.stats.real_time += block_int16.size / self.sample_rate

        # ---- running baseline: 20th percentile (robust to pulse duty cycles
        # up to ~a few hundred cps; pulses are positive after polarity fix)
        base = float(np.percentile(x, 20)) if n else 0.0
        if self._total_samples == 0 and not carry_n:
            self._baseline = base          # exact init on the very first block
        else:
            self._baseline += 0.1 * (base - self._baseline)
        y = x - self._baseline

        # ---- rising-edge triggers
        thr = cfg.threshold_adc
        above = y >= thr
        trig_rel = np.flatnonzero(above[1:] & ~above[:-1]) + 1
        pre, post, guard = cfg.pretrigger_samples, cfg.posttrigger_samples, cfg.guard_forward
        win = post + guard

        dead_per_pulse = post / self.sample_rate + cfg.dead_time_extra_us * 1e-6
        accepted: list[int] = []
        first_undecided_abs: int | None = None

        for t in trig_rel:
            t_abs = block_start_abs + int(t)
            if t_abs < self._resume_abs:
                continue                              # decided on a previous block
            if t + win >= n:
                first_undecided_abs = t_abs           # needs data from next block
                break
            if t_abs < self._dead_until_abs:
                continue                              # inside dead time: lost, but decided
            if t - pre < 0:
                self.stats.rejected_pileup += 1
                self._dead_until_abs = t_abs + post
                continue

            # pile-up vetoes -------------------------------------------------
            if np.any(y[t - pre : t] > thr * 0.5):    # noise before pulse
                self.stats.rejected_pileup += 1
                self._dead_until_abs = t_abs + post
                continue
            tail = y[t + post : t + win]
            if tail.size and np.any(tail >= thr):     # second pulse in decay tail
                self.stats.rejected_pileup += 1
                self._dead_until_abs = t_abs + post
                continue
            if np.max(x[t - pre : t + win]) >= 32700.0:   # ADC rail clip
                self.stats.rejected_overrange += 1
                self._dead_until_abs = t_abs + post
                continue

            # ---- peak height
            rel = int(np.argmax(y[t : t + post]))
            peak = y[t + rel]
            if cfg.parabolic_peak and 0 < t + rel < n - 1:
                y0, y1, y2 = y[t + rel - 1], y[t + rel], y[t + rel + 1]
                denom = y0 - 2.0 * y1 + y2
                if denom != 0.0:
                    frac = 0.5 * (y0 - y2) / denom
                    if abs(frac) <= 1.0:
                        peak = y1 - 0.25 * (y0 - y2) * frac

            ch = int(peak * cfg.n_channels / cfg.full_scale_adc)
            if ch < 0:
                self.stats.rejected_pileup += 1       # dipped negative: noise blip
            elif ch >= cfg.n_channels:
                self.stats.overflows += 1
            else:
                accepted.append(ch)
                self.stats.accepted += 1

            self._dead_until_abs = t_abs + post

        if accepted:
            np.add.at(self.spectrum, np.asarray(accepted), 1)

        # ---- decide resume point and carry
        if first_undecided_abs is not None:
            self._resume_abs = first_undecided_abs
        else:
            self._resume_abs = block_start_abs + n    # everything decided
        self._carry = x[-keep:] if n >= keep else x.copy()
        self._total_samples += block_int16.size

        processed = (self.stats.accepted + self.stats.rejected_pileup
                     + self.stats.rejected_overrange)
        self.stats.live_time = max(0.0, self.stats.real_time - processed * dead_per_pulse)
