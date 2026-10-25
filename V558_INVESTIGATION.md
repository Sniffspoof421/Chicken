# V557 efficiency and repeated GREEN investigation

Sources: the supplied state, predictor, session, events, crash, outcome and
JSONL audit files for the 20261022_025457 run. Source files were not modified.

## Efficiency excluding unassigned/manual-play crashes

| Measure | Recorded value |
|---|---:|
| Sampled state duration | 76.753 minutes |
| Registered GREEN signals | 36 |
| Attributed attempt records | 13 |
| Logged successes | 10 |
| Logged resolved failures | 0 |
| Tracking-timeout UNKNOWN | 1 (signal 10) |
| Chained/unvalidated | 2 (signals 19, 26) |
| Logged successes / attributed attempts | 10/13 = 76.9% |
| Separate reset detections | 13 |
| Runtime errors in published state | 0 |

The 76.9% describes recorded successful-outcome coverage, not verified physical
prediction accuracy. The remaining three attempts are unresolved, not proven
failures. Counting only resolved records gives 10/10, but advertising 100% would
hide these exclusions and weak attribution. Five successes use direct target
handoff (5,6,20,21,34); five use inferred scroll handoff (2,4,11,17,18).

The 13 separate reset detections are excluded from the GREEN failure denominator
because this run does not establish causal GREEN ownership for them. That
excludes manual-play resets as requested, but does not prove all 13 were manual.
For example, a reset about 2.2 seconds after GREEN 7 has no observed forward action
in the sampled trace. It remains ambiguous. Later reset geometry cannot be used
to invent a click or label it a definite GREEN failure. Signal 10's timeout also
precedes a later reset; it remains unresolved. A video or action timestamp trace
is needed to separate these cases reliably.

## Root cause of the burst announcements

Signals 13–17 occur on the same target ownership (switch 47), with cycle IDs
664,665,666,667,668. First sampled counter changes are approximately
1792620699.362,1792620702.026,1792620705.020,1792620709.734,1792620713.352.
That is five cues across roughly 14 seconds. Signals 23–25 are another same-target
sequence (switch 92), using cycles 878,880,885.

These are distinct motion busy-to-clear cycles rather than literal duplicate
announcements of the same cycle. V557's green_display_allowed method contains
an explicit exception: during the missed-cue cooldown, a different cycle ID
returns True. A different counter can therefore rearm immediately once the old
attribution grace ends. It does not require that the departing traffic passage
be observed AFTER the missed cue was resolved. This explains repeated cues
when the user stays on the same lane after missing one.

A cue's ordinal number is not a physical risk feature. The logs do not establish
that every third cue fails. Applying a global tighter ETA, or hardcoding every
third cue as unsafe, would not be supported by this run.

## V558 correction

After a cue becomes unacted, V558 waits for both the existing configured cooldown
and a newly observed busy-to-clear passage on the same target. A counter change
alone, time alone, short motion noise or invalid tracking cannot rearm it.
The busy duration reuses RiskEngine's existing gap_open_min_busy value; no new
global confidence/ETA/support requirement was introduced. A stable fresh new
target clears the prior-target missed-cue gate.

The guard is applied before indicator admission. Prediction and autonomous
traffic learning continue while announcements are withheld. Ongoing visible
signals and one-jump ownership retain their prior behavior. Target/cycle/rearm
reasons are logged so later bursts can be inspected without inferring IDs from
separate files.

## Honest outcome accounting

V557 silently discarded a reset when no active/provisional observed jump existed,
even if a recent GREEN was still pending. V558 records that proximity as UNKNOWN
with reset_without_observed_action in the outcome audit. It neither fabricates
an action nor trains a success/failure. Newly registered cues, missed cues and
action events have a separate signal audit. These records are meant to expose
coverage gaps rather than make efficiency appear better by excluding failures.

Manual successful jumps remain supplemental at their existing weights. V556's
landing callback and V557's missing-tracking initialization fixes are retained.
config.json is byte-identical to V557. No trained model file was supplied or
changed. Existing final landing locks remain irreversible.

## Verification and remaining limits

Passed: new V558 missed-cue/fresh-passage/noise/target-scope/reset-audit tests;
V551 convoy-tail, V552 degraded-FPS/progress-handoff and V555 chronology/deadline
unit regressions; Python module compilation; configuration byte comparison.
The included audit summary tool reproduces 13 attempt records, 10 successes and 3
unresolved from the supplied audit. Full Qt/OpenCV application tests could not
be rerun in this execution environment; the existing integration tests remain
included. No live Windows gameplay run was performed here.

This change targets the proven burst-admission mechanism. It does not prove that
future incoming-vehicle detection or late-stage physical jump safety improved.
Incomplete action visibility, inferred scroll ownership and unseen traffic are
still limits on measuring and predicting collisions. The new build should be
evaluated on a fresh run without treating all unassigned resets as manual play
or reporting resolved-record 100% as physical efficiency.
