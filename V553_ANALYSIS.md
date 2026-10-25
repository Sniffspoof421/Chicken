# V5.5.3 — V5.5.2 complete-failure investigation

## What the supplied run says

The current run is not a confirmed unsafe-GREEN regression.

It recorded:
- duration ≈ 9.39 minutes
- 2 GREEN signals
- 1 acted GREEN
- 1 GREEN success
- 0 GREEN failures
- 6 generic crash records

The failure perceived in play is mainly that the predictor almost stopped
producing usable GREEN windows.

### SafeWindow blockers

Approximate counts:
- LIVE GAP UNVERIFIED: 2,206
- FORECAST ETA: 1,032
- VISION/VIEWPORT: 322
- TRACK REWARM: 238
- CLEAR LEASE: 140

Processing remained healthy around 6.5-6.8 FPS.

## Root cause: local evidence is repeatedly erased by legitimate progress

The run reached:
- target-lane switches: 57
- lane-phase realigns: 15
- fullscreen/progress reframes: 11

Each geometry reanchor correctly discards screen-corridor-local motion history.

However this active run reanchors often enough that the local dynamic-gap model
rarely matures before it is reset again.

Examples in the supplied telemetry show motion-gap support dropping:
- 9 -> 0
- 14 -> 0
- 15 -> 0
and other similar resets.

Median motion-gap support was only 8.

Mode maturity requirements are:
- EASY 8
- NORMAL 9
- HARD 10
- EXTREME 12

Mode distribution in the run was approximately:
- HARD: 822 state rows
- NORMAL: 409
- EXTREME: 365
- EASY: 89

So most frames required more evidence than the median retained support.

dynamic_gap_ready was true on only 20 of 1,685 state rows (~1.2%).

## Bootstrap deadlock

There is a second interaction.

Before local support matures beyond the low-support cap, dynamic remaining time
is bounded by the clear-zone ETA.

That geometry ETA repeatedly sits near ~1.4 s.

Therefore a new lane may already contain several empirical ~2 s completed gaps,
but it still gets only ~1.4 s physical horizon until support fully matures.

That leaves almost no action lease, so the lane cannot become verified.

The next progress/reanchor may occur before maturity, and the cycle repeats.

## V5.5.3 design

### Two-level evidence

Local history:
- current physical corridor only
- still cleared on geometry reanchor

Session prior:
- rolling 180 s
- contains only completed raw-motion clear gaps from the current process/session
- survives reanchor
- never authorizes GREEN alone

A bootstrap opportunity requires:
- 5 local gaps in EASY/NORMAL, 6 HARD, 7 EXTREME
- at least 10 session-prior gaps
- strong local P25 by mode
- local and prior lower-tail estimates both valid
- >=0.30 s physical headroom over dynamic required ETA

The bootstrap lower bound is:
    min(local recent lower-tail, session-prior lower-tail)

This is intentionally conservative. The prior cannot upgrade the current lane
beyond what the current lane itself has observed.

Mature mode support thresholds remain unchanged at 8/9/10/12.

### RECHECK stuck correction

Two RECHECK episodes lasted roughly 9.48 s and 9.33 s.

The old rearm logic waits primarily for absolute screen X to become stable.
Normal progress can change X even though the chicken is already landed.

V5.5.3 adds an independent geometry release:
- fresh chicken
- stable chicken anchor
- valid next-lane target
- no tracking rewarm
- target about one lane ahead
- stable target/viewport identity

After ~0.28 s of that evidence, RECHECK releases.

The old X-stability path is retained as a fallback.

### WAIT_CHICKEN_LAND watchdog

A separate 1.35 s watchdog rebuilds the immediate next target from the current
fresh chicken when landing geometry is already stable.

## Offline evidence

A strict under-mature scan of the supplied run finds multiple strong episodes
where local support was below the mature mode threshold but the local lower-tail
gap was already materially above required ETA.

The new bootstrap is designed specifically for those episodes.

It does not guarantee a fixed GREEN count; live traffic still has to satisfy
all current hard safety gates.

## Regression status

Passed:
- V5.5.3 session-gap prior / local-evidence requirement / geometry rearm release
- V5.5.2 degraded-FPS headroom / progress handoff
- V5.5.1 recent-threat tail
- V5.5.0 causal landing survival / source feedback
- V5.4.7 runtime recovery / click-vs-CV / mid-lane identity
- V5.4.6 delayed causal attribution
- V5.4.5 centered GREEN
- V5.4.4 difficulty modes
- V5.3.9 physical verified override
- V5.3.8 causal ownership/reframe
- V5.3.5 fullscreen reframe
- V5.3.4 current-session CZN authority
- V5.3.3 chicken-authoritative geometry

The legacy V5.4.9 test that hard-codes the old degraded-FPS frame-margin value
remains intentionally superseded by V5.5.2.
