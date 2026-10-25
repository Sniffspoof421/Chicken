# V5.5.14 investigation

Source: all eight supplied 20261024_021103 files, including
outcome_audit_v555(9) and signal_audit_v558(6).

## Observations

28.52 minutes; 5,431 state rows; 15 GREEN starts; four recorded successes;
seven UNKNOWN outcomes. Two crash records exist, neither creates a classified
GREEN failure. Eight unacted events overlap some later unknown cases.
A reliable live success percentage cannot be established from these logs.
In particular, four logged successes and zero logged failures do not establish
100% success or invalidate the user's report of approximately 90% failures.

Incomplete crossing coverage occurs only twice; runtime errors are zero.
The earlier crop/exception defects are not the dominant problem in this run.

## Prediction limitation now visible in the new audit

At GREEN the retained histories are mostly fragmented one- or two-observation
tracks. Signals 1, 2, 5, 6, 9 and 15 include short measured trajectories followed
by new singleton IDs farther down the same column. Signal 6, for example,
records y=86.5 -> 201 over .0789741s, then another ID at y=605 after a further
.3349613s. These positions are consistent with one fast car, although only
video could prove object identity.

The actual tracker predicts each old track with the most recent LOOP dt,
capped at .25s, regardless of the time since that TRACK was observed. A track
missing several detections is therefore predicted too close to its old
location. The exponentially smoothed velocity can also substantially lag a
clean two-observation velocity. Its next detection falls beyond the existing
association radius and starts another ID. The upstream predictor then lacks
a mature trajectory despite having been correctly connected in V5.5.13.

The same timing error affects raw velocity: dividing displacement since the
last observation by a single frame interval overstates speed after a dropout.
For example, 40px over .8s is 50px/s, not 400px/s just because the latest loop
interval was .1s. This can damage speed classification, particularly early in
a slow vehicle track. It is a reproduced code defect; the supplied logs do
not establish how many missed opportunities it caused.

## Implemented repair

Association and raw velocity now use elapsed time since the individual track's
last observation. Clean recent two-point forward motion supplies association
prediction speed before the EMA catches up. Existing spatial association,
lateral/backward rejection and track expiry limits remain. The rule is for
matching detections, not a new GREEN admission shortcut.

A regression using the logged signal-6 positions with synthetic detector boxes
fails against V5.5.13 (two IDs) and passes here (one mature ID). A second
regression verifies a slow vehicle's 50px/s estimate after missed frames.
Synthetic detections do not reproduce every visual segmentation failure.
Singleton tracks with no usable motion history remain an unresolved case.

## Why the crash records did not teach the GREEN learner

v5_feedback_failures stays at 15 for all rows; v5_feedback_successes rises
from 77 to 81. The GREEN failure counter stays zero. record_green_outcome
accepts only success/failure; UNKNOWN returns without training.

Signals 5, 8, 9, 12, 13 and 15 are UNKNOWN without observed action, predominantly
following movement disruption and reset/reframe. Signal 3 is an ambiguous
progress-scroll handoff. Early collisions can fail to reach the existing
horizontal action-start threshold; a later reset cannot reliably identify
the input's owner. General crash-context learning and GREEN outcome training
are separate. Presence of a crash CSV does not mean that cue received negative
feedback. This patch does not convert unknown cases into invented labels.

Windows input diagnostics now record left mouse, Space, Up and Right press
edges, wall/monotonic observation times, cursor, foreground window handle,
last published cue, signal/target and whether its deadline had elapsed.
Polling runs in a separate daemon thread at nominal 10ms intervals, including
while the vision loop is busy. Only these control edges are observed; no
input is injected and no text is recorded. Held controls do not create
repeated events. The observer stops when the app closes.

These records are not hardware click timestamps or proof that the game
accepted input. They can include unrelated clicks and last-published rather
than physically-painted cue state. Linux does not enable this observer.
The Windows APIs require live Windows validation. Input/deadline record
logic is tested; no claim of a live Windows integration test is made.

## Before slow vehicles: recommendation

There are 113 rows with directional slow context. Eight are blocked by the
after-slow guard, 21 by occupied crossing, and 84 by upstream arrival. None
has a recorded upstream arrival beyond its required crossing horizon.
This cannot establish that the user-visible opportunities were unsafe;
tracking and speed measurement may be wrong. Correct measurement first.

Recommended next step: replay a separate before-arrival decision using a
fresh, coherent slow trajectory, all other incoming vehicles, the crossing
occupancy and remaining occupancy budget. Validate it against synchronized
input/outcome evidence before making it an admission override. An after-slow
historical gap rule should not substitute for before-arrival prediction.
No global ETA/lease/probability reduction is supported by this run.

For feedback, use a recorded in-game input during a valid cue together with
independent landing or reset evidence. Keep uncertain viewport changes as
unknown. This would admit early collision feedback without lowering the
horizontal movement threshold and reintroducing wobble-generated actions.
The present build collects the missing evidence; it does not yet automatically
train from input events.

## Preservation and limitations

config.json is byte-identical to V5.5.13. Outcome rules, slow-profile learner,
GREEN admission thresholds, model persistence, crop recovery, and existing
trajectory guard remain. No user models were erased or bundled. Speed values
can legitimately change because their observation timing is corrected.

The patch fixes reproduced tracking defects and adds the missing diagnostic
input stream. It does not establish that all bad GREENs are resolved. Live
success rate, cue frequency and Windows input capture must be checked in the
next run. Include input_audit_v5514.jsonl with the usual logs; a synchronized
recording is particularly valuable for ambiguous deaths versus scrolls.

Validation: the new regression passes and all 16 prior regression scripts
pass (17 total). The new association regression fails on V5.5.13 at the
expected split-ID assertion. Acceleration also uses elapsed observation time.
