# V5.4.0 Analysis — First-Jump Handoff + Missed Opportunity Fix

## Supplied V5.3.9 run

Duration: about 21.4 minutes.

The run exposed two separate failures.

### 1. Successful first jump remained stuck in JUMPING

Signal 3:
- GREEN baseline chicken X: ~193.06 px
- movement detected at X: ~335.04 px
- one-lane landing observed at X: ~630.10 px
- target switched from ~608.5 px to ~1072.44 px
- target lock reason: ARRIVED
- target switch counter: 1 -> 2

That is direct geometry evidence that the chicken reached the previously locked
next lane and the target advanced to the following lane.

However, V5.3.9 still kept the outcome tracker in JUMPING for ~4.17 seconds,
because success required additional fresh chicken frames. Chicken detection went
stale after landing, so the success dwell never completed. The later return to
the left was then logged as `jump_regression_reset`, even though the one-lane
landing had already happened.

## 2. GREEN opportunities were still starved

The V5.3.9 SafeWindow run contains:
- 9,051 decision evaluations
- only 6 visible GREEN IDs
- each visible GREEN appears for only one state-log frame

The dominant blocker was `FORECAST ETA`: 5,235 rows.

For a very large portion of those rows:
- effective ETA was ~1.42 s
- universal observed-clear minimum was 1.58 s
- current motion corridor was empty
- raw risk was around 11–12
- motion-gap support was mature
- gap P25 was commonly around 1.7–2.0 s
- no visible or uncertain vehicle was present

Using the new strict sustained-clear conditions on this exact run identifies
about 2,358 physically mature candidate frames across ~168 clear episodes;
~132 of those episodes lasted at least 0.6 s. This is not a blanket threshold
reduction: the override requires strong live gap history, sustained current
clear dwell, low raw risk, low MOG and low corridor motion.

## V5.4.0 changes

### Target-arrival success handoff
An acted GREEN now stores its signal-time target and target-switch counter.
When the lane lock reports ARRIVED, the target switch increments, viewport is
unchanged and chicken displacement matches one jump, the outcome closes as
SUCCESS immediately.

### Missing-CV release
If chicken detection disappears during an active attempt for >1.25 s without
landing proof, the outcome becomes UNKNOWN and the UI is released. It is never
trained as a failure.

### Bounded actionable GREEN hold
A committed GREEN may remain visible for at least 0.75 s through a policy-only
ETA/provenance transition, but only while the base physical hard gate remains
safe and ETA stays >=1.20 s. Real physical hazards still cancel immediately.

### Mature sustained observed-clear admission
The 1.58 s floor remains for generic observed-clear states. A lower 1.40 s floor
is allowed only with:
- current clear >=1.00 s
- motion-gap support >=20
- gap P25 >=1.70 s
- heuristic probability >=0.90
- raw risk <=18
- motion corridor <=0.04
- MOG <=0.055

### Policy cleanup
Attribution/feedback policy version is 540. Pre-540 GREEN-only failure counters,
source failure ETA floors and direct SafeWindow failure prototypes are cleared
once. Successful and general traffic learning is preserved.

## Regression tests

Passed:
- V5.4.0 target-arrival handoff / missing-CV release / sustained-clear / GREEN hold
- V5.3.9 verified physical override
- V5.3.8 causal GREEN attribution + fullscreen reframe
- V5.3.7 verified-gap fast path
- V5.3.6 GREEN reliability
- V5.3.5 fullscreen reframe
- V5.3.4 root-cause speed/bootstrap
- V5.3.3 chicken-authoritative geometry
- V5.3.2 recent-session adaptive learning
- V5.3.1 progress-scroll Hardcore behavior
- V5.3.0 self-advancing target

## Run

Use `start_v540.bat`.

Keep:
- `data/models/online_state_v532.joblib`
- `data/models/safe_window_v532.joblib`
