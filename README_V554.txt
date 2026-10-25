V5.5.4 — final landing ownership and upstream trajectory guard

Run start_v554.bat (same Python environment/dependencies as V5.5.3).
Extract into a NEW folder. Copy your existing data/model folder into this
folder if you want to retain learning; keep the original build as backup.
The model paths and config.json are unchanged. No learned files are included.

CHANGES
1. An owned action that reaches its original target within the existing
one-lane envelope, with exactly one target-switch advance and no intervening
viewport rebase, resolves immediately as success / SUCCESS_FINAL. This also
promotes an existing provisional landing. Later reset/reframe observations
cannot change the completed outcome because it no longer owns an attempt.
Coordinate-only landings without target handoff retain the prior validation.
Synthetic progress-scroll ownership retains its existing grace validation.

2. Fresh direction-valid vehicle tracks across the existing upstream lane ROI
are projected to the crossing zone using the fastest of measured smoothed,
fitted and net forward velocities, vehicle/chicken extents and track age.
An arrival inside the EXISTING required action horizon vetoes GREEN, after
V5/recovery overrides and before indicator admission. No track does not imply
safe: all baseline checks still apply. Passed, stale, missing and other-lane
vehicles cannot generate this veto. No historical gap is used as a trajectory.
This is constant-velocity prediction of visible traffic, not a guarantee
against unseen cars, acceleration, missed detections or click timing errors.

PRESERVED
config.json is byte-for-byte V5.5.3. ETA/lease/support/probability/cooldown and
regime floors are unchanged. Autonomous observation/gap learning and low-weight
manual-success learning are unchanged. The new physical veto can reduce GREEN
count when a measured incoming trajectory conflicts with the jump horizon.

LOGS
state CSV adds upstream_arrival_eta, upstream_threat_id,
upstream_required_seconds, upstream_prediction_available and
upstream_prediction_blocked. Outcome CSV adds outcome_state/landing_source;
outcome remains success for learner compatibility. Safe-window logs use v554.

VALIDATION
New synthetic ownership/trajectory tests and V553 regression tests pass.
The historical V550 test asserts provisional target-switch outcomes and is
superseded for that behavior by tools/test_v554_final_upstream.py.
This build has not been validated on live gameplay or the original run CSVs.
The supplied summary's signal 11/20 interpretations remain hypotheses.
For the next run, retain state, green_outcomes, crashes, green_failures,
safe_window_v554, events and session logs plus a screen recording.

Historical V549 preservation test fails at the same lease assertion in both
the supplied V553 and this build (0.54553 vs old expected 0.46–0.48).
V551, V552, V553 and new V554 tests pass.
