# V5.4.9 investigation — V5.4.8 regression

## 1. Primary zero-GREEN root cause: processing gate

V5.4.8 state:
- duration ~32.8 min
- median processing FPS ~2.35
- median processing lag ~425 ms
- processing_healthy true on only ~2.9% of rows

V5.4.7 state:
- median processing FPS ~6.5

SafeWindow V5.4.8:
- 4,596 rows blocked by PROCESSING
- 94 LIVE GAP UNVERIFIED
- 32 FORECAST ETA
- only 5 rows with no hard veto / decision opportunity
- one registered GREEN signal

Therefore V5.4.8 did not primarily fail because traffic had no safe windows.
The fixed 2.8-FPS gate disabled the decision engine for almost the entire run.

V5.4.9 permits stable >=2.0-FPS degraded operation. This does not remove timing
safety because SafeWindow already raises required action lease as FPS falls.

At ~2.35 FPS:
    one-frame presentation margin ~= 1/2.35 + 0.04 ~= 0.47 s

## 2. Strong opportunities still existed

Using current physical telemetry and V5.4.7-style mode lease profiles while
ignoring only the global PROCESSING block, the supplied state contains roughly:
- 26 strong physically eligible verified frames
- ~20 distinct gap episodes

Examples include verified gaps with:
- heuristic probability around 0.95-0.96
- dynamic confidence around 0.81-0.97
- motion gap P25 around 2.6-2.9 s
- raw risk 2
- zero target-lane motion
- 0.5-1.1 s action lease

So a zero-GREEN outcome is not justified by the traffic telemetry alone.

## 3. V5.4.8 manual-success overcount

V5.4.8 enabled passive manual success learning, but the validation was not tied
to a unique target ownership transition.

Observed:
- manual_successes reached 126
- target_lane_switches reached only 51
- successful_lane_streak reached 75

Two large state-log stalls coincide with success-counter bursts:
- ~17.9 s around the jump from 0 to 42 manual successes
- ~32.4 s around the jump from 51 to 126 manual successes

Even if not every millisecond of those gaps is caused by classifier training,
the counters prove the learner was crediting many duplicate/false manual SAFE
events.

V5.4.9 requires exactly one target switch and deduplicates by switch ID.
Manual training is low weight and classifier partial_fit is skipped when the
analyzer is already in degraded-FPS mode.

## 4. Preserve V5.4.7

V5.4.9 starts from V5.4.7 source.

Not carried forward from V5.4.8:
- higher 0.45-0.60 physical lease floors
- higher standard lease floors
- third-success extra lease/settle
- global two-GREEN-per-20-second presentation limiter

Preserved:
- centered post-pass GREEN
- difficulty mode switching
- V5.4.7 click-vs-CV timing separation
- runtime-gap recovery
- mid-lane chicken identity protection
- causal one-GREEN/one-jump outcome logic
- fullscreen reframe
- verified-gap physical ML override

## 5. Post-jump stuck recovery

V5.4.7's generic stale-chicken reacquire waited ~1.0 s.
V5.4.9 uses ~0.60 s when the system is explicitly waiting for the chicken to
land or the detector is rejecting an ambiguous between-lane candidate.

This clears stale screen-space identity sooner without disabling the anti-blob
mid-lane guard.

## Regression status

Passed:
- V5.4.9 preserved V5.4.7 profiles + degraded-FPS safety/schema
- V5.4.7 runtime recovery/click-vs-CV/mid-lane identity
- V5.4.6 delayed causal action attribution
- V5.4.5 centered GREEN/cycle-aware rearm
- V5.4.4 difficulty mode switching
- V5.3.9 strong physical override
- V5.3.8 causal outcome/reframe
- V5.3.5 fullscreen reframe
