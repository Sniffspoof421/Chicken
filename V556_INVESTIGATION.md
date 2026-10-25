# Why V555 appeared stuck after a successful jump

The previous changes addressed outcome ownership and display expiry but missed
a runtime exception in the successful-jump path. The new build fixes that
exception rather than adjusting GREEN thresholds or freezing coordinates.

## Reproduced cause

Inside App.tick, the manual-success bridge called:

    self.outcome.confirm_validated_manual_success(learning_chicken, wall_now)

The same function assigned learning_chicken only later, in the crash/outcome
section. Python therefore raised:

    UnboundLocalError: cannot access local variable 'learning_chicken'
    where it is not associated with a value

This branch is reached after the chicken has landed on the original target and
remained stable for 0.52 seconds. The exception occurs before passive_jump is
cleared and before log_state and self.last/UI are updated. On the next timer
call, the same landed branch can raise again. Its timeout is in an elif branch,
so remaining correctly landed does not escape the repeated exception. Moving
the screen/chicken can change the condition and let the code resume. That
explains why a coordinate change could appear necessary to unstick the widget.

The failure is independent of whether supplemental manual learning is enabled:
the GREEN success bridge is outside that configuration guard.

## Evidence in the supplied run

Sources: state_20261021_232255.csv, safe_window_v555_20261021_232255.csv,
green_outcomes, green_failures, crashes, session, events and outcome audit.

The state file covers approximately 82.686 minutes. There are 15 gaps longer
than one second with at least four predictor records inside each gap. The
largest is 105.441 seconds (1792607822.351143 to 1792607927.792350), containing
646 predictor updates. A further gap lasts 27.784 seconds with 169 predictor
updates. After the first recorded successful GREEN, the state file jumps from
1792605284.085029 to1792605289.539566 while the predictor continues processing.

This shows that analysis could continue before the final state/UI publication
was reached. It is consistent with the reproduced exception. Without the
original console traceback, it does not establish that every individual gap
had the same cause.

The run also records actual GREEN-associated failure candidates, including
signals 5, 171 and 202 marked training-eligible. This patch does not relabel these
as successes or claim their physical collisions are solved. Correcting the
update failure is necessary to get current target geometry and current signals
onto the screen; it is not proof of collision prediction accuracy.

## Changes

The successful-jump bridge now receives fresh_chicken, already established and
validated before entering that branch. The rest of the update can complete and
clear the completed jump. No coordinate clamp, detector reset, model reset or
new GREEN admission floor was introduced.

The Qt timer also calls _run_tick, which catches and records future runtime
errors, revokes displayed GREEN, marks the old coordinates as not freshly
confirmed and shows TRACK ERROR. It retries on the next tick. Persistently
failing code stays visibly in error; it cannot silently preserve an old CLEAR.
The log includes the traceback and update phase in runtime_errors_v556.log.

## Validation

The supplied V555 code was run with the complete application tick, a controlled
camera and fresh landing observations. It reproduced the exact UnboundLocalError
at the success bridge. The corrected full tick then completed both the first
and second landing, advanced the next target correctly and continued through a
third-lane screen reframe. Small changing Y values were included in this test.
An injected update exception produced TRACK ERROR, revoked GREEN, wrote its
traceback and recovered on the following successful update.

V551 convoy-tail, V552 degraded-FPS/progress handoff, V553 gap prior/rearm/schema,
V554 landing lock/upstream, V555 deadline/reset chronology and actual Qt expiry
callback regressions pass. Python modules compile. config.json is byte-identical
to V555. No trained files were supplied or changed. Tests do not simulate real
vehicle images, click latency or a live Windows gameplay session.

Run tools/test_v556_full_tick.py to repeat the new application-level test.
Its optional first argument can point to an earlier build; V555 reproduces the
original exception. The other historical tests remain in tools. Old V549/V550
expectations already superseded in prior builds are not claimed as passing.
