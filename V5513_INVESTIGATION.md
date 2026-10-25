# V5.5.13 investigation

## Latest V5.5.12 run

Source files: state, session, crashes, events, safe_window and green_outcomes
20261023_031947; outcome_audit_v555(8), signal_audit_v558(5).

73.39 minutes; 13,344 state samples; 41 GREEN starts; nine observed/inferred
actions; six classified successes; nine UNKNOWN outcomes; nine logged resets.
Some UNKNOWN outcomes have no observed action, so these counts are not disjoint
attempt categories. There are no logged GREEN failures, but this is NOT evidence
that all attempted GREENs succeeded. No reliable overall success percentage
can be calculated from these files.

The crop recovery worked: CROSSING ROI INCOMPLETE occurs in 13 samples (0.097%),
versus 44.3% in the prior run. Tick errors remain zero.

## Suspicious outcomes omitted from the failure counter

Signals 2, 5, 17, 20, 22 and 30 show movement/vertical disruption near x=630,
then a return near x=190 without a recorded landing at the target near x=1070.
They become UNKNOWN viewport_change_without_observed_action. Signal 31 shows
a similar return and becomes UNKNOWN scroll_without_independent_landing_evidence.
These seven cases are consistent with early failed attempts, but the trace
alone cannot distinguish every reset from a viewport operation. Signals 16
and 41 also remain UNKNOWN; their third-lane transitions are ambiguous.

The action detector requires about 24% of a lane's horizontal displacement.
A collision before that movement can therefore escape observed-action
ownership. Reframing then makes its outcome UNKNOWN. Lowering that threshold
would risk reviving detector-wobble false actions. This patch leaves outcomes
unchanged rather than inventing failure labels or training on uncertain cases.
The nine reset rows are not automatically counted as GREEN failures either;
several occur well after the nearest cue and may be manual actions.

## Confirmed prediction wiring defects

MotionEngine.update returns only currently matched tracks with age >= 2 and
explicitly strips their history. main.py passed exactly this list to
predict_arrival. However, predict_arrival's early fast-vehicle path requires
two history observations. That branch could not work with production output,
even though its earlier isolated fixture tests supplied history directly.
Missing tracks were also absent before the predictor could consider them.
Thus an empty foreground frame could erase an incoming trajectory immediately.

Signal 22 illustrates the risk. At timestamp 1792707242.3673, session.csv logs
track 1706 at x=1102.5, y=210.5, height=285, downward vy=617.69. GREEN starts
at 1792707242.9704, roughly 0.60 seconds later, with no upstream trajectory.
Constant-velocity projection using that logged speed puts the vehicle within
the buffered crossing interval at GREEN start: approximate front entry 0.44s
and rear exit 1.25s after the observation (resting chicken y≈731, h assumed160
for this calculation). This is an illustrative projection, not video-confirmed
collision reconstruction: logs omit full history/direction flags and actual
click time. It establishes a concrete threat-continuity concern, not proof
that this exact track caused the user's crash.

## Change

MotionEngine.prediction_tracks supplies separate snapshots of retained tracks,
including immutable position histories. The standard observed-track stream
used for learning and existing risk evaluation is untouched.

Fresh two-point trajectories now reach the existing early predictor. Missing
tracks are extrapolated only if mature, direction-valid, non-suspicious and
in the target lane. The fastest measured velocity supplies earliest front
arrival; the slowest positive estimate supplies latest rear exit. After that
exit the track contributes no veto. Existing tracker expiry and ROI resets
also remove it. An immature missing blob is not extrapolated. This is a
trajectory-specific veto; no global ETA, confidence, lease or cooldown change.

This constant-velocity bound cannot anticipate arbitrary acceleration, a
stopped vehicle, a missed initial detection or a bad association. It may veto
some opportunities while an uncertain retained trajectory is still in its
predicted crossing interval. Live frequency and outcomes must be checked.

Signal audit events now retain predictor track snapshots and a monotonic
clock reference, allowing future investigation of speed, age, direction,
missing state and history at each cue. Existing CSV schemas are unchanged.

## Validation

The new regression uses real MotionEngine association with synthetic detected
positions, not prebuilt predictor-only track dictionaries. It demonstrates
that the old public output loses the two-point trajectory; the new snapshot
preserves it, retains a mature threat during loss, expires it after rear exit,
and clears it on ROI reset/tracker expiry. Immature lost tracks stay excluded.

All 16 regression scripts pass after updating one old assertion that expected
missing mature tracks to vanish immediately; it now checks retention and rear
exit. This includes actual application tick, landing/reframe, tracking loss,
ROI recovery, crossing occupancy, slow learning, missed rearm and final landing
checks. config.json is byte-identical to V5.5.12. No learned weights changed.
Tests validate code behavior, not a live gameplay success rate.
