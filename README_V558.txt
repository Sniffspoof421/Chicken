V5.5.8 — fresh traffic rearm after a missed GREEN

Run start_v558.bat in a new extracted folder using your existing Python setup.
Copy your previous data folder to retain trained models. Keep the original as
backup. No model reset is needed.

WHY CUES REPEATED
V557 deliberately allowed a new motion-cycle ID to bypass the missed-GREEN
cooldown. Each busy-to-clear cycle could therefore announce another GREEN on
the same stationary target, including a cycle already underway while the prior
cue was still resolving. The supplied burst 13–17 uses distinct cycles664–668,
not five announcements of one identical gap.

WHAT CHANGED
The normal first-cue prediction/admission is retained. After an unacted cue on
the SAME target, a new cue requires the existing unacted cooldown and a newly
observed busy-to-clear passage after that cue was classified as missed. Merely
changing the cycle counter or waiting does not rearm. Motion must be available,
geometry fresh/stable and the preceding occupancy must satisfy the existing
minimum busy duration. Invalid tracking cannot manufacture rearm evidence.
A genuine new target starts independently. No global ETA, lease, confidence,
probability, support, detector or difficulty setting has been increased.

A second or third cue is not inherently safe/unsafe. The change removes the
rapid rearm path; it is not a guarantee against a collision in a new gap.

AUDIT
signal_audit_v558.jsonl records cue starts, misses and action events. The
existing outcome_audit_v555.jsonl also retains UNKNOWN records for nearby resets
without observed actions. These unknowns do not train successes or failures.
State CSV now logs cycle ID, admission status/reason and missed-cue rearm state.
Predictor logs use v558; unexpected runtime errors use runtime_errors_v558.log.

RUN RESULTS
76.753 minutes, 36 registered GREENs, 13 attributed attempt records: 10 logged
successes, 1 tracking timeout, 2 chained/unvalidated. Logged success share of
attributed attempts is 76.9%; the remaining 23.1% is unresolved, not proven
failure. Of the 10 successes, 5 use direct target handoff and 5 inferred scroll
handoff. The10 resolved records alone show 100%, which is not a reliable physical
accuracy claim. The 13 independent reset records are not added as GREEN failures;
without click/video evidence not every one can be labeled manual play.
Read V558_INVESTIGATION.md for the exact limits and signal examples.

CHECKS
New missed-cue cooldown/fresh-passage/ownership tests pass, along with V551
convoy-tail, V552 degraded-FPS/progress handoff and V555 chronology/deadline unit
regressions. Modules compile. config.json is byte-identical to V557. Full Qt/
OpenCV application tests could not be rerun in this execution environment;
those tests remain included. Live-game prediction accuracy is unverified.

Use tools/summarize_green_outcomes.py PATH_TO_OUTCOME_AUDIT to report future
coverage. It excludes proximity-only resets from the attempt denominator.
