# V5.3.4 analysis — zero GREEN root cause

Input run analysed:
- `state_20261013_013014.csv`
- `safe_window_v533_20261013_013014.csv`
- `session_20261013_013014.csv`
- `events_20261013_013014.csv`
- `crashes_20261013_013014.csv`

## What the run proved

The ~12.77 minute V5.3.3 run produced **zero GREENs**. This was not caused by the chicken anchor fix itself and was not primarily an ML probability-threshold issue.

The V5 SafeWindow log had **5,413 evaluations and zero `hard_ok` frames**. The dominant blockers were:

- `LIVE GAP UNVERIFIED`: 3,184
- `PHYSICAL ETA`: 1,330
- `VISION/VIEWPORT`: 439
- `TRACK REWARM`: 279
- `CLEAR LEASE`: 160

Because there was never a `hard_ok` state, the current-session V5 learner stayed at **0 training samples** for the whole run. No threshold adjustment could fix that deadlock.

## Root cause 1 — stale historical speed made physical ETA impossible

The clear-zone geometry itself was healthy: the visible upstream road distance was typically about **635 px**.

But V5.3.3 forced the CZN speed reference to **700–740.83 px/s** because the current CZN speed was maxed with old persisted/stage speed history.

That made the clear-zone ETA:

`~635 / 700 * 0.88 = ~0.80 s`

Telemetry confirms:
- median `effective_eta`: ~0.7975 s
- maximum `effective_eta`: ~0.9025 s
- V5 absolute minimum ETA: 1.08 s
- typical V5 required ETA: ~1.12–1.13 s

Therefore a clear-zone state could **never** pass the physical ETA gate, even if the target lane was visibly empty.

This historical speed was not representative of the current run:
- current `regime_speed_p90`: ~84.16 px/s
- median current raw CZN p95: ~294.35 px/s
- historical/stage physical reference: 700–740.83 px/s

The same architectural problem fixed in V5.3.2 for ML weighting still existed independently in the risk/ETA layer: old session history remained the hard physical authority.

## Root cause 2 — strong motion evidence could be rejected before its override

V5.3.3 intentionally allowed strong raw-motion gap history to substitute for sparse CZN crossing events in the observed-clear physical override.

However `_live_gap_verified()` required `czn_live_ready` before that override could be reached. During bootstrap this could produce:

`strong motion gap -> CZN not ready -> LIVE GAP UNVERIFIED -> override never evaluated`

That is a control-flow deadlock.

The run had useful raw-motion evidence despite sparse crossing events:
- median motion gap support: 10
- 75th percentile support: 34
- median motion gap P25: ~1.58 s
- 75th percentile motion gap P25: ~1.81 s

Only one confirmed crossing event was recorded, so the model must be able to bootstrap cautiously from strong independent target-ROI motion evidence instead of waiting indefinitely for tracker crossing events.

## V5.3.4 corrections

### 1. Current-session CZN speed authority

Physical clear-zone ETA now uses current-session evidence:
- startup physical speed floor;
- current adaptive/regime speed;
- current confirmed event speed when available;
- current raw incoming-track speed when available.

Historical p95 is only a **bounded cold-start prior**:
- with zero live support: at most 1.25x / +90 px/s above the live floor;
- with one live support item: at most 1.12x / +50 px/s;
- with >=2 live support items: historical p95 has no hard-max authority.

The old `max(CZN speed, stage historical speed)` is removed. Stage history remains available for difficulty/context, but cannot dictate the physical ETA of the current target lane.

### 2. Strong-motion bootstrap path

An empty lane can now be live-gap verified without CZN crossing readiness only when the independent motion evidence is strong:
- live motion profile ready;
- real busy->clear transition;
- sufficient preceding busy duration;
- strong gap support;
- strong lower-tail gap P25;
- current corridor motion near zero;
- current MOG foreground ratio near zero.

Weak motion history still waits for ordinary CZN/live verification. This is not a global threshold relaxation.

### 3. Diagnostic telemetry

Added:
- `czn_live_speed_reference`
- `czn_historical_speed_p95`
- `czn_historical_prior_applied`
- `czn_speed_reference_source`
- `czn_live_speed_support`
- `czn_stage_speed_reference`

The SafeWindow log is now named `safe_window_v534_*.csv`.

## Offline replay of the failed run

Using the original V5.3.3 telemetry, reconstructing the V5.3.4 CZN speed authority while keeping the **old V5.3.3 probabilities** (therefore conservative because the improved ETA would also improve the heuristic feature):

- corrected median clear-zone ETA: ~1.314 s
- corrected 75th percentile ETA: ~1.325 s
- corrected max ETA: ~1.612 s
- states passing all reconstructed V5 hard/final physical gates: **298**
- observed-clear frames satisfying the existing evidence-qualified physical override: **141**
- those 141 frames form ~19 candidate windows
- **18 windows** last at least the current ~0.28 s V5 commit requirement
- longest reconstructed candidate window: ~4.68 s

This replay is diagnostic, not a guarantee of exactly 18 visible GREENs, because live indicator/rearm/outcome timing still operates at runtime. It demonstrates that the deterministic zero-GREEN wall is removed without lowering the global GREEN threshold.

## Regression tests

Passed:
- V5.3.4 current-session CZN speed authority + strong-motion bootstrap
- V5.3.3 chicken-authoritative geometry
- V5.3.2 two-timescale session learning
- V5.3.1 progress-scroll / Hardcore ETA handoff
- V5.3.0 self-advancing target
- V5.2.9 outcome / slow / stable GREEN lease

The trained model schema is unchanged. Continue using:
- `online_state_v532.joblib`
- `safe_window_v532.joblib`

Do not reset those models solely for this build.
