# V5.2.4 analysis of 2026-10-10 22:36:40 run

## Run summary
- Duration: ~87.66 minutes.
- 15,256 state rows, 29,299 V5 safe-window rows.
- Only 4 visible GREEN episodes were captured in state telemetry, despite 24 V5 committed episodes in state / 25 in the V5 log.
- Three crashes were recorded; this run added zero new GREEN failure labels, so the user-observed failed signals were not causally represented in the learner.

## Late-game no-signal cause #1: processing collapse
A continuous processing-unhealthy interval ran from ~49.89 to ~72.13 minutes, median ~2.37 FPS. During 50-70 minutes V5 produced zero raw safe decisions because PROCESSING is a hard safety veto. This is correct behavior at that refresh rate; V5.2.4 reduces sustained CV work rather than weakening the safety gate.

## Late-game no-signal cause #2: internal gap consumption
After processing recovered (~72-80 min), V5 produced 47 raw SAFE states and 11 committed states but zero visible GREENs. Repeated committed rows were blocked with `GAP ALREADY SIGNALED - WAIT NEXT VEHICLE`. The legacy indicator treated `v5-safe-window` like `dynamic-gap` and consumed an evidence cycle internally, including cases where downstream one-jump/rearm logic hid the CLEAR from the user.

V5.2.4 leaves one-shot dedup only on legacy `dynamic-gap`. V5 has its own commitment plus GreenJumpOutcomeTracker admission/rearm semantics.

## Late-game difficulty error
Near the end of the run, recent event p95 speed reached ~350 px/s while raw CZN p95 temporarily fell near ~33 px/s; live difficulty collapsed to ~0.04. V5.2.4 uses 90% of recent pass-event p95 as a backup speed observation when larger than raw CZN p95. Historical/all-session speed is not used for this fallback.

## Performance changes
- chicken work-band scale 0.60; replay benchmark at 2560x1600 reduced median chicken detection from ~21 ms to ~13 ms while retaining comparable coordinates.
- lane marking refresh 3 -> 12 frames once locked.
- skip locked lane rescan and noncritical unsupervised observation during low-FPS recovery.
- added processing stage telemetry so any remaining slowdown can be localized on the next run.

## GREEN failures not entering the learner
This run increased total crash learning by 3 but `green_failures_learned` and V5 direct feedback did not increase. V5.2.4 adds a low-confidence crash-progress fallback: if a still-recent displayed GREEN exists and CrashDetector proves material forward movement before a reset, the failure is linked to that signal even when the action-onset frame was missed. Viewport invalidation still clears attribution, and the fallback requires substantial progress plus a short time window.
