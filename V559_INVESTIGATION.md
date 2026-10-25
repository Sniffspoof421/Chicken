# V558 late-lane report and slow-learning investigation

The sources are the ten supplied files: predictor/state/session/event/outcome/
crash CSVs, both audit JSONL files and the two joblib model snapshots. Original
files and trained weights have not been modified.

## What this run can establish

The state trace spans 22.861 minutes and has zero runtime errors. There are 15
registered GREENs, four attributed actions and four logged successful outcomes
(signals 1, 8, 9, 13). Signals 1 and 8 have direct target-switch landing proof; 9 and 13
use scroll-handoff inference. Eleven cues are logged unacted. Four records are
not sufficient for a physical efficiency estimate, and the inferred outcomes
must not be advertised as verified 100% jump accuracy.

All four reset detections form a short sequence at 1792624399.038616,
1792624401.080890,1792624403.143297 and1792624406.339496. The preceding GREEN is
signal 12 at 1792624354.895258. Its missed-cue event is at 1792624357.402046.
The resets follow 44.14–51.44 seconds after that GREEN started, with no subsequent
registered GREEN until signal 13 at 1792624517.187951. These records cannot
causally identify those resets as executions of an active GREEN. They also do
not prove the user's observed failures did not occur. No click trace or video
was supplied. Local lane IDs repeat after scrolling, so target-switch counts
also cannot reliably locate the global fourth/fifth gameplay lane.

## Concrete slow-profile defect

Live slow geometry selects vehicles with forward_class. Historical
slow_anchor_profile instead selected anchors using class, computed from total
tracked speed. Both fields already exist in the saved history.

Among 1,069 retained non-reset events there are 185 disagreements:

| Stored total-speed class | Stored forward class | Events |
|---|---|---:|
| S | M | 77 |
| M | F | 47 |
| F | M | 30 |
| M | S | 25 |
| F | S | 6 |

Thus 77 records used as slow anchors carry a medium forward classification;
31 other physically classified-as-slow forward records were omitted from that
profile. Follower classification disagreed too. These are disagreements between
measured estimates, not externally verified vehicle ground truth.

The current run often has a large inherited slow-profile support count
(up to 260), but the profile reports lower-tail gaps around 1.01–1.02 seconds and
blocks after-slow windows whose existing requirement is about 1.29–1.30 seconds.
Only 10 sampled state rows select slow-after and none select slow-before. This
does not justify lowering the safety requirement. It does justify correcting
which examples train the slow profile and letting mature current-context
examples adapt instead of pooling all old segments indefinitely.

## V559 changes and scope boundaries

The directional slow profile uses forward_class for anchors and followers;
legacy records without that field fall back to class. Recent current-segment
pairs in a 180-second window take priority only after the existing local support
minimum is met, or twice that minimum for current global evidence. Sparse new
patterns retain historical fallback. Fast followers, short headways and reset
boundaries are included/handled rather than learning only positive cases.

This profile is selected only with a current slow candidate or a confirmed slow
pass in the preceding 2.5 seconds. Otherwise the original profile calculation is
used, including its confidence formula. A test against the exact V558 method
confirms matching old profile fields for every saved lane in ordinary traffic.
No configuration thresholds or learned classifier weights were changed. The
existing slow-after body clearance, follower timing, physical ETA and fast-car
vetoes remain authoritative. The recent profile cannot itself authorize a jump.

## Learning persistence evidence

The attached online_state_v532.joblib contains 77 supervised samples and 2,635
pattern events, matching the beginning of the run. The last state row contains
86 samples and 2,664 events. This proves that the attached online snapshot trails
the live run; it does not prove a save failure because the app may still have
been running when the file was copied. Existing configuration disables routine
in-run online-learner model saves. The safe-window snapshot separately records
its own learner and should not be confused with the online traffic model.

V559 adds infrequent idle checkpoints to reduce exposure to interrupted exit.
The checkpoint requires a stable fresh chicken, healthy processing, no current
GREEN/V5 decision, no active jump/rearm and no scroll context. It reuses the
existing atomic temp-file/replace save behavior. A deep-copied snapshot is frozen
on the application thread; serialization and disk I/O run in one background
worker, without concurrent writes. Normal shutdown joins the worker before
saving final state. Failure preserves the previous model and is visible in
checkpoint status fields.

With the provided model, a synchronous save took 0.676 seconds in this environment,
so that write was moved off the GUI thread. Snapshot preparation/dispatch took
0.322 seconds in the measured background test. These are local measurements,
not Windows timing guarantees. Checkpoints occur during idle states and do not
run on every jump or frame. The existing explicit save-during-run option retains
its original behavior if the user has enabled it.

## Verification

New tests pass for correct forward anchor/follower classes, no reset bridging,
legacy-field fallback, mature/sparse recent contexts, dangerous recent followers,
idle-only checkpoint admission, atomic failure preservation, coherent nested
snapshot copying during live updates and no overlapping background writes.

Regression tests pass for the existing slow-profile and slow-before/fast-follower
geometry; V551 convoy-tail maturity; V552 degraded-FPS/progress handoff; V553 gap
prior/rearm/CSV schema; V554 landing lock/upstream guard; V555 chronology/deadline
and real Qt expiry callback; V556 full application landings/reframe/error recovery;
V557 full application tracking loss/reacquisition; and V558 missed-cue rearm.
Final schema and application tests were rerun after checkpoint refactoring.
Modules compile and config.json is byte-identical to V558. The supplied histories
remain unchanged. No model retraining or source-file replacement was performed.

This update fixes demonstrated slow-learning inconsistency and retention risks.
It cannot establish or promise that the reported late-lane physical collisions
are solved. A screen recording with the widget visible at the actual failing
jump is needed to resolve the remaining difference between observed gameplay
and the attributed events in these files.
