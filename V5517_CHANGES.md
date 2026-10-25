# V5.5.17

## What the supplied run established
The 20261025_004825 state trace covers 33.15 minutes. There were ten internally
registered GREENs, one input-owned attempt, zero resolved successes/failures and
ten crash-detector events (not ten GREEN crashes). Nine unacted GREEN durations
were 0.156-0.404 seconds. That does not establish ten visible, usable opportunities.
The failure counter remained 15; successes remained 91; runtime tick errors were zero.

Signal 3: valid Space at 1792869867.8433082; baseline around x630,y731.
Fresh detection reached x637,y764, then was lost; it returned near x191,y731 and
stayed there. Target progression was labelled VIEW_SCROLL without an independently
observed landing. The attempt finally became UNKNOWN, rather than failure feedback.
CrashDetector's minimum-progress condition misses early failed jumps.

## Changes
1. A narrow early-reset classifier for input-owned attempts:
   - Valid existing input attribution and detected movement.
   - Downward displacement >=6% of lane spacing before 35% forward progress.
   - No observed target landing or substantial forward travel.
   - Fresh return 0.65-1.35 lanes behind the baseline, near original ground height.
   - Two stable observations separated by the existing landing hold.
   - Within the existing outcome timeout; duplicated input remains excluded.
   - Actual pan/reframe/settling invalidates this evidence. Explicit coordinate
     rebasing clears it.
   - The raw pan flag that fullscreen mode explicitly ignores remains telemetry;
     it does not override the application's effective viewport state.
   This resolves the supplied signal-3 state sequence as input_owned_early_fall_reset
   and sends it through existing failure learning exactly once.

   This is an inference from the CV sequence, not independent video ground truth.
   A sufficiently similar detector error can still fool it. No old UNKNOWN labels
   or model files are rewritten. Early failures returning to the same starting x,
   or ambiguous real reframes, are not force-labelled by this rule.

2. Presentation before logging:
   Publish state and synchronously repaint the overlay before CSV/debug I/O.
   Expiry is still checked at paint time; the physical deadline is never extended.
   presentation_audit_v5517.jsonl records green_painted and green_paint_ended
   transitions, deduplicated by signal ID. These prove that the application painted
   a cue, not that the monitor displayed it or the person noticed it. Events are
   drained on subsequent tick processing; abrupt termination can lose a final event.

## What was NOT changed
config.json is byte-identical to V5.5.16. No global ETA, probability, support,
lease, cooldown or difficulty tightening. Broad unresolved-vehicle veto remains
diagnostic; earlier logs showed it would remove most opportunities. The prior
timeout and scoped-peak fixes remain. Models are retained when the data folder is copied.

## Validation and limits
See V5517_TEST_RESULTS.json. The outcome regression replays the shared signal-3
state fields, including ignored raw-pan telemetry, through outcome.update.
It checks one failure and separately checks a learner increment. Negative cases
cover actual pan, rebase, upward-only motion, substantial forward progress, stale
detections and late resets. A Qt test checks actual paint callbacks and expiry.
The existing current regression suite is also run.
Legacy test_v550_causal_landing.py already fails on V5.5.15/16 due to subsequently
changed landing requirements; it is excluded, not counted as a pass.
These are software regressions and state replay, not full pixel replay or native
Windows live validation. They do not demonstrate improved live precision or
increased GREEN availability. No trustworthy success percentage can be derived
from this run's unresolved labels.

## Why previous iterations did not establish improvement
The work fixed individual plumbing errors without a reliable end-to-end benchmark
of visible cues and causally resolved outcomes. Synthetic checks passed while
live feedback remained incomplete. This build addresses two identifiable parts
of that gap; it cannot honestly be described as a finished, accurate predictor.
