# V5.4.7 root-cause investigation

## Supplied V5.4.6 run

Duration: ~15.34 minutes.

Observed:
- State rows: 2,616
- SafeWindow rows: 8,083
- Visible CLEAR state rows: 1
- GREEN signals: 1
- GREEN acted: 0
- GREEN successes: 0
- GREEN failures: 0

Dominant SafeWindow vetoes:
- LIVE GAP UNVERIFIED: 3,726
- FORECAST ETA: 2,282
- PHYSICAL ETA: 1,237
- CLEAR LEASE: 375
- TRACK REWARM: 137
- VISION/VIEWPORT: 94
- POST PASS SETTLE: 69

## Root cause 1 — action-confirmation latency polluted safety ETA

V5.4.6 deliberately expanded GREEN action attribution so a robust lane-relative
movement could be recognized even when the chicken detector shows it much later.

That was correct for causality, but the same delayed motion timestamp was fed into
RiskEngine as "reaction time".

In the supplied run:
- dynamic_gap_reaction_budget mean: ~0.99 s
- dynamic_gap_reaction_budget max: ~1.14 s
- dynamic_gap_required_eta mean: ~2.04 s

The user reports clicking GO immediately. The delayed telemetry is therefore
mainly game animation + anti-wobble confirmation + CV frame cadence.

V5.4.7 splits these concepts:
- outcome attribution grace remains 2.30 s,
- physical input-response budget is 0.30/0.34/0.40/0.46 s by mode.

Offline replay of the supplied state using the new input-response budgets finds
about 223 basic physically eligible frames and roughly 28 strong centered
verified-gap episodes, versus only one GREEN in V5.4.6. This is diagnostic replay,
not an exact future GREEN-count guarantee.

## Root cause 2 — jump-caused rewarm blocked outcome ownership

The one GREEN appears around run +168.4 s.

After it:
- chicken ~564 px
- then ~598 px
- then ~1065 px
- target switch increments
- target reason becomes ARRIVED

This is a real lane transition.

Nevertheless green_acted remains 0 because V5.4.6's action attribution rejected
movement whenever viewport_hold/vision_hold was set. The jump itself rebuilds the
target motion ROI and can set those generic hold flags.

V5.4.7 blocks attribution only for actual coordinate-frame motion:
scene pan, progress scroll, fullscreen reframe, or stale chicken detection.

## Root cause 3 — real runtime stalls / stale-state recovery

The state timestamps contain large holes:
- 23.41 s after the first lane transition
- 13.79 s
- 14.55 s
- 15.26 s
- 14.31 s

The supplied recording continues showing the game running during the initial
period, so the analyzer must not continue from stale chicken/target/MOG state
when processing resumes.

V5.4.7 adds a >=1.50 s runtime-gap watchdog. On resume it reacquires chicken and
rebuilds only screen-space/short-lived state; long-term learning is retained.

Periodic full model serialization is also removed from the live hot loop.
Telemetry flushes remain; models are saved on clean exit.

## Root cause 4 — between-lane chicken identity

After a lane transition the state held a stable chicken near ~631 px, then moved
to ~460 px for many seconds. That position is between expected lane centres and
the anchor becomes unstable.

The identity selector previously preferred any candidate within ~0.42 lane of
the last chicken. This can favor a nearby red/yellow/white traffic/decor blob
over the newly-landed chicken.

V5.4.7:
- narrows near preference to 0.24 lane,
- rejects 0.28-0.70-lane ambiguous mid-lane candidates,
- waits for a proper near-one-lane landing confirmation.

## Regression status

Passed:
- V5.4.7 click-vs-CV timing split / rewarm attribution / mid-lane identity/schema
- V5.4.6 delayed causal attribution
- V5.4.5 centered GREEN / anti-jitter / cycle rearm
- V5.4.4 difficulty regime switching
- V5.3.9 strong physical override
- V5.3.8 causal outcome / one-jump / reframe
- V5.3.5 fullscreen reframe
