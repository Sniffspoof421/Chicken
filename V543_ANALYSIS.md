# V5.4.3 root-cause analysis

## Supplied V5.4.2 run

Duration: ~38 minutes.

Observed behavior:
- 179 verified physical gap cycles.
- 16 cycles produced GREEN.
- 35 CLEAR state frames total.
- 342 verified SafeWindow frames rejected as `ACTION LEASE`.
- No acted GREEN outcome was recorded in this run.

Verified-gap physics were generally strong:
- dynamic-gap remaining time median: ~2.07 s
- dynamic required ETA median: ~1.81 s
- physical heuristic median: ~0.942
- motion-gap P25 median: ~2.35 s
- raw risk on verified frames: 2
- target-lane motion and MOG were essentially zero for most verified frames

## Root cause

`dynamic_gap_required_eta` already includes:
- jump crossing time
- safety buffer
- learned source reaction delay
- measured pipeline latency
- stage/guard terms

In this run the learned reaction budget was already capped at 0.72 s and
measured pipeline latency was ~0.157 s, producing required ETA around 1.81 s.

V5.4.2 then required an additional flat 0.55 s SafeWindow action lease. This
raised practical admission to roughly 2.36 s and rejected the majority of real
verified gaps. The lease was intended as a presentation reserve, but became a
second reaction margin.

## V5.4.3 correction

Two-tier admission:

### Strong physical verified gap
Extra lease = max(0.32 s, FPS frame reserve, RiskEngine lease floor).

This tier still requires the existing strict V5.4.2 physical evidence:
- verified busy->clear dynamic gap
- physical heuristic >= 0.94
- dynamic confidence >= 0.78
- motion gap support >= 10
- gap P25 >= 2.20 s
- raw risk <= 12
- target-lane motion <= 0.03
- MOG <= 0.04
- all ordinary hard vetoes clear

### Standard / ML-only verified gap
Extra lease = max(0.42 s, FPS frame reserve, RiskEngine lease floor).

This preserves a larger reserve for states that do not have exceptional live
physical proof.

## Replay impact

Replaying the supplied V5.4.2 telemetry against the new strong tier identifies
about 49 qualifying verified cycles versus 16 admitted by V5.4.2, recovering
roughly 33 additional strong opportunities.

Observed-clear logic is unchanged; this fix does not reopen the V5.4.0 crash
path.

## Tests

Passed:
- V5.4.3 adaptive verified lease
- V5.4.2 anti-jitter / strong-gap / cycle-aware rearm
- V5.3.9 physical override
- V5.3.8 causal outcome/reframe
- V5.3.7 verified-gap fast path
- V5.3.5 fullscreen reframe
- V5.3.4 current-session CZN authority
- V5.3.3 anchor geometry
- V5.3.2 recent adaptation
- V5.3.1 progression
- V5.3.0 target advancement

Older tests that intentionally expect tiny pre-V5.4.2 chicken movement to own a
GREEN action remain superseded by the lane-scaled anti-jitter behavior.
