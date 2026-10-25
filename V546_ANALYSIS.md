# V5.4.6 investigation — GREEN failures were not being attributed

## V5.4.5 telemetry

The decisive finding is not a GREEN threshold.

V5.4.5 recorded:
- 38 GREEN signals
- 0 acted GREEN signals
- 0 GREEN successes
- 0 GREEN failures
- 1 late/unattributed action

Therefore the model was not learning from the user's real GO clicks.

## Measured action timing

Using the visible GREEN episodes and the first robust forward displacement of
~24% of the current lane, likely actions appeared roughly:

- signal 1: ~1.99 s after GREEN end
- signal 2: ~1.79 s
- signal 4: ~1.32 s
- signal 6: ~1.19 s
- signal 8: ~1.61 s
- signal 9: ~2.22 s
- signal 27: ~0.87 s
- signal 32: ~1.89 s
- signal 36: ~0.92 s
- signal 38: ~1.00 s

The configured causal grace was only 0.65 s.

This explains why the user could click immediately, yet the outcome system saw
no acted GREEN: chicken motion crosses the anti-wobble confirmation threshold
later than the UI click.

## Why not simply lower the movement threshold?

Earlier builds proved that the detector can wobble around 50-70 px while the
chicken is stationary. Lowering the threshold would recreate false JUMPING.

V5.4.6 instead:
- keeps a lane-relative robust threshold,
- raises confirmation from ~18% to ~24% of lane,
- extends causal attribution to 2.30 s.

This is intentionally causal movement attribution, not the old crash fallback.
The old V5.3.7 six-second crash-progress fabrication remains removed.

## Difficulty controller finding

At 13 of 25 sampled visible GREEN starts, current speed/density evidence implied
a higher minimum difficulty mode than V5.4.5 was using.

Examples:
- live speed difficulty ~0.81 with EASY mode
- live speed difficulty ~1.00 with NORMAL mode
- one high-speed/high-busy GREEN remained EASY even though the current traffic
  should be treated as HARD during the click->jump latency.

V5.4.6 adds a fast-traffic mode floor while retaining hysteresis.

## Reaction-learning source mismatch

GREEN decisions are exposed as eta_source=v5-safe-window, but the dynamic gap
engine requests learned response timing using the key `dynamic-gap`.

V5.4.6 stores an additional physical timing source:
- verified-gap -> dynamic-gap
- observed-clear -> clear-zone

Validated successful actions now train the source that actually controls future
reaction budgets.

## Reaction budget

The old dynamic-gap reaction budget was pinned at 0.72 s for every visible GREEN.

V5.4.6 uses bounded mode-specific ceilings:
- EASY 0.85 s
- NORMAL 0.95 s
- HARD 1.10 s
- EXTREME 1.20 s

This adds safety margin in harder/faster traffic without applying an extreme
global delay that would starve GREEN.

## Regression status

Passed:
- V5.4.6 causal delayed action + anti-wobble + mode floor
- V5.4.5 centered post-pass GREEN timing
- V5.4.4 difficulty mode switching/schema
- V5.3.9 physical verified override/hard-veto preservation
- V5.3.8 causal outcome ownership/reframe
- V5.3.5 fullscreen reframe

Older pre-centered-GREEN tests that expect immediate first-clear-frame admission
are intentionally superseded by V5.4.5+.
