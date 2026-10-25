# V5.5.18 investigation

## Accuracy across the supplied sessions
| Run | Minutes | Painted GREENs | Tracked attempts | Logged success | Logged failure | Unresolved tracked attempts |
|---|---:|---:|---:|---:|---:|---:|
| 20261025_013055 | 65.34 | 34 | 13 | 4 | 3 | 6 |
| 20261025_025200 | 16.53 | 9 | 4 | 1 | 0 | 3 |
| Combined | 81.87 | 43 | 17 | 5 | 3 | 9 |

Raw resolved log rate: 5/8 = 62.5%. This is not whole-session prediction accuracy.
Only four attempts have recorded in-window Space ownership, all in the first run:
signal 1 failure, signal 9 UNKNOWN, signal 20 UNKNOWN, signal 25 success.
The strongest resolved subset is therefore 1/2 = 50%, with two of four unresolved.
That tiny, selected subset cannot establish general performance.
Neither all 17 crash-detector events nor all 43 cues are valid accuracy denominators.
Manual crashes and unacted cues are not counted as GREEN failures.
All four input-owned attempts were backed by the input audit; late CV-attributed
successes are not promoted to input-verified successes.

## Painted cue usability
43 painted starts and 43 painted ends were logged. Median painted interval 0.341 s,
minimum 0.120 s, maximum 0.692 s. 27 of 43 were shorter than 0.4 s.
These are application paint timestamps, not independent monitor/video observations.
They support the user's report of fleeting/vague cues; ten internal signals need
not mean ten practically usable opportunities. No artificial GREEN extension is applied.

## Failure-by-failure findings
First run, signal 1:
Space 1792872110.1066978 was recorded CLEAR, before the input snapshot's deadline
1792872111.1548643; paint end was 1792872110.1923444. The input was in GREEN.
The chicken reached roughly x637,y790, without settled ground-height landing, then
returned to x190. A regression failure is supported; it must not be excluded as late.
The old logical end_ts was 1792872110.0101125, earlier than the press. OnlineLearner
used that timestamp and skipped it, while SafeWindow learned it. The two learners
disagreed about the same event.
At cue start the upstream evidence consisted of lost, direction-unconfirmed fragments,
not a reliable incoming trajectory. A gap-derived ETA is not proof of vehicle-free
future occupancy. These logs do not establish the exact colliding vehicle.

Signal 5:
Paint ended 1792872480.896522; Space was 1792872480.925758, about 29 ms later.
The input snapshot said WAIT and outside deadline. CV later guessed action onset
at 1792872482.2053442 and trained a delayed GREEN failure. The recorded input
contradicts that GREEN attribution. This is not a confirmed in-GREEN failure.

Signal 21:
Paint ended 1792874503.5254004; Space was 1792874503.7020779, about 177 ms later.
Input snapshot said ETA HOLD and outside deadline. Delayed CV attribution again
trained it as a GREEN failure. Exclude from strict GREEN accuracy/training.
This does not blame the user: the brief cues themselves are difficult to act upon.

Signals 9 and 20:
Input was valid; traces show little/temporary movement and return near the same lane,
without independent settled success or confirmed reset. Keep UNKNOWN; do not claim
either crash or safe success from these coordinates alone.

## Implemented fixes
1. Persist input_validated_deadline on a validated input-owned attempt.
OnlineLearner uses verified input timing and movement rather than an older logical
GREEN end timestamp to decide lateness. The original observed input validation
(focus, signal, generation, timestamp, deadline and chicken position) remains required.
2. A fresh, same-foreground Space record explicitly outside GREEN closes the
unacted current/pending cue as UNKNOWN recorded_input_outside_green. Delayed CV
movement can no longer reclaim that cue and train the late/manual action as GREEN.
Manual learning remains separate. Stale/focus-mismatched records cannot cancel cues.
3. Outcome audit now retains the validated deadline and contradictory input timestamp.
Versioned input/presentation/runtime/safe-window logs use v5518.
No retrospective relabelling of model weights or old logs; no global thresholds changed.

## Why no broad stricter veto
The unresolved-vehicle shadow condition occurred on 40/43 cue starts.
Enabling it broadly would remove most observed opportunities, including successes.
There is no validated threshold in these data that separates the genuine input-owned
failure from the input-owned success and generalizes to other runs.
This build fixes demonstrable label contradictions. It does not claim to prevent
signal 1's original bad prediction or establish improved live accuracy.

## Validation
See V5518_TEST_RESULTS.json. New tests reproduce signal-1 timing disagreement and
both off-GREEN input timings. They verify source learning for valid input, no delayed
CV reclaim for invalid input, and stale/focus exclusions. Current prior tests cover
tracking, viewport handling, landing, presentation, forecasting and feedback.
The old test_v550_causal_landing.py fails on the unchanged baseline as previously
documented and is excluded, not counted as passing.
Tests use state/record replay, not video replay or native Windows game input.
