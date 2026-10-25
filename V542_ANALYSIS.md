# V5.4.2 investigation — stable action window + anti-jitter jump ownership

## What the V5.4.1 run showed

Run duration: ~44.5 minutes.

Visible GREEN episodes: 15.
Most were one processed frame; none lasted 0.4 s.

Three crashes occurred shortly after marginal GREENs:
- signal 1: initial verified action lease ~0.17 s, crash ~2.45 s later
- signal 7: initial verified action lease ~0.31 s, crash ~2.25 s later
- signal 11: initial verified action lease ~0.41 s, crash ~2.76 s later

These were physically verified gaps, but they were surfaced too late in the gap to be useful as a manual-action permission.

## False JUMPING / stuck state

After signal 9 the chicken position was approximately:

631 -> 661 -> 702 -> 640 -> 631...

There was no one-lane jump. This was detector wobble of only ~70 px.
The V5.4.1 outcome tracker used a fixed 18 px action-start threshold, so it falsely created a GREEN action and remained JUMPING for ~5.4 s.

V5.4.2 uses a lane-scaled action threshold:

    max(18 px, 0.18 * signal-time lane step)

For a ~440 px lane this is ~79 px. The observed ~70 px wobble is rejected, while real first movement in earlier jumps (~140 px+) is still detected.

## Why good gaps were missed

There were 252 verified-gap state rows. 92 passed hard physical safety gates.
Among those, 33 were still rejected because the blended ML probability was only ~0.26-0.58 while the physical heuristic was ~0.94-0.97.

Many of these had:
- dynamic confidence ~0.78-0.84
- gap P25 ~2.5-2.9 s
- clean motion/MOG
- 0.7-1.0 s extra action lease

V5.4.1's physical override required at least 12 motion-gap samples. Many strong windows had 10-11 samples and were therefore missed.

## V5.4.2 GREEN policy

### Marginal verified gaps are no longer displayed
New GREEN admission requires at least 0.55 s extra verified action lease.
This removes the three crash-associated marginal signals from this run.

### Strong missed verified gaps may bypass ML
The strict physical override now requires:
- verified dynamic gap
- heuristic >= 0.94
- dynamic confidence >= 0.78
- motion-gap support >= 10
- gap P25 >= 2.20 s
- action lease >= 0.55 s
- raw risk <= 12
- motion corridor <= 0.03
- MOG <= 0.04
- all existing hard target/vehicle/processing/viewport vetoes must pass

On the supplied V5.4.1 telemetry this recovers roughly six distinct strong verified opportunities that the ML prior suppressed, while removing the low-lease crash-associated GREENs.

### Early motion-rise cancellation
Once GREEN is visible, it is cancelled early if live traffic evidence suddenly rises:
- raw risk > 30, or
- motion corridor > 0.06, or
- MOG > 0.08

This is only a cancellation rule; it can never create a GREEN.

## Six-second missed-opportunity blackout fixed

V5.4.1 inherited a 6 s presentation cooldown after every unacted GREEN.
Because many GREENs were only a few tenths of a second long, the tracker often classified them as unacted and hid later opportunities for six seconds.

V5.4.2 makes this cooldown cycle-aware:
- same dynamic-gap cycle: repeated flicker remains suppressed
- new busy->clear cycle: display can reopen immediately
- fallback same-cycle cooldown reduced to 2.0 s

## Existing safety architecture retained

- causal GREEN outcome ownership
- one GREEN = one jump
- fullscreen third-lane recent-peak reframe
- no fabricated crash fallback GREEN failures
- current-session speed guard for observed-clear
- target-switch successful landing handoff
- missing-CV outcomes remain UNKNOWN

## Regression checks

Passed:
- V5.4.2 stable action-window / anti-jitter / strong-gap override / cycle-aware rearm
- V5.4.1 session-speed guard + jump handoff
- V5.3.9 verified physical override
- V5.3.8 causal outcome + fullscreen reframe
- V5.3.7 verified-gap fast path
- V5.3.5 fullscreen reframe

Older tests that explicitly require very small (<~0.2 lane) motion to count as a GREEN action are intentionally superseded because the supplied V5.4.1 run proves that behavior creates false JUMPING states from detector wobble.
