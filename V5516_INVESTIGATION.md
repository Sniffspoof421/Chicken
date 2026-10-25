# V5.5.16 investigation and changes

## Latest run: 20261024_214118
46 GREEN starts in 47.32 minutes (0.97/minute).
Four Space inputs recorded within displayed GREEN validity: signals 1, 4, 9, 38.
All four acquired input ownership and movement confirmation, but were classified UNKNOWN
with chicken_detection_timeout. The safe-window failure counter stayed 15; successes
rose 88 to 91. Three logged successes (2, 3, 46) used CV post-GREEN-grace attribution,
not recorded in-window input ownership. There were 12 outcome-audit entries:
3 successes, 8 UNKNOWN, 1 chained/unvalidated. Four crash CSV rows are not four
proven GREEN failures; unrelated manual play is excluded from GREEN conclusions.
Zero runtime tick errors were logged.

A reliable GREEN success percentage cannot be computed from these labels.
Neither 3/3 nor 3/46 measures causal GREEN accuracy.

## Root causes demonstrated in code and logs
1. The missing-chicken timeout was measured from action start. Once an attempt was
1.25 seconds old, a single missing observation could immediately discard ownership.
This happened to all four input-owned attempts. Signal 9 was discarded at
1792859159.4975908; confirmed reset was logged at 1792859160.0435493.
2. on_crash compared the current attempt with CrashDetector.max_x, whose lifetime
can cover earlier jumps and different viewport coordinates. For signal 9, that value
was 1659.5, while the current jump began around x630 and reached about x692.
Using that old peak can incorrectly classify the attempt as multiple jumps.

Signals 1, 4 and 38 also have return-to-start-like traces after disappearance.
They are suspicious failures, but these files alone do not independently establish
every reset versus viewport transition. They are not retroactively relabelled.

## Changes
- Measure continuous detection absence; fresh detections clear that absence clock.
- Preserve the existing absolute outcome timeout so permanent detection loss is bounded.
- For input-owned attempts, use the attempt's observed peak rather than the detector's
historical peak. Capture fresh post-input displacement even before filtered outcome
processing. Actual progress beyond the chain envelope remains excluded.
- Preserve input/focus/deadline checks, duplicate-input exclusion, settled-landing
requirements, final-success ownership, and viewport invalidation.
- Versioned launcher, runtime logs and input audit now use 5516.
- No weights replaced and config.json is byte-identical to V5.5.15.

## Why the broad stricter guard remains diagnostic
The unresolved-vehicle shadow flag is present on 44 of 46 GREEN starts (95.7%),
including all three logged successes and all four input-owned attempts.
It does not distinguish success from failure in this sample. Previous V5.5.14
analysis likewise found large opportunity loss under the broad unresolved-object
rule. Turning it on would likely reintroduce starvation; it is not a validated
accuracy improvement. Existing measured upstream trajectory vetoes remain active.

This build does not claim to fix the underlying prediction error on every bad GREEN.
The evidence establishes lost feedback, not a specific missed incoming trajectory
for every failure. More strictness is justified only when a candidate rule separates
causal failures from successes on held-out sessions. Failure learning can now receive
the tested delayed-reset case instead of silently losing it; improved live precision
still requires validation. No historical UNKNOWN labels are rewritten.

## Validation
See V5516_TEST_RESULTS.json. New regression uses signal 9's rounded timing and
positions, a confirmed reset and the recorded historical peak. It asserts one failure
feedback increment, no duplicate, no-input exclusion, real multi-jump exclusion,
continuous missing timeout, reacquisition and bounded expiry.
This is an outcome-component replay, not a pixel replay or a native Windows test.
The legacy test_v550_causal_landing.py fails on unchanged V5.5.15 as well; it predates
the later independent settled-landing requirements. It is not counted as passing.
Current landing-evidence tests are included in the current regression suite.

## Running and next validation
Close the old build, copy the existing data folder, and run start_v5516.bat.
Use Space for jumps. Keep input_audit_v5516.jsonl, state, crash, GREEN-outcome,
outcome-audit, signal-audit and safe-window logs together.
Evaluate confirmed in-window single-jump success/failure separately from UNKNOWN,
manual, late and chained actions. Track GREENs/minute alongside precision.
