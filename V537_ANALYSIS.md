# V5.3.7 analysis — verified-gap admission/display deadlock

Run analysed: `state_20261013_065757.csv`, `safe_window_v534_20261013_065758.csv`, `events_20261013_065757.csv`, `crashes_20261013_065757.csv`, and session telemetry.

## What the run proves

The V5.3.6 progressed-lane evidence-reset bug is fixed in this run:

- duration: ~18.99 minutes;
- `motion_gap_support` reached 53 (median 39), so traffic evidence is no longer being wiped continuously;
- `dynamic_gap_ready` became true repeatedly;
- chicken anchor was stable ~95.5% of logged states;
- only 16 actual lane-phase realignments occurred while ~7,696 unnecessary phase corrections were suppressed;
- target geometry was valid for almost the entire run.

So the absence of visible GREEN is no longer caused by target/chicken geometry or lack of learned live-gap support.

## Actual zero-GREEN root cause

V5.3.6 had two sequential waiting layers for the SAME verified gap:

1. RiskEngine detected a physical busy -> clear transition, estimated the remaining gap, checked visibility/MOG/raw risk, and created a `dynamic_gap_action_lease`.
2. SafeWindow then required another `motion_clear_dwell >= 0.30 s`.
3. After that, SafeWindow required another ~0.28-0.34 s sustained commit.

At this run's ~3 FPS processing cadence, those duplicate waits consumed roughly 0.6 s before display.

The clearest example in the telemetry:

- first verified frame: remaining gap ~2.729 s, extra action lease ~0.919 s, corridor clean, probability ~0.932 -> rejected as `V5 CLEAR LEASE`;
- next frame: remaining ~2.489 s, lease ~0.679 s, probability ~0.897 -> only starts SafeWindow commit;
- next frame: remaining ~2.195 s, lease ~0.385 s -> finally becomes CLEAR;
- following frame: `dynamic_gap_ready` has ended, source falls back to `observed-clear`, clear-zone ETA ~1.424 s is compared with the strict 1.58 s forecast floor -> GREEN terminates immediately.

Result: the only logged CLEAR episode lasted one processed row. Two internal signals were registered, but the user effectively saw no usable GREEN.

## Why V5.3.6 became too strict

The 1.58 s observed-clear floor was intentionally added after V5.3.4 produced unsafe marginal GREENs. That part is retained.

The mistake was applying the same extra maturation concept to `verified-gap`. Dynamic-gap already contains the strong evidence that observed-clear lacks:

- a real preceding busy period;
- current clear target ROI;
- learned gap lower bound;
- remaining-gap calculation;
- full required ETA including reaction/pipeline reserve;
- explicit extra action lease;
- visibility, MOG, uncertain-vehicle and raw-risk checks.

Waiting another clear dwell + commit after those checks is duplicate safety latency rather than new evidence.

## V5.3.7 correction

### 1. Verified-gap fast path

When `dynamic_gap_ready == 1`, SafeWindow no longer requires its separate 0.30 s motion-clear dwell.

### 2. No second commit dwell

A dynamic-gap that has already passed RiskEngine's physical checks uses a 0-second additional SafeWindow commit. This is not an instant blind GREEN: the RiskEngine verification itself is the maturation step.

### 3. FPS-aware actionable lease

A NEW verified-gap GREEN must have enough extra start-time margin to survive at least one processing frame:

`max(config minimum, 1/FPS + 0.04 s, RiskEngine lease floor)`

The configured absolute minimum is 0.28 s. At ~3 FPS this naturally becomes roughly 0.35-0.40 s.

This rejects a gap that is already expiring while avoiding the V5.3.6 double-wait.

### 4. Same-gap continuation

Once a verified gap is GREEN, the same dynamic-gap cycle may continue while RiskEngine still considers it ready even after the extra admission lease shrinks. It is not forced to satisfy the admission reserve again every frame.

A short bounded hold also preserves `verified-gap` provenance when the dynamic-gap source drops one frame after admission, preventing an immediate switch back to the 1.58 s observed-clear rule. The hold is bounded by the action lease and a 0.75 s maximum.

### 5. Hard hazards remain immediate

The fast path does NOT bypass:

- visible vehicle;
- uncertain vehicle;
- target/viewport/tracking rewarm;
- motion/MOG hazard;
- raw-risk hazard;
- slow-after / slow-approach guard;
- crash-memory hard veto;
- processing failure.

Any such hazard ends GREEN immediately.

### 6. Observed-clear remains strict

V5.3.7 does not lower the 1.58 s `observed-clear` or tracked-forecast ETA floor. The unsafe V5.3.4 path is therefore not reopened.

## Offline projection from this run

Using the recorded V5 probabilities plus the corrected verified-gap physical admission logic, the run contains multiple distinct verified busy->clear windows that were previously blocked only by duplicate `CLEAR LEASE` / commit waiting. The strongest cluster had extra action leases roughly 0.77-1.12 s and probabilities ~0.88-0.98.

This projection is diagnostic, not a promise of a fixed number of displayed GREENs: outcome/rearm rules and real-time user action still affect display frequency.

## Regression status

Passed:

- V5.3.7 verified-gap fast path / FPS-aware lease / hard-hazard cancellation;
- V5.3.6 expired-GREEN attribution and policy migration;
- V5.3.5 fullscreen third-lane reframe;
- V5.3.4 current-session CZN speed authority / motion bootstrap;
- V5.3.3 chicken-authoritative geometry;
- V5.3.2 two-timescale session adaptation;
- V5.3.1 progress-scroll / ETA handoff;
- V5.3.0 self-advancing target;
- V5.2.9 outcome geometry / stable GREEN lease.
